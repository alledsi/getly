"""
Authentification et administration des utilisateurs de Getly.

Stockage dans une base SQLite locale (`getly_users.db`, à la racine du
projet par défaut, exclue de Git comme `.env`) — indépendante par
déploiement (un poste ou un serveur donné a ses propres comptes). Les
mots de passe ne sont jamais stockés en clair : hachage
PBKDF2-HMAC-SHA256 avec sel aléatoire par utilisateur (bibliothèque
standard Python, pas de dépendance supplémentaire).

L'emplacement du fichier peut être surchargé via la variable d'environnement
`GETLY_USERS_DB` (dans `.env`) si le dossier du projet n'est pas
inscriptible par l'utilisateur qui exécute l'application (ex. service
systemd durci) : mets alors ce chemin vers un dossier accessible en
écriture, par exemple `/var/lib/getly/getly_users.db`.

Au tout premier lancement (base vide), un compte administrateur par
défaut est créé automatiquement :
    identifiant : admin
    mot de passe : admin123
Ce compte est marqué "doit changer son mot de passe à la prochaine
connexion" — l'application impose le changement avant de donner accès
au reste du menu.

Chaque utilisateur peut être rattaché à une **direction** (table
`directions`, ex. "Contrôle de gestion", "Comptabilité"...), et chaque
direction se voit attribuer un ensemble de rapports (extractions) et de
tableaux de bord visibles (table `direction_permissions`). Un
administrateur voit toujours tout, quelle que soit sa direction. Un
utilisateur sans direction assignée conserve un accès complet aux
rapports (comportement historique, pour ne pas casser les déploiements
existants) mais n'a accès à aucun tableau de bord — cette fonctionnalité
est nouvelle et réservée par direction dès le départ (voir
`get_visible_item_ids`).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import secrets
import sqlite3
from contextlib import contextmanager
from typing import Optional

import pandas as pd
from dotenv import load_dotenv

load_dotenv()  # au cas où auth.py est importé avant config.py

_DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "getly_users.db")
DB_PATH = os.getenv("GETLY_USERS_DB", _DEFAULT_DB_PATH)

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin123"

MOT_DE_PASSE_LONGUEUR_MIN = 8

_PBKDF2_ITERATIONS = 260_000

# Identifiants des tableaux de bord (dashboards/__init__.py) accordés par
# défaut à la direction "Contrôle de gestion" amorcée au premier lancement.
# À garder synchronisé avec dashboards.DASHBOARDS si de nouveaux tableaux
# de bord sont ajoutés (une désynchronisation n'est pas dangereuse : elle
# prive juste le nouveau tableau de bord de son octroi automatique, un
# administrateur peut toujours l'accorder depuis « Administration »).
_DASHBOARD_IDS_SEED_CONTROLE_GESTION = [
    "rendement_portefeuille",
    "cout_du_risque",
    "situation_adhesions",
    "situation_revenus",
    "situation_charges",
    "resultat",
]
DIRECTION_CONTROLE_GESTION = "Contrôle de gestion"


# ---------------------------------------------------------------------------
# Connexion / initialisation
# ---------------------------------------------------------------------------


@contextmanager
def _connect():
    dossier = os.path.dirname(DB_PATH)
    if dossier and not os.path.isdir(dossier):
        os.makedirs(dossier, exist_ok=True)
    try:
        conn = sqlite3.connect(DB_PATH)
    except sqlite3.OperationalError as exc:
        raise sqlite3.OperationalError(
            f"Impossible d'ouvrir la base des utilisateurs à l'emplacement "
            f"« {DB_PATH} » ({exc}). Vérifie que l'utilisateur qui exécute "
            f"l'application a le droit d'écrire dans ce dossier (permissions, "
            f"ou restrictions systemd comme ProtectHome/ProtectSystem/"
            f"ReadWritePaths), ou redéfinis l'emplacement via la variable "
            f"d'environnement GETLY_USERS_DB dans .env."
        ) from exc
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Crée les tables (utilisateurs, directions, permissions) si
    nécessaire, migre les bases existantes (ajout de `direction_id`),
    amorce un compte administrateur par défaut si la base est vide, et
    amorce la direction "Contrôle de gestion" (accès à tous les tableaux
    de bord) si elle n'existe pas encore."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS directions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nom TEXT UNIQUE NOT NULL,
                cree_le TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                nom_complet TEXT,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                actif INTEGER NOT NULL DEFAULT 1,
                doit_changer_mdp INTEGER NOT NULL DEFAULT 0,
                direction_id INTEGER REFERENCES directions(id),
                cree_le TEXT NOT NULL
            )
            """
        )
        # Migration : les bases créées avant l'ajout de la colonne
        # direction_id n'ont pas cette colonne — on l'ajoute si besoin.
        colonnes_users = {
            row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()
        }
        if "direction_id" not in colonnes_users:
            conn.execute("ALTER TABLE users ADD COLUMN direction_id INTEGER REFERENCES directions(id)")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS direction_permissions (
                direction_id INTEGER NOT NULL REFERENCES directions(id) ON DELETE CASCADE,
                item_type TEXT NOT NULL CHECK (item_type IN ('extraction', 'dashboard')),
                item_id TEXT NOT NULL,
                PRIMARY KEY (direction_id, item_type, item_id)
            )
            """
        )

        nb = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        if nb == 0:
            password_hash, password_salt = _hash_password(DEFAULT_ADMIN_PASSWORD)
            conn.execute(
                """
                INSERT INTO users
                    (username, nom_complet, password_hash, password_salt, role, actif, doit_changer_mdp, cree_le)
                VALUES (?, ?, ?, ?, 'admin', 1, 1, ?)
                """,
                (
                    DEFAULT_ADMIN_USERNAME,
                    "Administrateur",
                    password_hash,
                    password_salt,
                    dt.datetime.now().isoformat(timespec="seconds"),
                ),
            )

        # Amorce la direction "Contrôle de gestion" avec accès à tous les
        # tableaux de bord existants au moment de l'amorçage (l'admin peut
        # ensuite ajuster librement depuis « Administration »). Ne s'exécute
        # qu'une fois : si la direction existe déjà, on ne touche à rien
        # (pour ne pas écraser des permissions que l'admin aurait modifiées).
        cg = conn.execute(
            "SELECT id FROM directions WHERE nom = ?", (DIRECTION_CONTROLE_GESTION,)
        ).fetchone()
        if cg is None:
            curseur = conn.execute(
                "INSERT INTO directions (nom, cree_le) VALUES (?, ?)",
                (DIRECTION_CONTROLE_GESTION, dt.datetime.now().isoformat(timespec="seconds")),
            )
            cg_id = curseur.lastrowid
            conn.executemany(
                "INSERT OR IGNORE INTO direction_permissions (direction_id, item_type, item_id) VALUES (?, 'dashboard', ?)",
                [(cg_id, dashboard_id) for dashboard_id in _DASHBOARD_IDS_SEED_CONTROLE_GESTION],
            )


# ---------------------------------------------------------------------------
# Hachage des mots de passe
# ---------------------------------------------------------------------------


def _hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ITERATIONS
    )
    return digest.hex(), salt


def _verifier_mot_de_passe(password: str, password_hash: str, password_salt: str) -> bool:
    candidat, _ = _hash_password(password, password_salt)
    return secrets.compare_digest(candidat, password_hash)


def _valider_mot_de_passe(password: str) -> Optional[str]:
    if not password or len(password) < MOT_DE_PASSE_LONGUEUR_MIN:
        return f"Le mot de passe doit contenir au moins {MOT_DE_PASSE_LONGUEUR_MIN} caractères."
    return None


# ---------------------------------------------------------------------------
# Authentification
# ---------------------------------------------------------------------------


def authentifier(username: str, password: str) -> Optional[dict]:
    """Vérifie l'identifiant/mot de passe. Retourne les infos utilisateur
    (sans le hash) si valide et le compte est actif, sinon None."""
    if not username or not password:
        return None
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT u.*, d.nom AS direction_nom
            FROM users u
            LEFT JOIN directions d ON d.id = u.direction_id
            WHERE u.username = ?
            """,
            (username.strip(),),
        ).fetchone()
    if row is None:
        return None
    if not row["actif"]:
        return None
    if not _verifier_mot_de_passe(password, row["password_hash"], row["password_salt"]):
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "nom_complet": row["nom_complet"],
        "role": row["role"],
        "doit_changer_mdp": bool(row["doit_changer_mdp"]),
        "direction_id": row["direction_id"],
        "direction_nom": row["direction_nom"],
    }


def changer_mon_mot_de_passe(user_id: int, ancien_mdp: str, nouveau_mdp: str) -> tuple[bool, str]:
    """Un utilisateur change lui-même son mot de passe (ancien mot de passe requis)."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            return False, "Utilisateur introuvable."
        if not _verifier_mot_de_passe(ancien_mdp, row["password_hash"], row["password_salt"]):
            return False, "Mot de passe actuel incorrect."
        erreur = _valider_mot_de_passe(nouveau_mdp)
        if erreur:
            return False, erreur
        password_hash, password_salt = _hash_password(nouveau_mdp)
        conn.execute(
            "UPDATE users SET password_hash = ?, password_salt = ?, doit_changer_mdp = 0 WHERE id = ?",
            (password_hash, password_salt, user_id),
        )
    return True, "Mot de passe modifié avec succès."


# ---------------------------------------------------------------------------
# Administration des utilisateurs
# ---------------------------------------------------------------------------


def lister_utilisateurs() -> pd.DataFrame:
    with _connect() as conn:
        df = pd.read_sql_query(
            """
            SELECT u.id, u.username, u.nom_complet, u.direction_id, d.nom AS direction_nom,
                   u.role, u.actif, u.doit_changer_mdp, u.cree_le
            FROM users u
            LEFT JOIN directions d ON d.id = u.direction_id
            ORDER BY u.username
            """,
            conn,
        )
    return df


def creer_utilisateur(
    username: str,
    password: str,
    role: str = "user",
    nom_complet: Optional[str] = None,
    direction_id: Optional[int] = None,
) -> tuple[bool, str]:
    username = (username or "").strip()
    if not username:
        return False, "L'identifiant est obligatoire."
    if role not in ("user", "admin"):
        return False, "Rôle invalide."
    erreur = _valider_mot_de_passe(password)
    if erreur:
        return False, erreur

    with _connect() as conn:
        existe = conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existe:
            return False, f"L'identifiant « {username} » existe déjà."
        if direction_id is not None:
            direction_existe = conn.execute(
                "SELECT 1 FROM directions WHERE id = ?", (direction_id,)
            ).fetchone()
            if not direction_existe:
                return False, "Direction introuvable."
        password_hash, password_salt = _hash_password(password)
        conn.execute(
            """
            INSERT INTO users
                (username, nom_complet, password_hash, password_salt, role, actif, doit_changer_mdp, direction_id, cree_le)
            VALUES (?, ?, ?, ?, ?, 1, 1, ?, ?)
            """,
            (
                username,
                (nom_complet or "").strip() or None,
                password_hash,
                password_salt,
                role,
                direction_id,
                dt.datetime.now().isoformat(timespec="seconds"),
            ),
        )
    return True, f"Utilisateur « {username} » créé."


def modifier_role(user_id: int, role: str) -> tuple[bool, str]:
    if role not in ("user", "admin"):
        return False, "Rôle invalide."
    with _connect() as conn:
        nb_admins_actifs = conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND actif = 1"
        ).fetchone()["n"]
        cible = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if cible is None:
            return False, "Utilisateur introuvable."
        if cible["role"] == "admin" and role == "user" and nb_admins_actifs <= 1:
            return False, "Impossible : c'est le dernier administrateur actif."
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
    return True, "Rôle mis à jour."


def activer_desactiver(user_id: int, actif: bool) -> tuple[bool, str]:
    with _connect() as conn:
        cible = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if cible is None:
            return False, "Utilisateur introuvable."
        if cible["role"] == "admin" and not actif:
            nb_admins_actifs = conn.execute(
                "SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND actif = 1"
            ).fetchone()["n"]
            if nb_admins_actifs <= 1:
                return False, "Impossible : c'est le dernier administrateur actif."
        conn.execute("UPDATE users SET actif = ? WHERE id = ?", (1 if actif else 0, user_id))
    return True, "Statut mis à jour."


def reinitialiser_mot_de_passe(user_id: int, nouveau_mdp: str) -> tuple[bool, str]:
    """Un administrateur réinitialise le mot de passe d'un utilisateur ;
    celui-ci devra le changer à sa prochaine connexion."""
    erreur = _valider_mot_de_passe(nouveau_mdp)
    if erreur:
        return False, erreur
    with _connect() as conn:
        cible = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if cible is None:
            return False, "Utilisateur introuvable."
        password_hash, password_salt = _hash_password(nouveau_mdp)
        conn.execute(
            "UPDATE users SET password_hash = ?, password_salt = ?, doit_changer_mdp = 1 WHERE id = ?",
            (password_hash, password_salt, user_id),
        )
    return True, "Mot de passe réinitialisé."


def supprimer_utilisateur(user_id: int) -> tuple[bool, str]:
    with _connect() as conn:
        cible = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if cible is None:
            return False, "Utilisateur introuvable."
        if cible["role"] == "admin":
            nb_admins_actifs = conn.execute(
                "SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND actif = 1"
            ).fetchone()["n"]
            if nb_admins_actifs <= 1:
                return False, "Impossible : c'est le dernier administrateur actif."
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return True, "Utilisateur supprimé."


def modifier_direction_utilisateur(user_id: int, direction_id: Optional[int]) -> tuple[bool, str]:
    """Rattache (ou détache si `direction_id=None`) un utilisateur à une direction."""
    with _connect() as conn:
        cible = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if cible is None:
            return False, "Utilisateur introuvable."
        if direction_id is not None:
            direction_existe = conn.execute(
                "SELECT 1 FROM directions WHERE id = ?", (direction_id,)
            ).fetchone()
            if not direction_existe:
                return False, "Direction introuvable."
        conn.execute("UPDATE users SET direction_id = ? WHERE id = ?", (direction_id, user_id))
    return True, "Direction mise à jour."


# ---------------------------------------------------------------------------
# Directions et permissions (rapports/tableaux de bord visibles par direction)
# ---------------------------------------------------------------------------


def lister_directions() -> pd.DataFrame:
    """Une ligne par direction, avec le nombre d'utilisateurs rattachés."""
    with _connect() as conn:
        df = pd.read_sql_query(
            """
            SELECT d.id, d.nom, d.cree_le, COUNT(u.id) AS nb_utilisateurs
            FROM directions d
            LEFT JOIN users u ON u.direction_id = d.id
            GROUP BY d.id, d.nom, d.cree_le
            ORDER BY d.nom
            """,
            conn,
        )
    return df


def creer_direction(nom: str) -> tuple[bool, str]:
    nom = (nom or "").strip()
    if not nom:
        return False, "Le nom de la direction est obligatoire."
    with _connect() as conn:
        existe = conn.execute("SELECT 1 FROM directions WHERE nom = ?", (nom,)).fetchone()
        if existe:
            return False, f"La direction « {nom} » existe déjà."
        conn.execute(
            "INSERT INTO directions (nom, cree_le) VALUES (?, ?)",
            (nom, dt.datetime.now().isoformat(timespec="seconds")),
        )
    return True, f"Direction « {nom} » créée."


def renommer_direction(direction_id: int, nouveau_nom: str) -> tuple[bool, str]:
    nouveau_nom = (nouveau_nom or "").strip()
    if not nouveau_nom:
        return False, "Le nom de la direction est obligatoire."
    with _connect() as conn:
        cible = conn.execute("SELECT * FROM directions WHERE id = ?", (direction_id,)).fetchone()
        if cible is None:
            return False, "Direction introuvable."
        existe = conn.execute(
            "SELECT 1 FROM directions WHERE nom = ? AND id != ?", (nouveau_nom, direction_id)
        ).fetchone()
        if existe:
            return False, f"La direction « {nouveau_nom} » existe déjà."
        conn.execute("UPDATE directions SET nom = ? WHERE id = ?", (nouveau_nom, direction_id))
    return True, "Direction renommée."


def supprimer_direction(direction_id: int) -> tuple[bool, str]:
    with _connect() as conn:
        cible = conn.execute("SELECT * FROM directions WHERE id = ?", (direction_id,)).fetchone()
        if cible is None:
            return False, "Direction introuvable."
        nb_utilisateurs = conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE direction_id = ?", (direction_id,)
        ).fetchone()["n"]
        if nb_utilisateurs > 0:
            return False, (
                f"Impossible : {nb_utilisateurs} utilisateur(s) sont encore rattachés à "
                f"cette direction. Réaffecte-les d'abord (ou détache-les, direction « (Aucune) »)."
            )
        conn.execute("DELETE FROM direction_permissions WHERE direction_id = ?", (direction_id,))
        conn.execute("DELETE FROM directions WHERE id = ?", (direction_id,))
    return True, "Direction supprimée."


def obtenir_permissions_direction(direction_id: int) -> dict[str, set[str]]:
    """Retourne {'extraction': {id, ...}, 'dashboard': {id, ...}} pour une direction."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT item_type, item_id FROM direction_permissions WHERE direction_id = ?",
            (direction_id,),
        ).fetchall()
    resultat: dict[str, set[str]] = {"extraction": set(), "dashboard": set()}
    for row in rows:
        resultat.setdefault(row["item_type"], set()).add(row["item_id"])
    return resultat


def definir_permissions_direction(
    direction_id: int, item_type: str, item_ids: set[str]
) -> tuple[bool, str]:
    """Remplace entièrement les permissions d'un type ('extraction' ou
    'dashboard') pour une direction par l'ensemble `item_ids` donné."""
    if item_type not in ("extraction", "dashboard"):
        return False, "Type de permission invalide."
    with _connect() as conn:
        existe = conn.execute("SELECT 1 FROM directions WHERE id = ?", (direction_id,)).fetchone()
        if not existe:
            return False, "Direction introuvable."
        conn.execute(
            "DELETE FROM direction_permissions WHERE direction_id = ? AND item_type = ?",
            (direction_id, item_type),
        )
        if item_ids:
            conn.executemany(
                "INSERT INTO direction_permissions (direction_id, item_type, item_id) VALUES (?, ?, ?)",
                [(direction_id, item_type, item_id) for item_id in item_ids],
            )
    return True, "Permissions enregistrées."


def get_visible_item_ids(user: dict, item_type: str) -> Optional[set[str]]:
    """Ensemble des identifiants (extraction ou tableau de bord) visibles
    par cet utilisateur pour `item_type` ('extraction' ou 'dashboard').

    Retourne `None` pour signifier « accès à tout » (administrateur, ou —
    seulement pour item_type='extraction' — utilisateur sans direction
    assignée, afin de préserver l'accès complet aux rapports des comptes
    créés avant l'introduction des directions). Un utilisateur sans
    direction n'a en revanche accès à aucun tableau de bord : cette
    fonctionnalité est nouvelle et réservée par direction dès le départ.
    Pour un utilisateur avec direction, retourne l'ensemble (éventuellement
    vide) explicitement accordé à sa direction."""
    if user.get("role") == "admin":
        return None
    direction_id = user.get("direction_id")
    if direction_id is None:
        return None if item_type == "extraction" else set()
    permissions = obtenir_permissions_direction(direction_id)
    return permissions.get(item_type, set())

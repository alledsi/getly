"""
Authentification et administration des utilisateurs de Getly.

Stockage dans une base SQLite locale (`getly_users.db`, à la racine du
projet, exclue de Git comme `.env`) — indépendante par déploiement (un
poste ou un serveur donné a ses propres comptes). Les mots de passe ne
sont jamais stockés en clair : hachage PBKDF2-HMAC-SHA256 avec sel
aléatoire par utilisateur (bibliothèque standard Python, pas de
dépendance supplémentaire).

Au tout premier lancement (base vide), un compte administrateur par
défaut est créé automatiquement :
    identifiant : admin
    mot de passe : admin123
Ce compte est marqué "doit changer son mot de passe à la prochaine
connexion" — l'application impose le changement avant de donner accès
au reste du menu.
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

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "getly_users.db")

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin123"

MOT_DE_PASSE_LONGUEUR_MIN = 8

_PBKDF2_ITERATIONS = 260_000


# ---------------------------------------------------------------------------
# Connexion / initialisation
# ---------------------------------------------------------------------------


@contextmanager
def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Crée la table des utilisateurs si nécessaire, et amorce un compte
    administrateur par défaut si la base est vide."""
    with _connect() as conn:
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
                cree_le TEXT NOT NULL
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
            "SELECT * FROM users WHERE username = ?", (username.strip(),)
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
            "SELECT id, username, nom_complet, role, actif, doit_changer_mdp, cree_le "
            "FROM users ORDER BY username",
            conn,
        )
    return df


def creer_utilisateur(
    username: str,
    password: str,
    role: str = "user",
    nom_complet: Optional[str] = None,
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
        password_hash, password_salt = _hash_password(password)
        conn.execute(
            """
            INSERT INTO users
                (username, nom_complet, password_hash, password_salt, role, actif, doit_changer_mdp, cree_le)
            VALUES (?, ?, ?, ?, ?, 1, 1, ?)
            """,
            (
                username,
                (nom_complet or "").strip() or None,
                password_hash,
                password_salt,
                role,
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

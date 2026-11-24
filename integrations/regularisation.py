"""
Intégration "Régularisation" : importe un fichier Excel de régularisation
(Immo ou Classic) dans la table Oracle `TABLE_REGUL`.

Fichiers attendus (format fourni par l'utilisateur, aucune colonne
supplémentaire n'est demandée) :
    - Immo    : Débit, Crédit, Libellé écriture, Montant, Date
    - Classic : Débit, Crédit, Libellé écriture, Montant, Date,
                Code opération

Mapping vers TABLE_REGUL (confirmé par l'utilisateur le 24/11/2026) :
    Débit            -> CPT_DB
    Crédit           -> CPT_CR
    Libellé écriture -> LIB_MVT
    Montant          -> MT_MVT
    Date             -> DATE_MVT
    Code opération   -> CODE_OPER (absent/NULL pour un fichier Immo)
Les autres colonnes de TABLE_REGUL (CPT, MATRICULE_CLIENT, CODE_BUREAU,
SENS) ne sont pas renseignées par cette intégration : laissées à NULL,
comme demandé explicitement par l'utilisateur ("les autres champs tu les
laisse vides").

À chaque import confirmé, TABLE_REGUL est entièrement vidée avant
l'insertion des nouvelles lignes (voir `db.truncate_and_insert`) — un
nouvel upload remplace donc complètement le contenu précédent, pour les
deux types de régularisation (Immo et Classic partagent la même table).

Correction du 24/11/2026 : les colonnes Débit, Crédit et Code opération
sont relues directement via openpyxl (voir `_lire_colonnes_brutes`) plutôt
que de se fier uniquement à `pandas.read_excel`. En effet, un compte
stocké comme NOMBRE dans Excel mais affiché avec des zéros de tête via un
format d'affichage personnalisé (ex. la valeur 895848 affichée "0895848")
redevient "895848" si on lit juste la valeur numérique brute — il faut
tenir compte du format d'affichage de la cellule pour reconstituer le bon
texte. Signalé par l'utilisateur ("faut le prendre en texte").
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Optional

import openpyxl
import pandas as pd
import streamlit as st

import db

_TABLE = "TABLE_REGUL"

# Ordre des colonnes de TABLE_REGUL (doit correspondre à la structure
# Oracle réelle communiquée par l'utilisateur).
_COLONNES_TABLE = [
    "CPT_CR",
    "CPT_DB",
    "MT_MVT",
    "CPT",
    "MATRICULE_CLIENT",
    "CODE_BUREAU",
    "LIB_MVT",
    "DATE_MVT",
    "SENS",
    "CODE_OPER",
]

# Colonnes attendues dans le fichier Excel, par type de régularisation
# (ordre et libellés exacts, tels que fournis par l'utilisateur).
_COLONNES_FICHIER: dict[str, list[str]] = {
    "Immo": ["Débit", "Crédit", "Libellé écriture", "Montant", "Date"],
    "Classic": ["Débit", "Crédit", "Libellé écriture", "Montant", "Date", "Code opération"],
}

_COLONNES_OBLIGATOIRES = ["Débit", "Crédit", "Libellé écriture", "Montant", "Date"]


def _valider_colonnes(df: pd.DataFrame, type_regul: str) -> Optional[str]:
    """Vérifie que les colonnes obligatoires attendues pour ce type sont
    bien présentes (dans l'ordre), sans exiger qu'il n'y ait rien d'autre
    après (tolère une colonne "Code opération" en trop sur un fichier
    envoyé par erreur comme Immo, par exemple — elle sera alors simplement
    ignorée)."""
    attendu = _COLONNES_FICHIER[type_regul][: len(_COLONNES_OBLIGATOIRES)]
    colonnes_fichier = list(df.columns)[: len(attendu)]
    if colonnes_fichier != attendu:
        return (
            f"Colonnes inattendues pour un fichier « {type_regul} ». "
            f"Attendu au minimum, dans cet ordre : {attendu}. "
            f"Trouvé : {list(df.columns)}."
        )
    if type_regul == "Classic" and "Code opération" not in df.columns:
        return (
            "Colonne « Code opération » manquante — obligatoire pour un "
            "fichier Classic."
        )
    return None


def _est_vide(valeur) -> bool:
    if valeur is None:
        return True
    try:
        return bool(pd.isna(valeur))
    except (TypeError, ValueError):
        return False


_RE_FORMAT_ZERO_PAD = re.compile(r"0+")


def _largeur_zero_pad(number_format: Optional[str]) -> Optional[int]:
    """Si le format d'affichage Excel d'une cellule numérique sert
    uniquement à compléter le nombre par des zéros de tête sur une largeur
    fixe (ex. ``"0000000"`` pour afficher 895848 en "0895848"), renvoie
    cette largeur ; sinon `None` (format "General", séparateur de
    milliers, décimales...) — on ne touche alors pas à la valeur."""
    if not number_format or number_format == "General":
        return None
    nettoye = number_format.replace(",", "")
    if not _RE_FORMAT_ZERO_PAD.fullmatch(nettoye):
        return None
    return len(nettoye)


def _valeur_brute_cellule(cellule) -> object:
    """Valeur d'une cellule Excel en respectant un éventuel format
    d'affichage à zéros de tête : une cellule stockée comme NOMBRE
    (895848) mais affichée sur une largeur fixe (ex. "0895848") renvoie la
    chaîne zero-paddée correspondante ; sinon la valeur brute (nombre ou
    texte), inchangée."""
    if cellule is None:
        return None
    valeur = cellule.value
    if isinstance(valeur, (int, float)) and not isinstance(valeur, bool):
        largeur = _largeur_zero_pad(cellule.number_format)
        if largeur:
            return str(int(valeur)).zfill(largeur)
    return valeur


def _lire_colonnes_brutes(fichier, colonnes: list[str], nb_lignes: int) -> dict[str, list]:
    """Relit directement via openpyxl les colonnes passées (identifiées par
    leur libellé d'en-tête), en respectant le format d'affichage à zéros de
    tête éventuel (voir `_valeur_brute_cellule`) — `pandas.read_excel` perd
    silencieusement cette information pour une cellule stockée comme
    nombre (un compte "0895848" affiché ainsi mais stocké comme le nombre
    895848 redeviendrait "895848" sans ce correctif)."""
    fichier.seek(0)
    classeur = openpyxl.load_workbook(fichier, data_only=True, read_only=True)
    feuille = classeur.worksheets[0]
    lignes_iter = feuille.iter_rows()
    try:
        entetes = [c.value for c in next(lignes_iter)]
    except StopIteration:
        return {nom: [] for nom in colonnes}

    index_colonnes = {nom: entetes.index(nom) for nom in colonnes if nom in entetes}
    resultat: dict[str, list] = {nom: [] for nom in colonnes}
    for ligne in lignes_iter:
        for nom, idx in index_colonnes.items():
            cellule = ligne[idx] if idx < len(ligne) else None
            resultat[nom].append(_valeur_brute_cellule(cellule))

    # Sécurité : aligne la longueur sur le nombre de lignes lu par pandas
    # (devrait déjà correspondre, les deux lisant la même plage de données).
    for nom in colonnes:
        valeurs = resultat[nom]
        if len(valeurs) < nb_lignes:
            valeurs.extend([None] * (nb_lignes - len(valeurs)))
        resultat[nom] = valeurs[:nb_lignes]
    return resultat


def _compte_str(valeur) -> Optional[str]:
    """Numéro de compte (Débit/Crédit) -> chaîne sans décimale, quel que
    soit le type lu depuis Excel (texte déjà, ou nombre si Excel l'a
    stocké sans le formater en texte)."""
    if _est_vide(valeur):
        return None
    if isinstance(valeur, str):
        return valeur.strip()
    return str(int(valeur))


def _libelle_str(valeur) -> Optional[str]:
    if _est_vide(valeur):
        return None
    return str(valeur).strip()


def _montant(valeur) -> Optional[float]:
    if _est_vide(valeur):
        return None
    return float(valeur)


def _date_mvt(valeur) -> Optional[dt.datetime]:
    if _est_vide(valeur):
        return None
    if isinstance(valeur, pd.Timestamp):
        return valeur.to_pydatetime()
    if isinstance(valeur, dt.datetime):
        return valeur
    if isinstance(valeur, dt.date):
        return dt.datetime.combine(valeur, dt.time.min)
    return None


def _code_oper_str(valeur) -> Optional[str]:
    if _est_vide(valeur):
        return None
    if isinstance(valeur, str):
        return valeur.strip()
    # Excel peut stocker le code en nombre (ex. 241) et faire perdre un
    # éventuel zéro de tête (ex. 041 -> 41) : on complète sur 3 caractères,
    # comme les codes opération à 3 chiffres utilisés ailleurs dans Getly.
    return str(int(valeur)).zfill(3)


def _construire_lignes(df: pd.DataFrame, type_regul: str) -> list[dict]:
    lignes: list[dict] = []
    for _, row in df.iterrows():
        code_oper = (
            _code_oper_str(row["Code opération"])
            if type_regul == "Classic" and "Code opération" in df.columns
            else None
        )
        lignes.append(
            {
                "CPT_CR": _compte_str(row["Crédit"]),
                "CPT_DB": _compte_str(row["Débit"]),
                "MT_MVT": _montant(row["Montant"]),
                "CPT": None,
                "MATRICULE_CLIENT": None,
                "CODE_BUREAU": None,
                "LIB_MVT": _libelle_str(row["Libellé écriture"]),
                "DATE_MVT": _date_mvt(row["Date"]),
                "SENS": None,
                "CODE_OPER": code_oper,
            }
        )
    return lignes


def render() -> None:
    st.header("🔄 Régularisation")
    st.caption(
        "Importe un fichier Excel de régularisation (Immo ou Classic) dans "
        "TABLE_REGUL. **Chaque import remplace entièrement** le contenu "
        "actuel de la table."
    )

    type_regul = st.radio(
        "Type de régularisation", ["Immo", "Classic"], horizontal=True, key="regul_type"
    )

    fichier = st.file_uploader(
        f"Fichier Excel — Régularisation {type_regul}",
        type=["xlsx"],
        key=f"regul_upload_{type_regul}",
    )
    if fichier is None:
        return

    try:
        df_brut = pd.read_excel(fichier)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Impossible de lire ce fichier Excel : {exc}")
        return

    erreur = _valider_colonnes(df_brut, type_regul)
    if erreur:
        st.error(erreur)
        return

    # Relit Débit/Crédit/Code opération directement via openpyxl : certains
    # comptes/codes sont stockés comme des nombres dans Excel mais affichés
    # avec des zéros de tête (ex. "0895848") — pandas.read_excel les ferait
    # sinon redevenir "895848" (voir _lire_colonnes_brutes ci-dessus).
    colonnes_a_corriger = ["Débit", "Crédit"]
    if "Code opération" in df_brut.columns:
        colonnes_a_corriger.append("Code opération")
    try:
        colonnes_brutes = _lire_colonnes_brutes(fichier, colonnes_a_corriger, len(df_brut))
        for nom, valeurs in colonnes_brutes.items():
            df_brut[nom] = valeurs
    except Exception as exc:  # noqa: BLE001
        # Filet de sécurité : si la relecture openpyxl échoue, on garde les
        # valeurs lues par pandas (comportement d'avant ce correctif)
        # plutôt que de bloquer complètement l'import.
        st.warning(
            f"Impossible de vérifier les zéros de tête des comptes/codes "
            f"({exc}) — valeurs lues normalement, à vérifier après import."
        )

    # Ignore les lignes totalement vides (ex. ligne blanche en fin de
    # fichier Excel).
    df_utile = df_brut.dropna(subset=_COLONNES_OBLIGATOIRES, how="all")

    if df_utile.empty:
        st.warning("Aucune ligne exploitable dans ce fichier.")
        return

    lignes = _construire_lignes(df_utile, type_regul)

    st.write(
        f"**{len(lignes)} ligne(s)** prête(s) à être importée(s) dans `TABLE_REGUL` "
        f"(type : {type_regul})."
    )
    st.dataframe(pd.DataFrame(lignes), width="stretch", hide_index=True)

    st.warning(
        "⚠️ Cette action **vide entièrement** TABLE_REGUL avant d'y insérer "
        "ces lignes. Toute donnée actuellement présente dans la table sera "
        "définitivement perdue."
    )

    if st.button("🗑️➜📥 Vider et importer dans TABLE_REGUL", type="primary"):
        try:
            with st.spinner("Import en cours..."):
                nb = db.truncate_and_insert(_TABLE, _COLONNES_TABLE, lignes)
            st.success(
                f"TABLE_REGUL vidée puis {nb} ligne(s) importée(s) "
                f"(régularisation {type_regul})."
            )
        except Exception as exc:  # noqa: BLE001
            st.error(f"Échec de l'import : {exc}")

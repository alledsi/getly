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
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

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

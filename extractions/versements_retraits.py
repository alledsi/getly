"""
Extraction : Versements et retraits.

Mouvements de caisse de versement/retrait (table EVENEMENT), restreints
aux codes opération **001, 009, 007, 010** (règle métier fixe, reprise
telle quelle de la requête SQL fournie par l'utilisateur le 20/11/2026 —
non modifiable depuis le formulaire, comme pour les codes
décaissement/remboursement d'Opérations sur le crédit). `SELECT DISTINCT`
conservé tel quel.

Filtres obligatoires : **date début** et **date fin** (sur `DATE_MVT`,
bornes incluses — remplace le filtre sur une seule date exacte de la
requête d'origine, pour couvrir une période). Filtres facultatifs :
localisation hiérarchique (Mutuelle -> Agence -> Bureau) — jointure
`LEFT JOIN MUTUELLE` ajoutée uniquement pour permettre le filtre par
mutuelle (absente de la requête d'origine, pas de colonne affichée en
plus).

Les colonnes affichées correspondent à la requête fournie par
l'utilisateur, dans le même ordre, mais celle-ci ne donnait AUCUN alias
`AS` (noms de colonnes bruts) : des alias explicites ont donc été
ajoutés ici pour la lisibilité de l'affichage/export, avec un suffixe
`_CLIENT`/`_OPERATEUR` pour distinguer les deux colonnes `TYPE_PIECE`
(une sur CLIENT, une sur EVENEMENT — qui seraient sinon homonymes dans
le résultat) et les deux colonnes `DATE_DELIVRANCE_PIECE`/
`DATE_NAISSANCE` (même situation). Aucune colonne de la requête
d'origine n'a été ajoutée ni retirée.

Table EVUTI (alias `u`, colonne `NOMU`) : même table/jointure que dans
`balance_agee.py`/`base_clientele_personnes_morales.py` (utilisateur
ayant enregistré le mouvement).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import streamlit as st

from db import fetch_df
from extractions.base import Extraction
from extractions.reference_data import (
    referentiel_localisation_cached,
    render_localisation_cascade,
)

# ---------------------------------------------------------------------------
# Filtres du formulaire
# ---------------------------------------------------------------------------


@dataclass
class VersementsRetraitsFilters:
    date_debut: Optional[dt.date]
    date_fin: Optional[dt.date]
    code_mutuelle: Optional[str] = None
    code_agence: Optional[str] = None
    code_bureau: Optional[str] = None

    def validate(self) -> Optional[str]:
        if not self.date_debut or not self.date_fin:
            return "La date de début et la date de fin sont obligatoires."
        if self.date_debut > self.date_fin:
            return "La date de début doit être antérieure ou égale à la date de fin."
        return None


# ---------------------------------------------------------------------------
# Accès aux données
# ---------------------------------------------------------------------------

# Codes opération "versement"/"retrait" — règle métier fixe reprise de la
# requête fournie par l'utilisateur, non exposée comme filtre.
_CODES_OPERATION_VERSEMENT_RETRAIT = ("001", "009", "007", "010")

_BASE_SQL = """
    SELECT DISTINCT
        r.CODE_REGION                            AS CODE_AGENCE,
        r.LIB_REGION                             AS NOM_AGENCE,
        e.CODE_CAISSE                            AS CODE_CAISSE,
        e.CODE_OPER                              AS CODE_OPERATION,
        e.CODE_BUREAU                            AS CODE_BUREAU,
        e.NO_COMPTE                              AS NO_COMPTE,
        e.DATE_MVT                               AS DATE_MVT,
        e.MT_MVT                                 AS MONTANT,
        e.STATUS_MVT                             AS STATUT_MVT,
        cl.MATRICULE_CLIENT                      AS MATRICULE_CLIENT,
        SUBSTR(cl.PRENOM_CLIENT, 1, 20)          AS PRENOM_CLIENT,
        SUBSTR(cl.RAISON_SOCIALE_CLIENT, 1, 12)  AS RAISON_SOCIALE_CLIENT,
        cl.NUMERO_PIECE_IDENTITE                 AS NUMERO_PIECE_IDENTITE_CLIENT,
        cl.TYPE_PIECE                            AS TYPE_PIECE_CLIENT,
        cl.DATE_DELIVRANCE_PIECE                 AS DATE_DELIVRANCE_PIECE_CLIENT,
        cl.ADRESSE_1                             AS ADRESSE_CLIENT,
        SUBSTR(cl.TEL_PORT, 1, 20)                AS TEL_PORT_CLIENT,
        cl.DATE_NAISSANCE_ENTREPRENEUR           AS DATE_NAISSANCE_ENTREPRENEUR,
        e.CODE_UTILISATEUR                       AS CODE_UTILISATEUR,
        u.NOMU                                   AS NOM_UTILISATEUR,
        e.PRENOM_OP_EVEN                         AS PRENOM_OPERATEUR,
        e.NOM_OP_EVEN                            AS NOM_OPERATEUR,
        e.ADR_OP_EVEN                            AS ADRESSE_OPERATEUR,
        e.CNI_OP_EVEN                            AS CNI_OPERATEUR,
        e.DATE_DELIV_PIECE                       AS DATE_DELIVRANCE_PIECE_OPERATEUR,
        e.NO_TELEPHONE_DEST                      AS NO_TELEPHONE_DEST,
        e.NO_TELEPHONE                           AS NO_TELEPHONE_OPERATEUR,
        e.TYPE_PIECE                             AS TYPE_PIECE_OPERATEUR,
        e.DATE_NAISSANCE                         AS DATE_NAISSANCE_OPERATEUR
    FROM EVENEMENT e
    JOIN COMPTE c          ON e.NO_COMPTE = c.NO_COMPTE
    JOIN BUREAU b          ON e.CODE_BUREAU = b.CODE_BUREAU
    JOIN REGION r          ON b.CODE_REGION = r.CODE_REGION
    JOIN OPERATION op      ON e.CODE_OPER = op.CODE_OPER
    JOIN CLIENT cl         ON c.MATRICULE_CLIENT = cl.MATRICULE_CLIENT
    JOIN EVUTI u           ON e.CODE_UTILISATEUR = u.CUTI
    LEFT JOIN MUTUELLE mut ON mut.CODE_MUTUELLE = r.CODE_MUTUELLE
    WHERE e.DATE_MVT >= :date_debut
      AND e.DATE_MVT <  :date_fin_exclusive
      AND e.CODE_OPER IN ({codes_operation})
      {filtres_optionnels}
    ORDER BY r.CODE_REGION
"""

_PLACEHOLDERS_CODES_OPERATION = ", ".join(
    f":code_oper_{i}" for i in range(len(_CODES_OPERATION_VERSEMENT_RETRAIT))
)

_COLONNES_FINALES = [
    "CODE_AGENCE",
    "NOM_AGENCE",
    "CODE_CAISSE",
    "CODE_OPERATION",
    "CODE_BUREAU",
    "NO_COMPTE",
    "DATE_MVT",
    "MONTANT",
    "STATUT_MVT",
    "MATRICULE_CLIENT",
    "PRENOM_CLIENT",
    "RAISON_SOCIALE_CLIENT",
    "NUMERO_PIECE_IDENTITE_CLIENT",
    "TYPE_PIECE_CLIENT",
    "DATE_DELIVRANCE_PIECE_CLIENT",
    "ADRESSE_CLIENT",
    "TEL_PORT_CLIENT",
    "DATE_NAISSANCE_ENTREPRENEUR",
    "CODE_UTILISATEUR",
    "NOM_UTILISATEUR",
    "PRENOM_OPERATEUR",
    "NOM_OPERATEUR",
    "ADRESSE_OPERATEUR",
    "CNI_OPERATEUR",
    "DATE_DELIVRANCE_PIECE_OPERATEUR",
    "NO_TELEPHONE_DEST",
    "NO_TELEPHONE_OPERATEUR",
    "TYPE_PIECE_OPERATEUR",
    "DATE_NAISSANCE_OPERATEUR",
]


def _construire_filtres(filters: VersementsRetraitsFilters) -> tuple[str, dict]:
    """Construit la clause WHERE optionnelle (localisation) et les
    paramètres associés."""
    params: dict = {}
    filtres_optionnels = ""

    if filters.code_mutuelle:
        filtres_optionnels += " AND mut.CODE_MUTUELLE = :code_mutuelle"
        params["code_mutuelle"] = filters.code_mutuelle.strip()

    if filters.code_agence:
        filtres_optionnels += " AND r.CODE_REGION = :code_agence"
        params["code_agence"] = filters.code_agence.strip()

    if filters.code_bureau:
        filtres_optionnels += " AND e.CODE_BUREAU = :code_bureau"
        params["code_bureau"] = filters.code_bureau.strip()

    return filtres_optionnels, params


def get_versements_retraits(filters: VersementsRetraitsFilters) -> pd.DataFrame:
    """Construit et exécute la requête des versements/retraits sur la
    période choisie."""
    error = filters.validate()
    if error:
        raise ValueError(error)

    filtres_optionnels, params = _construire_filtres(filters)
    params["date_debut"] = dt.datetime.combine(filters.date_debut, dt.time.min)
    params["date_fin_exclusive"] = dt.datetime.combine(
        filters.date_fin + dt.timedelta(days=1), dt.time.min
    )
    for i, code in enumerate(_CODES_OPERATION_VERSEMENT_RETRAIT):
        params[f"code_oper_{i}"] = code

    sql = _BASE_SQL.format(
        codes_operation=_PLACEHOLDERS_CODES_OPERATION,
        filtres_optionnels=filtres_optionnels,
    )

    df = fetch_df(sql, params)
    if df.empty:
        return pd.DataFrame(columns=_COLONNES_FINALES)
    return df[_COLONNES_FINALES]


# ---------------------------------------------------------------------------
# Formulaire Streamlit
# ---------------------------------------------------------------------------

LIBELLES_COLONNES = {
    "CODE_AGENCE": "Code agence",
    "NOM_AGENCE": "Agence",
    "CODE_CAISSE": "Code caisse",
    "CODE_OPERATION": "Code opération",
    "CODE_BUREAU": "Code bureau",
    "NO_COMPTE": "N° compte",
    "DATE_MVT": "Date mouvement",
    "MONTANT": "Montant",
    "STATUT_MVT": "Statut mouvement",
    "MATRICULE_CLIENT": "Matricule client",
    "PRENOM_CLIENT": "Prénom client",
    "RAISON_SOCIALE_CLIENT": "Raison sociale",
    "NUMERO_PIECE_IDENTITE_CLIENT": "N° pièce identité (client)",
    "TYPE_PIECE_CLIENT": "Type pièce (client)",
    "DATE_DELIVRANCE_PIECE_CLIENT": "Date délivrance pièce (client)",
    "ADRESSE_CLIENT": "Adresse client",
    "TEL_PORT_CLIENT": "Téléphone client",
    "DATE_NAISSANCE_ENTREPRENEUR": "Date naissance entrepreneur",
    "CODE_UTILISATEUR": "Code utilisateur",
    "NOM_UTILISATEUR": "Utilisateur",
    "PRENOM_OPERATEUR": "Prénom opérateur",
    "NOM_OPERATEUR": "Nom opérateur",
    "ADRESSE_OPERATEUR": "Adresse opérateur",
    "CNI_OPERATEUR": "CNI opérateur",
    "DATE_DELIVRANCE_PIECE_OPERATEUR": "Date délivrance pièce (opérateur)",
    "NO_TELEPHONE_DEST": "N° téléphone destinataire",
    "NO_TELEPHONE_OPERATEUR": "N° téléphone opérateur",
    "TYPE_PIECE_OPERATEUR": "Type pièce (opérateur)",
    "DATE_NAISSANCE_OPERATEUR": "Date naissance opérateur",
}


class VersementsRetraitsExtraction(Extraction):
    id = "versements_retraits"
    label = "Versements et retraits"
    description = (
        "Mouvements de caisse de versement et retrait (codes opération "
        "001/009/007/010) sur une période donnée."
    )
    icon = "💰"

    column_labels = LIBELLES_COLONNES
    montant_cols = {"MONTANT"}
    date_cols = {
        "DATE_MVT",
        "DATE_DELIVRANCE_PIECE_CLIENT",
        "DATE_NAISSANCE_ENTREPRENEUR",
        "DATE_DELIVRANCE_PIECE_OPERATEUR",
        "DATE_NAISSANCE_OPERATEUR",
    }
    total_cols = {"MONTANT"}

    def render_form(self) -> Optional[VersementsRetraitsFilters]:
        # NB : pas de st.form ici — les menus Mutuelle/Agence/Bureau sont en
        # cascade et doivent se recalculer immédiatement quand on change un
        # choix, ce que st.form empêche (il ne rerun qu'à la soumission).

        try:
            ref_localisation_df = referentiel_localisation_cached()
        except Exception:  # noqa: BLE001
            ref_localisation_df = pd.DataFrame(
                columns=[
                    "CODE_BUREAU", "LIBELLE_BUREAU",
                    "CODE_REGION", "LIB_REGION",
                    "CODE_MUTUELLE", "NOM_MUTUELLE",
                ]
            )
            st.warning(
                "Impossible de charger la liste des mutuelles/agences/bureaux "
                "depuis la base. Tu peux réessayer plus tard."
            )

        st.subheader("Critères de recherche")
        col1, col2 = st.columns(2)
        with col1:
            date_debut = st.date_input(
                "Date début *", value=dt.date.today() - dt.timedelta(days=7)
            )
        with col2:
            date_fin = st.date_input("Date fin *", value=dt.date.today())

        with st.expander("Filtres avancés (facultatifs)"):
            st.caption("Localisation (Mutuelle → Agence → Bureau)")
            code_mutuelle, code_agence, code_bureau = render_localisation_cascade(
                ref_localisation_df, key_prefix="versret_"
            )

        submitted = st.button(
            "🔍 Générer les versements et retraits", width="stretch", type="primary"
        )

        if not submitted:
            return None

        filters = VersementsRetraitsFilters(
            date_debut=date_debut,
            date_fin=date_fin,
            code_mutuelle=code_mutuelle or None,
            code_agence=code_agence or None,
            code_bureau=code_bureau or None,
        )

        erreur = filters.validate()
        if erreur:
            st.error(erreur)
            return None
        return filters

    def execute(self, filters: VersementsRetraitsFilters) -> pd.DataFrame:
        return get_versements_retraits(filters)

    def excel_filename(self, filters: VersementsRetraitsFilters) -> str:
        return (
            f"versements_retraits_{filters.date_debut:%Y%m%d}_"
            f"{filters.date_fin:%Y%m%d}.xlsx"
        )

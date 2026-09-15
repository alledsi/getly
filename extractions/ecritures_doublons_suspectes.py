"""
Extraction : Écritures Doublons Suspectes.

Écritures potentiellement dupliquées (même compte / opération / montant
répété plusieurs fois) sur une période donnée (table de reporting
RPT_ECRITURES_DOUBLONS_SUSPECTES, une ligne par groupe d'écritures
suspectes avec son nombre d'occurrences — table d'événements détectés,
pas un instantané à une date d'arrêté, donc filtrée par une PÉRIODE
comme le Journal des écritures et les Nouveaux comptes débiteurs).

Champs obligatoires : date début / date fin (sur D_ECR). Filtres
facultatifs : localisation hiérarchique (Mutuelle -> Agence -> Bureau),
obtenue via CODE_BUREAU -> BUREAU -> REGION -> MUTUELLE (la table ne
porte que le bureau, pas l'agence/mutuelle directement).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import streamlit as st

from db import fetch_df
from extractions.base import Extraction
from extractions.reference_data import referentiel_localisation_cached, render_localisation_cascade

# ---------------------------------------------------------------------------
# Filtres du formulaire
# ---------------------------------------------------------------------------


@dataclass
class EcrituresDoublonsSuspectesFilters:
    date_debut: dt.date
    date_fin: dt.date
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

_BASE_SQL = """
    SELECT
        m.CODE_MUTUELLE          AS CODE_MUTUELLE,
        m.NOM_MUTUELLE           AS NOM_MUTUELLE,
        r.CODE_REGION            AS CODE_AGENCE,
        r.LIB_REGION             AS NOM_AGENCE,
        rpt.CODE_BUREAU          AS CODE_BUREAU,
        b.LIBELLE_BUREAU         AS NOM_BUREAU,
        rpt.NO_ECR               AS NO_ECR,
        rpt.D_ECR                AS DATE_ECRITURE,
        rpt.NO_COMPTE            AS NO_COMPTE,
        rpt.MATRICULE_CLIENT     AS MATRICULE_CLIENT,
        cl.RAISON_SOCIALE_CLIENT AS RAISON_SOCIALE_CLIENT,
        cl.PRENOM_CLIENT         AS PRENOM_CLIENT,
        rpt.CODE_OPER            AS CODE_OPERATION,
        o.LIB_OPER                AS LIBELLE_OPERATION,
        rpt.MT_ECR                AS MONTANT,
        rpt.NB_OCCURRENCES        AS NB_OCCURRENCES
    FROM RPT_ECRITURES_DOUBLONS_SUSPECTES rpt
    LEFT JOIN BUREAU    b   ON b.CODE_BUREAU = rpt.CODE_BUREAU
    LEFT JOIN REGION    r   ON r.CODE_REGION = b.CODE_REGION
    LEFT JOIN MUTUELLE  m   ON m.CODE_MUTUELLE = r.CODE_MUTUELLE
    LEFT JOIN CLIENT    cl  ON cl.MATRICULE_CLIENT = rpt.MATRICULE_CLIENT
    LEFT JOIN OPERATION o   ON o.CODE_OPER = rpt.CODE_OPER
    WHERE rpt.D_ECR >= :date_debut
      AND rpt.D_ECR <  :date_fin_exclusive
"""

_ORDER_SQL = " ORDER BY rpt.D_ECR, rpt.NB_OCCURRENCES DESC, rpt.CODE_BUREAU"

_COLONNES_FINALES = [
    "CODE_MUTUELLE",
    "NOM_MUTUELLE",
    "CODE_AGENCE",
    "NOM_AGENCE",
    "CODE_BUREAU",
    "NOM_BUREAU",
    "NO_ECR",
    "DATE_ECRITURE",
    "NO_COMPTE",
    "MATRICULE_CLIENT",
    "RAISON_SOCIALE_CLIENT",
    "PRENOM_CLIENT",
    "CODE_OPERATION",
    "LIBELLE_OPERATION",
    "MONTANT",
    "NB_OCCURRENCES",
]


def get_ecritures_doublons_suspectes(filters: EcrituresDoublonsSuspectesFilters) -> pd.DataFrame:
    """Construit et exécute la requête des écritures doublons suspectes sur la période choisie."""
    error = filters.validate()
    if error:
        raise ValueError(error)

    sql = _BASE_SQL
    params: dict = {
        "date_debut": dt.datetime.combine(filters.date_debut, dt.time.min),
        "date_fin_exclusive": dt.datetime.combine(
            filters.date_fin + dt.timedelta(days=1), dt.time.min
        ),
    }

    if filters.code_mutuelle:
        sql += " AND m.CODE_MUTUELLE = :code_mutuelle"
        params["code_mutuelle"] = filters.code_mutuelle.strip()

    if filters.code_agence:
        sql += " AND r.CODE_REGION = :code_agence"
        params["code_agence"] = filters.code_agence.strip()

    if filters.code_bureau:
        sql += " AND rpt.CODE_BUREAU = :code_bureau"
        params["code_bureau"] = filters.code_bureau.strip()

    sql += _ORDER_SQL

    df = fetch_df(sql, params)
    if df.empty:
        return pd.DataFrame(columns=_COLONNES_FINALES)
    return df[_COLONNES_FINALES]


# ---------------------------------------------------------------------------
# Formulaire Streamlit
# ---------------------------------------------------------------------------

LIBELLES_COLONNES = {
    "CODE_MUTUELLE": "Code mutuelle",
    "NOM_MUTUELLE": "Mutuelle",
    "CODE_AGENCE": "Code agence",
    "NOM_AGENCE": "Agence",
    "CODE_BUREAU": "Code bureau",
    "NOM_BUREAU": "Bureau",
    "NO_ECR": "N° écriture",
    "DATE_ECRITURE": "Date écriture",
    "NO_COMPTE": "N° compte",
    "MATRICULE_CLIENT": "Matricule client",
    "RAISON_SOCIALE_CLIENT": "Raison sociale",
    "PRENOM_CLIENT": "Prénom client",
    "CODE_OPERATION": "Code opération",
    "LIBELLE_OPERATION": "Libellé opération",
    "MONTANT": "Montant",
    "NB_OCCURRENCES": "Nombre d'occurrences",
}


class EcrituresDoublonsSuspectesExtraction(Extraction):
    id = "ecritures_doublons_suspectes"
    label = "Écritures Doublons Suspectes"
    description = (
        "Écritures potentiellement dupliquées (même compte, opération et montant "
        "répétés) sur une période donnée, avec le nombre d'occurrences."
    )
    icon = "⚠️"

    column_labels = LIBELLES_COLONNES
    montant_cols = {"MONTANT"}
    date_cols = {"DATE_ECRITURE"}
    total_cols = {"MONTANT", "NB_OCCURRENCES"}

    def render_form(self) -> Optional[EcrituresDoublonsSuspectesFilters]:
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
                "Date début *", value=dt.date.today() - dt.timedelta(days=30)
            )
        with col2:
            date_fin = st.date_input("Date fin *", value=dt.date.today())

        with st.expander("Filtres avancés (facultatifs)"):
            st.caption("Localisation (Mutuelle → Agence → Bureau)")
            code_mutuelle, code_agence, code_bureau = render_localisation_cascade(
                ref_localisation_df, key_prefix="eds_"
            )

        submitted = st.button(
            "🔍 Générer la liste des écritures doublons suspectes", width="stretch", type="primary"
        )

        if not submitted:
            return None

        filters = EcrituresDoublonsSuspectesFilters(
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

    def execute(self, filters: EcrituresDoublonsSuspectesFilters) -> pd.DataFrame:
        return get_ecritures_doublons_suspectes(filters)

    def excel_filename(self, filters: EcrituresDoublonsSuspectesFilters) -> str:
        return (
            f"ecritures_doublons_suspectes_"
            f"{filters.date_debut:%Y%m%d}_{filters.date_fin:%Y%m%d}.xlsx"
        )

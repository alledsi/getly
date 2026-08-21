"""
Extraction : Récapitulatif des écritures.

Vue agrégée du journal des écritures : une ligne par type d'opération
(code + libellé), avec le total débit, le total crédit et l'écart
(crédit - débit) sur la période choisie.

Champs obligatoires : date début, date fin. Filtres facultatifs :
matricule client, n° compte, compte général, et localisation
hiérarchique (Mutuelle -> Agence -> Bureau).
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
class RecapitulatifFilters:
    date_debut: dt.date
    date_fin: dt.date
    matricule_client: Optional[str] = None
    no_compte: Optional[str] = None
    compte_general: Optional[str] = None
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
        e.CODE_OPER AS CODE_OPERATION,
        o.LIB_OPER  AS LIBELLE_OPERATION,
        SUM(CASE WHEN e.SENS_ECR = 'D' THEN e.MT_ECR ELSE 0 END) AS DEBIT,
        SUM(CASE WHEN e.SENS_ECR = 'C' THEN e.MT_ECR ELSE 0 END) AS CREDIT,
        SUM(CASE WHEN e.SENS_ECR = 'C' THEN e.MT_ECR ELSE 0 END)
          - SUM(CASE WHEN e.SENS_ECR = 'D' THEN e.MT_ECR ELSE 0 END) AS ECART
    FROM ECRITURE e
    LEFT JOIN OPERATION o  ON o.CODE_OPER = e.CODE_OPER
    LEFT JOIN COMPTE    cpt ON cpt.NO_COMPTE = e.NO_COMPTE
    LEFT JOIN CLIENT    cl  ON cl.MATRICULE_CLIENT = cpt.MATRICULE_CLIENT
    LEFT JOIN BUREAU    b   ON b.CODE_BUREAU = e.CODE_BUREAU
    LEFT JOIN REGION    r   ON r.CODE_REGION = b.CODE_REGION
    LEFT JOIN MUTUELLE  m   ON m.CODE_MUTUELLE = r.CODE_MUTUELLE
    WHERE e.D_ECR >= :date_debut
      AND e.D_ECR <  :date_fin_exclusive
"""

_GROUP_ORDER_SQL = """
    GROUP BY e.CODE_OPER, o.LIB_OPER
    ORDER BY e.CODE_OPER
"""

_COLONNES_FINALES = [
    "CODE_OPERATION",
    "LIBELLE_OPERATION",
    "DEBIT",
    "CREDIT",
    "ECART",
]


def get_recapitulatif(filters: RecapitulatifFilters) -> pd.DataFrame:
    """
    Construit et exécute la requête du récapitulatif des écritures :
    total débit, total crédit et écart, groupés par type d'opération, sur
    la période et les filtres du formulaire.
    """
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

    if filters.matricule_client:
        sql += " AND cl.MATRICULE_CLIENT = :matricule_client"
        params["matricule_client"] = filters.matricule_client.strip()

    if filters.no_compte:
        sql += " AND e.NO_COMPTE = :no_compte"
        params["no_compte"] = filters.no_compte.strip()

    if filters.compte_general:
        sql += " AND cpt.COMPTE_GENERAL = :compte_general"
        params["compte_general"] = filters.compte_general.strip()

    if filters.code_mutuelle:
        sql += " AND m.CODE_MUTUELLE = :code_mutuelle"
        params["code_mutuelle"] = filters.code_mutuelle.strip()

    if filters.code_agence:
        sql += " AND r.CODE_REGION = :code_agence"
        params["code_agence"] = filters.code_agence.strip()

    if filters.code_bureau:
        sql += " AND b.CODE_BUREAU = :code_bureau"
        params["code_bureau"] = filters.code_bureau.strip()

    sql += _GROUP_ORDER_SQL

    df = fetch_df(sql, params)
    if df.empty:
        return pd.DataFrame(columns=_COLONNES_FINALES)
    return df[_COLONNES_FINALES]


# ---------------------------------------------------------------------------
# Formulaire Streamlit
# ---------------------------------------------------------------------------


LIBELLES_COLONNES = {
    "CODE_OPERATION": "Code opération",
    "LIBELLE_OPERATION": "Type d'opération",
    "DEBIT": "Débit",
    "CREDIT": "Crédit",
    "ECART": "Écart (crédit - débit)",
}


class RecapitulatifEcrituresExtraction(Extraction):
    id = "recapitulatif_ecritures"
    label = "Récapitulatif des écritures"
    description = (
        "Total débit, total crédit et écart par type d'opération, sur une "
        "période donnée."
    )
    icon = "🧮"

    column_labels = LIBELLES_COLONNES
    montant_cols = {"DEBIT", "CREDIT", "ECART"}
    date_cols: set[str] = set()
    total_cols = {"DEBIT", "CREDIT", "ECART"}

    def render_form(self) -> Optional[RecapitulatifFilters]:
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
                "depuis la base. Tu peux saisir les codes manuellement dans "
                "les filtres avancés."
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
            st.caption("Identification")
            c1, c2, c3 = st.columns(3)
            with c1:
                matricule_client = st.text_input("Matricule client")
            with c2:
                no_compte = st.text_input("N° compte")
            with c3:
                compte_general = st.text_input("Compte général")

            st.caption("Localisation (Mutuelle → Agence → Bureau)")
            code_mutuelle, code_agence, code_bureau = render_localisation_cascade(
                ref_localisation_df, key_prefix="recap_"
            )

        submitted = st.button("🔍 Générer le récapitulatif", width="stretch", type="primary")

        if not submitted:
            return None

        filters = RecapitulatifFilters(
            date_debut=date_debut,
            date_fin=date_fin,
            matricule_client=matricule_client or None,
            no_compte=no_compte or None,
            compte_general=compte_general or None,
            code_mutuelle=code_mutuelle or None,
            code_agence=code_agence or None,
            code_bureau=code_bureau or None,
        )

        erreur = filters.validate()
        if erreur:
            st.error(erreur)
            return None
        return filters

    def execute(self, filters: RecapitulatifFilters) -> pd.DataFrame:
        return get_recapitulatif(filters)

    def excel_filename(self, filters: RecapitulatifFilters) -> str:
        return (
            f"recapitulatif_ecritures_"
            f"{filters.date_debut:%Y%m%d}_{filters.date_fin:%Y%m%d}.xlsx"
        )

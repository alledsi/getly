"""
Extraction : Nouveaux comptes débiteurs.

Comptes passés en position débitrice sur une période donnée (table de
reporting RPT_NOUVEAUX_COMPTES_DEBITEURS, une ligne par compte et par
date de passage en débiteur — contrairement à RPT_COMPTES_DEBITEURS qui
est un instantané à une date d'arrêté, cette table est un historique
d'événements, donc filtrée par une PÉRIODE plutôt que par une date
d'arrêté unique).

Champs obligatoires : date début / date fin (sur DATE_DEBITEUR). Filtres
facultatifs : localisation hiérarchique (Mutuelle -> Agence -> Bureau).
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
class NouveauxComptesDebiteursFilters:
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
        rpt.CODE_REGION          AS CODE_AGENCE,
        r.LIB_REGION             AS NOM_AGENCE,
        rpt.CODE_BUREAU          AS CODE_BUREAU,
        b.LIBELLE_BUREAU         AS NOM_BUREAU,
        rpt.NO_COMPTE            AS NUMERO_COMPTE,
        rpt.CODE_TYPE_CPT        AS CODE_TYPE_COMPTE,
        rpt.MATRICULE_CLIENT     AS MATRICULE_CLIENT,
        cl.RAISON_SOCIALE_CLIENT AS RAISON_SOCIALE_CLIENT,
        cl.PRENOM_CLIENT         AS PRENOM_CLIENT,
        rpt.SLD_DEBITEUR         AS SLD_DEBITEUR,
        rpt.STATUS_COMPTE        AS STATUS_COMPTE,
        rpt.DATE_DEBITEUR        AS DATE_DEBITEUR
    FROM RPT_NOUVEAUX_COMPTES_DEBITEURS rpt
    LEFT JOIN BUREAU   b   ON b.CODE_BUREAU = rpt.CODE_BUREAU
    LEFT JOIN REGION   r   ON r.CODE_REGION = rpt.CODE_REGION
    LEFT JOIN MUTUELLE m   ON m.CODE_MUTUELLE = r.CODE_MUTUELLE
    LEFT JOIN CLIENT   cl  ON cl.MATRICULE_CLIENT = rpt.MATRICULE_CLIENT
    WHERE rpt.DATE_DEBITEUR >= :date_debut
      AND rpt.DATE_DEBITEUR <  :date_fin_exclusive
"""

_ORDER_SQL = " ORDER BY rpt.DATE_DEBITEUR DESC, rpt.CODE_BUREAU, rpt.NO_COMPTE"

_COLONNES_FINALES = [
    "CODE_MUTUELLE",
    "NOM_MUTUELLE",
    "CODE_AGENCE",
    "NOM_AGENCE",
    "CODE_BUREAU",
    "NOM_BUREAU",
    "NUMERO_COMPTE",
    "CODE_TYPE_COMPTE",
    "MATRICULE_CLIENT",
    "RAISON_SOCIALE_CLIENT",
    "PRENOM_CLIENT",
    "SLD_DEBITEUR",
    "STATUS_COMPTE",
    "DATE_DEBITEUR",
]


def get_nouveaux_comptes_debiteurs(filters: NouveauxComptesDebiteursFilters) -> pd.DataFrame:
    """Construit et exécute la requête des nouveaux comptes débiteurs sur la période choisie."""
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
        sql += " AND rpt.CODE_REGION = :code_agence"
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
    "NUMERO_COMPTE": "N° compte",
    "CODE_TYPE_COMPTE": "Code type compte",
    "MATRICULE_CLIENT": "Matricule client",
    "RAISON_SOCIALE_CLIENT": "Raison sociale",
    "PRENOM_CLIENT": "Prénom client",
    "SLD_DEBITEUR": "Solde débiteur",
    "STATUS_COMPTE": "Statut compte",
    "DATE_DEBITEUR": "Date passage débiteur",
}


class NouveauxComptesDebiteursExtraction(Extraction):
    id = "nouveaux_comptes_debiteurs"
    label = "Nouveaux comptes débiteurs"
    description = (
        "Comptes passés en position débitrice sur une période donnée "
        "(un compte par date de passage en débiteur)."
    )
    icon = "🆕"

    column_labels = LIBELLES_COLONNES
    montant_cols = {"SLD_DEBITEUR"}
    date_cols = {"DATE_DEBITEUR"}
    total_cols = {"SLD_DEBITEUR"}

    def render_form(self) -> Optional[NouveauxComptesDebiteursFilters]:
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
                ref_localisation_df, key_prefix="ncd_"
            )

        submitted = st.button(
            "🔍 Générer la liste des nouveaux comptes débiteurs", width="stretch", type="primary"
        )

        if not submitted:
            return None

        filters = NouveauxComptesDebiteursFilters(
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

    def execute(self, filters: NouveauxComptesDebiteursFilters) -> pd.DataFrame:
        return get_nouveaux_comptes_debiteurs(filters)

    def excel_filename(self, filters: NouveauxComptesDebiteursFilters) -> str:
        return (
            f"nouveaux_comptes_debiteurs_"
            f"{filters.date_debut:%Y%m%d}_{filters.date_fin:%Y%m%d}.xlsx"
        )

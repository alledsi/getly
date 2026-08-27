"""
Extraction : Comptes débiteurs.

Instantané des comptes en position débitrice à une date d'arrêté choisie
(table de reporting RPT_COMPTES_DEBITEURS), avec le solde débiteur, la
date de passage en débiteur, la durée en jours et, le cas échéant, la
date d'apurement.

Champ obligatoire : date d'arrêté (liste déroulante, dernière disponible
par défaut). Filtres facultatifs : matricule client, code type compte,
statut compte, et localisation hiérarchique (Mutuelle -> Agence ->
Bureau).
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
    dates_arrete_comptes_debiteurs_cached,
    referentiel_localisation_cached,
    render_localisation_cascade,
    select_valeur,
)

# ---------------------------------------------------------------------------
# Filtres du formulaire
# ---------------------------------------------------------------------------


@dataclass
class ComptesDebiteursFilters:
    date_arrete: Optional[dt.date]
    matricule_client: Optional[str] = None
    code_type_compte: Optional[str] = None
    status_compte: Optional[str] = None
    code_mutuelle: Optional[str] = None
    code_agence: Optional[str] = None
    code_bureau: Optional[str] = None

    def validate(self) -> Optional[str]:
        if not self.date_arrete:
            return "La date d'arrêté est obligatoire."
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
        rpt.NO_COMPTE            AS NUMERO_COMPTE,
        rpt.CODE_TYPE_CPT        AS CODE_TYPE_COMPTE,
        rpt.MATRICULE_CLIENT     AS MATRICULE_CLIENT,
        cl.RAISON_SOCIALE_CLIENT AS RAISON_SOCIALE_CLIENT,
        cl.PRENOM_CLIENT         AS PRENOM_CLIENT,
        rpt.SLD_DEBITEUR         AS SLD_DEBITEUR,
        rpt.DATE_ARRETE          AS DATE_ARRETE,
        rpt.DATE_DEBITEUR        AS DATE_DEBITEUR,
        rpt.DUREE_JOURS          AS DUREE_JOURS,
        rpt.DATE_APUREMENT       AS DATE_APUREMENT,
        rpt.STATUS_COMPTE        AS STATUS_COMPTE
    FROM RPT_COMPTES_DEBITEURS rpt
    LEFT JOIN BUREAU   b   ON b.CODE_BUREAU = rpt.CODE_BUREAU
    LEFT JOIN REGION   r   ON r.CODE_REGION = rpt.CODE_REGION
    LEFT JOIN MUTUELLE m   ON m.CODE_MUTUELLE = r.CODE_MUTUELLE
    LEFT JOIN CLIENT   cl  ON cl.MATRICULE_CLIENT = rpt.MATRICULE_CLIENT
    WHERE rpt.DATE_ARRETE = :date_arrete
"""

_ORDER_SQL = " ORDER BY rpt.CODE_BUREAU, rpt.NO_COMPTE"

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
    "DATE_ARRETE",
    "DATE_DEBITEUR",
    "DUREE_JOURS",
    "DATE_APUREMENT",
    "STATUS_COMPTE",
]


def get_valeurs_code_type_compte() -> list[str]:
    """Codes type de compte distincts présents dans RPT_COMPTES_DEBITEURS."""
    df = fetch_df(
        "SELECT DISTINCT CODE_TYPE_CPT FROM RPT_COMPTES_DEBITEURS "
        "WHERE CODE_TYPE_CPT IS NOT NULL ORDER BY CODE_TYPE_CPT"
    )
    return df["CODE_TYPE_CPT"].dropna().tolist()


def get_valeurs_status_compte() -> list[str]:
    """Statuts de compte distincts présents dans RPT_COMPTES_DEBITEURS."""
    df = fetch_df(
        "SELECT DISTINCT STATUS_COMPTE FROM RPT_COMPTES_DEBITEURS "
        "WHERE STATUS_COMPTE IS NOT NULL ORDER BY STATUS_COMPTE"
    )
    return df["STATUS_COMPTE"].dropna().tolist()


def get_comptes_debiteurs(filters: ComptesDebiteursFilters) -> pd.DataFrame:
    """Construit et exécute la requête des comptes débiteurs à la date d'arrêté choisie."""
    error = filters.validate()
    if error:
        raise ValueError(error)

    sql = _BASE_SQL
    params: dict = {
        "date_arrete": dt.datetime.combine(filters.date_arrete, dt.time.min),
    }

    if filters.matricule_client:
        sql += " AND rpt.MATRICULE_CLIENT = :matricule_client"
        params["matricule_client"] = filters.matricule_client.strip()

    if filters.code_type_compte:
        sql += " AND rpt.CODE_TYPE_CPT = :code_type_compte"
        params["code_type_compte"] = filters.code_type_compte.strip()

    if filters.status_compte:
        sql += " AND rpt.STATUS_COMPTE = :status_compte"
        params["status_compte"] = filters.status_compte.strip()

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


@st.cache_data(ttl=3600, show_spinner=False)
def _valeurs_code_type_compte_cached() -> list[str]:
    return get_valeurs_code_type_compte()


@st.cache_data(ttl=3600, show_spinner=False)
def _valeurs_status_compte_cached() -> list[str]:
    return get_valeurs_status_compte()


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
    "DATE_ARRETE": "Date arrêté",
    "DATE_DEBITEUR": "Date passage débiteur",
    "DUREE_JOURS": "Durée (jours)",
    "DATE_APUREMENT": "Date apurement",
    "STATUS_COMPTE": "Statut compte",
}


class ComptesDebiteursExtraction(Extraction):
    id = "comptes_debiteurs"
    label = "Comptes débiteurs"
    description = (
        "Comptes en position débitrice à une date d'arrêté donnée, avec la durée "
        "en jours depuis le passage en débiteur et la date d'apurement le cas échéant."
    )
    icon = "🔻"

    column_labels = LIBELLES_COLONNES
    montant_cols = {"SLD_DEBITEUR"}
    date_cols = {"DATE_ARRETE", "DATE_DEBITEUR", "DATE_APUREMENT"}
    total_cols = {"SLD_DEBITEUR"}

    def render_form(self) -> Optional[ComptesDebiteursFilters]:
        # NB : pas de st.form ici — les menus Mutuelle/Agence/Bureau sont en
        # cascade et doivent se recalculer immédiatement quand on change un
        # choix, ce que st.form empêche (il ne rerun qu'à la soumission).

        try:
            dates_dispo = dates_arrete_comptes_debiteurs_cached()
        except Exception:  # noqa: BLE001
            dates_dispo = []
            st.warning(
                "Impossible de charger les dates d'arrêté disponibles "
                "(vérifie que le fichier .env est bien configuré et que le "
                "serveur a accès à la base)."
            )

        try:
            valeurs_code_type_compte = _valeurs_code_type_compte_cached()
        except Exception:  # noqa: BLE001
            valeurs_code_type_compte = []

        try:
            valeurs_status_compte = _valeurs_status_compte_cached()
        except Exception:  # noqa: BLE001
            valeurs_status_compte = []

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

        if dates_dispo:
            date_arrete = st.selectbox(
                "Date d'arrêté *",
                options=dates_dispo,
                index=0,  # la plus récente (liste triée du plus récent au plus ancien)
                format_func=lambda d: d.strftime("%d/%m/%Y"),
            )
        else:
            st.error(
                "Aucune date d'arrêté trouvée. Cette extraction ne peut pas "
                "être calculée pour le moment."
            )
            date_arrete = None

        with st.expander("Filtres avancés (facultatifs)"):
            st.caption("Identification du compte")
            c1, c2, c3 = st.columns(3)
            with c1:
                matricule_client = st.text_input("Matricule client", max_chars=8)
            with c2:
                code_type_compte = select_valeur(
                    "Code type compte", valeurs_code_type_compte, "Tous", "cd_code_type_compte", max_chars=3
                )
            with c3:
                status_compte = select_valeur(
                    "Statut compte", valeurs_status_compte, "Tous", "cd_status_compte", max_chars=1
                )

            st.caption("Localisation (Mutuelle → Agence → Bureau)")
            code_mutuelle, code_agence, code_bureau = render_localisation_cascade(
                ref_localisation_df, key_prefix="comptes_deb_"
            )

        submitted = st.button("🔍 Générer la liste des comptes débiteurs", width="stretch", type="primary")

        if not submitted:
            return None

        filters = ComptesDebiteursFilters(
            date_arrete=date_arrete,
            matricule_client=matricule_client or None,
            code_type_compte=code_type_compte or None,
            status_compte=status_compte or None,
            code_mutuelle=code_mutuelle or None,
            code_agence=code_agence or None,
            code_bureau=code_bureau or None,
        )

        erreur = filters.validate()
        if erreur:
            st.error(erreur)
            return None
        return filters

    def execute(self, filters: ComptesDebiteursFilters) -> pd.DataFrame:
        return get_comptes_debiteurs(filters)

    def excel_filename(self, filters: ComptesDebiteursFilters) -> str:
        return f"comptes_debiteurs_{filters.date_arrete:%Y%m%d}.xlsx"

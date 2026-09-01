"""
Extraction : État des dépôts.

Situation des soldes de dépôts à une date d'arrêté choisie, à partir de
la table de reporting RPT_ETAT_DEPOTS (déjà pré-calculée en base, une
ligne par compte de dépôt et par date d'arrêté).

Champ obligatoire : date d'arrêté (liste déroulante des dates
disponibles, la plus récente par défaut). Filtres facultatifs, en deux
groupes :
  - identification du compte : matricule client, compte général,
    n° compte, code type compte, statut compte, et une case pour exclure
    les comptes à solde nul (débiteur et créditeur tous deux à 0)
  - localisation, hiérarchique (Mutuelle -> Agence -> Bureau), identique
    au Journal des écritures.
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
    dates_arrete_etat_depots_cached,
    referentiel_localisation_cached,
    render_localisation_cascade,
    select_valeur,
)

# ---------------------------------------------------------------------------
# Filtres du formulaire
# ---------------------------------------------------------------------------


@dataclass
class EtatDepotsFilters:
    date_arrete: Optional[dt.date]
    matricule_client: Optional[str] = None
    compte_general: Optional[str] = None
    no_compte: Optional[str] = None
    code_type_compte: Optional[str] = None
    status_compte: Optional[str] = None
    exclure_soldes_nuls: bool = False
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
        d.CODE_MUTUELLE          AS CODE_MUTUELLE,
        mut.NOM_MUTUELLE         AS NOM_MUTUELLE,
        d.CODE_AGENCE            AS CODE_AGENCE,
        r.LIB_REGION             AS NOM_AGENCE,
        d.CODE_BUREAU            AS CODE_BUREAU,
        b.LIBELLE_BUREAU         AS NOM_BUREAU,
        d.COMPTE_GENERAL         AS COMPTE_GENERAL,
        d.NUMERO_COMPTE          AS NUMERO_COMPTE,
        d.CODE_TYPE_COMPTE       AS CODE_TYPE_COMPTE,
        d.MATRICULE_CLIENT       AS MATRICULE_CLIENT,
        d.RAISON_SOCIALE_CLIENT  AS RAISON_SOCIALE_CLIENT,
        d.PRENOM_CLIENT          AS PRENOM_CLIENT,
        d.SLD_DEBITEUR           AS SLD_DEBITEUR,
        d.SLD_CREDITEUR          AS SLD_CREDITEUR,
        d.DATE_ARRETE            AS DATE_ARRETE,
        d.STATUS_COMPTE          AS STATUS_COMPTE
    FROM RPT_ETAT_DEPOTS d
    JOIN BUREAU   b   ON b.CODE_BUREAU = d.CODE_BUREAU
    JOIN REGION   r   ON r.CODE_REGION = d.CODE_AGENCE
    LEFT JOIN MUTUELLE mut ON mut.CODE_MUTUELLE = d.CODE_MUTUELLE
    WHERE d.DATE_ARRETE = :date_arrete
"""

_ORDER_SQL = " ORDER BY d.CODE_AGENCE, d.CODE_BUREAU, d.NUMERO_COMPTE"

_COLONNES_FINALES = [
    "CODE_MUTUELLE",
    "NOM_MUTUELLE",
    "CODE_AGENCE",
    "NOM_AGENCE",
    "CODE_BUREAU",
    "NOM_BUREAU",
    "COMPTE_GENERAL",
    "NUMERO_COMPTE",
    "CODE_TYPE_COMPTE",
    "MATRICULE_CLIENT",
    "RAISON_SOCIALE_CLIENT",
    "PRENOM_CLIENT",
    "SLD_DEBITEUR",
    "SLD_CREDITEUR",
    "DATE_ARRETE",
    "STATUS_COMPTE",
]


def get_valeurs_compte_general() -> list[str]:
    """Comptes généraux distincts présents dans RPT_ETAT_DEPOTS."""
    df = fetch_df("SELECT DISTINCT COMPTE_GENERAL FROM RPT_ETAT_DEPOTS ORDER BY COMPTE_GENERAL")
    return df["COMPTE_GENERAL"].dropna().tolist()


def get_valeurs_code_type_compte() -> list[str]:
    """Codes type de compte distincts présents dans RPT_ETAT_DEPOTS."""
    df = fetch_df(
        "SELECT DISTINCT CODE_TYPE_COMPTE FROM RPT_ETAT_DEPOTS "
        "WHERE CODE_TYPE_COMPTE IS NOT NULL ORDER BY CODE_TYPE_COMPTE"
    )
    return df["CODE_TYPE_COMPTE"].dropna().tolist()


def get_valeurs_status_compte() -> list[str]:
    """Statuts de compte distincts présents dans RPT_ETAT_DEPOTS."""
    df = fetch_df(
        "SELECT DISTINCT STATUS_COMPTE FROM RPT_ETAT_DEPOTS "
        "WHERE STATUS_COMPTE IS NOT NULL ORDER BY STATUS_COMPTE"
    )
    return df["STATUS_COMPTE"].dropna().tolist()


def get_etat_depots(filters: EtatDepotsFilters) -> pd.DataFrame:
    """Construit et exécute la requête de l'état des dépôts à la date d'arrêté choisie."""
    error = filters.validate()
    if error:
        raise ValueError(error)

    sql = _BASE_SQL
    params: dict = {
        "date_arrete": dt.datetime.combine(filters.date_arrete, dt.time.min),
    }

    if filters.matricule_client:
        sql += " AND d.MATRICULE_CLIENT = :matricule_client"
        params["matricule_client"] = filters.matricule_client.strip()

    if filters.compte_general:
        sql += " AND d.COMPTE_GENERAL = :compte_general"
        params["compte_general"] = filters.compte_general.strip()

    if filters.no_compte:
        sql += " AND d.NUMERO_COMPTE = :no_compte"
        params["no_compte"] = filters.no_compte.strip()

    if filters.code_type_compte:
        sql += " AND d.CODE_TYPE_COMPTE = :code_type_compte"
        params["code_type_compte"] = filters.code_type_compte.strip()

    if filters.status_compte:
        sql += " AND d.STATUS_COMPTE = :status_compte"
        params["status_compte"] = filters.status_compte.strip()

    if filters.code_mutuelle:
        sql += " AND d.CODE_MUTUELLE = :code_mutuelle"
        params["code_mutuelle"] = filters.code_mutuelle.strip()

    if filters.code_agence:
        sql += " AND d.CODE_AGENCE = :code_agence"
        params["code_agence"] = filters.code_agence.strip()

    if filters.code_bureau:
        sql += " AND d.CODE_BUREAU = :code_bureau"
        params["code_bureau"] = filters.code_bureau.strip()

    if filters.exclure_soldes_nuls:
        sql += " AND NOT (d.SLD_DEBITEUR = 0 AND d.SLD_CREDITEUR = 0)"

    sql += _ORDER_SQL

    df = fetch_df(sql, params)
    if df.empty:
        return pd.DataFrame(columns=_COLONNES_FINALES)
    return df[_COLONNES_FINALES]


# ---------------------------------------------------------------------------
# Formulaire Streamlit
# ---------------------------------------------------------------------------


@st.cache_data(ttl=3600, show_spinner=False)
def _valeurs_compte_general_cached() -> list[str]:
    return get_valeurs_compte_general()


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
    "COMPTE_GENERAL": "Compte général",
    "NUMERO_COMPTE": "N° compte",
    "CODE_TYPE_COMPTE": "Code type compte",
    "MATRICULE_CLIENT": "Matricule client",
    "RAISON_SOCIALE_CLIENT": "Raison sociale",
    "PRENOM_CLIENT": "Prénom client",
    "SLD_DEBITEUR": "Solde débiteur",
    "SLD_CREDITEUR": "Solde créditeur",
    "DATE_ARRETE": "Date arrêté",
    "STATUS_COMPTE": "Statut compte",
}


class EtatDepotsExtraction(Extraction):
    id = "etat_depots"
    label = "État des dépôts"
    description = "Situation des soldes de dépôts par compte à une date d'arrêté donnée."
    icon = "🏦"

    column_labels = LIBELLES_COLONNES
    montant_cols = {"SLD_DEBITEUR", "SLD_CREDITEUR"}
    date_cols = {"DATE_ARRETE"}
    total_cols = {"SLD_DEBITEUR", "SLD_CREDITEUR"}

    def render_form(self) -> Optional[EtatDepotsFilters]:
        # NB : pas de st.form ici — les menus Mutuelle/Agence/Bureau sont en
        # cascade et doivent se recalculer immédiatement quand on change un
        # choix, ce que st.form empêche (il ne rerun qu'à la soumission).

        try:
            dates_dispo = dates_arrete_etat_depots_cached()
        except Exception:  # noqa: BLE001
            dates_dispo = []
            st.warning(
                "Impossible de charger les dates d'arrêté disponibles "
                "(vérifie que le fichier .env est bien configuré et que le "
                "serveur a accès à la base)."
            )

        try:
            valeurs_compte_general = _valeurs_compte_general_cached()
        except Exception:  # noqa: BLE001
            valeurs_compte_general = []

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
                "depuis la base. Tu peux saisir les codes manuellement dans "
                "les filtres avancés."
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
                compte_general = select_valeur(
                    "Compte général", valeurs_compte_general, "Tous", "compte_general", max_chars=10
                )
            with c2:
                no_compte = st.text_input("N° compte", max_chars=12)
                code_type_compte = select_valeur(
                    "Code type compte", valeurs_code_type_compte, "Tous", "code_type_compte", max_chars=3
                )
            with c3:
                status_compte = select_valeur(
                    "Statut compte", valeurs_status_compte, "Tous", "status_compte", max_chars=1
                )
                exclure_soldes_nuls = st.checkbox("Exclure les comptes à solde nul")

            st.caption("Localisation (Mutuelle → Agence → Bureau)")
            code_mutuelle, code_agence, code_bureau = render_localisation_cascade(
                ref_localisation_df, key_prefix="depots_"
            )

        submitted = st.button("🔍 Générer l'état des dépôts", width="stretch", type="primary")

        if not submitted:
            return None

        filters = EtatDepotsFilters(
            date_arrete=date_arrete,
            matricule_client=matricule_client or None,
            compte_general=compte_general or None,
            no_compte=no_compte or None,
            code_type_compte=code_type_compte or None,
            status_compte=status_compte or None,
            exclure_soldes_nuls=exclure_soldes_nuls,
            code_mutuelle=code_mutuelle or None,
            code_agence=code_agence or None,
            code_bureau=code_bureau or None,
        )

        erreur = filters.validate()
        if erreur:
            st.error(erreur)
            return None
        return filters

    def execute(self, filters: EtatDepotsFilters) -> pd.DataFrame:
        return get_etat_depots(filters)

    def excel_filename(self, filters: EtatDepotsFilters) -> str:
        return f"etat_depots_{filters.date_arrete:%Y%m%d}.xlsx"

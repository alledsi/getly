"""
Extraction : Alertes mails.

Historique des alertes envoyées par mail (table RPT_HIST_MAILS_ALERTES) —
détection de typologies à risque sur des clients (PPE, montants
suspects...), avec l'utilisateur destinataire et la date de réception de
l'alerte.

Aucun filtre obligatoire. Filtres facultatifs : date de réception (début,
fin), utilisateur récepteur, PPE (Oui/Non), et localisation hiérarchique
(Mutuelle -> Agence -> Bureau).
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
    select_valeur,
)

# ---------------------------------------------------------------------------
# Filtres du formulaire
# ---------------------------------------------------------------------------

_PPE_LABELS = {"O": "Oui", "N": "Non"}
_PPE_OPTIONS = ["Oui", "Non"]
_PPE_CODE_PAR_OPTION = {"Oui": "O", "Non": "N"}


@dataclass
class HistMailsAlertesFilters:
    date_reception_debut: Optional[dt.date] = None
    date_reception_fin: Optional[dt.date] = None
    utilisateur_recepteur: Optional[str] = None
    ppe: Optional[str] = None
    code_mutuelle: Optional[str] = None
    code_agence: Optional[str] = None
    code_bureau: Optional[str] = None

    def validate(self) -> Optional[str]:
        if (
            self.date_reception_debut
            and self.date_reception_fin
            and self.date_reception_debut > self.date_reception_fin
        ):
            return "La date de début doit être antérieure ou égale à la date de fin."
        return None


# ---------------------------------------------------------------------------
# Accès aux données
# ---------------------------------------------------------------------------

_BASE_SQL = """
    SELECT
        m.CODE_MUTUELLE            AS CODE_MUTUELLE,
        m.NOM_MUTUELLE             AS NOM_MUTUELLE,
        r.CODE_REGION              AS CODE_AGENCE,
        r.LIB_REGION               AS NOM_AGENCE,
        rpt.CODE_BUREAU            AS CODE_BUREAU,
        b.LIBELLE_BUREAU           AS NOM_BUREAU,
        rpt.NUMERO                 AS NUMERO,
        rpt.DATE_RECEPTION         AS DATE_RECEPTION,
        rpt.UTILISATEUR_RECEPTEUR  AS UTILISATEUR_RECEPTEUR,
        rpt.MATRICULE_CLIENT       AS MATRICULE_CLIENT,
        rpt.NOM_CLIENT             AS NOM_CLIENT,
        rpt.PRENOM_CLIENT          AS PRENOM_CLIENT,
        rpt.PPE                    AS PPE,
        rpt.TYPOLOGIE              AS TYPOLOGIE,
        rpt.MONTANT_CONCERNE       AS MONTANT_CONCERNE,
        rpt.DATE_OPERATION         AS DATE_OPERATION
    FROM RPT_HIST_MAILS_ALERTES rpt
    LEFT JOIN BUREAU   b   ON b.CODE_BUREAU = rpt.CODE_BUREAU
    LEFT JOIN REGION   r   ON r.CODE_REGION = b.CODE_REGION
    LEFT JOIN MUTUELLE m   ON m.CODE_MUTUELLE = r.CODE_MUTUELLE
    WHERE 1 = 1
"""

_ORDER_SQL = " ORDER BY rpt.DATE_RECEPTION DESC, rpt.NUMERO DESC"

_COLONNES_FINALES = [
    "CODE_MUTUELLE",
    "NOM_MUTUELLE",
    "CODE_AGENCE",
    "NOM_AGENCE",
    "CODE_BUREAU",
    "NOM_BUREAU",
    "NUMERO",
    "DATE_RECEPTION",
    "UTILISATEUR_RECEPTEUR",
    "MATRICULE_CLIENT",
    "NOM_CLIENT",
    "PRENOM_CLIENT",
    "PPE",
    "TYPOLOGIE",
    "MONTANT_CONCERNE",
    "DATE_OPERATION",
]


def get_valeurs_utilisateur_recepteur() -> list[str]:
    """Utilisateurs récepteurs distincts présents dans RPT_HIST_MAILS_ALERTES."""
    df = fetch_df(
        "SELECT DISTINCT UTILISATEUR_RECEPTEUR FROM RPT_HIST_MAILS_ALERTES "
        "WHERE UTILISATEUR_RECEPTEUR IS NOT NULL ORDER BY UTILISATEUR_RECEPTEUR"
    )
    return df["UTILISATEUR_RECEPTEUR"].dropna().tolist()


def get_hist_mails_alertes(filters: HistMailsAlertesFilters) -> pd.DataFrame:
    """Construit et exécute la requête des alertes mails selon les filtres du formulaire."""
    error = filters.validate()
    if error:
        raise ValueError(error)

    sql = _BASE_SQL
    params: dict = {}

    if filters.date_reception_debut:
        sql += " AND rpt.DATE_RECEPTION >= :date_reception_debut"
        params["date_reception_debut"] = dt.datetime.combine(
            filters.date_reception_debut, dt.time.min
        )

    if filters.date_reception_fin:
        sql += " AND rpt.DATE_RECEPTION < :date_reception_fin_exclusive"
        params["date_reception_fin_exclusive"] = dt.datetime.combine(
            filters.date_reception_fin + dt.timedelta(days=1), dt.time.min
        )

    if filters.utilisateur_recepteur:
        sql += " AND rpt.UTILISATEUR_RECEPTEUR = :utilisateur_recepteur"
        params["utilisateur_recepteur"] = filters.utilisateur_recepteur.strip()

    if filters.ppe:
        sql += " AND rpt.PPE = :ppe"
        params["ppe"] = filters.ppe.strip()

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

    df = df.copy()
    df["PPE"] = df["PPE"].map(
        lambda v: _PPE_LABELS.get(str(v).strip().upper(), v) if pd.notna(v) else v
    )
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
    "NUMERO": "N°",
    "DATE_RECEPTION": "Date réception",
    "UTILISATEUR_RECEPTEUR": "Utilisateur récepteur",
    "MATRICULE_CLIENT": "Matricule client",
    "NOM_CLIENT": "Nom client",
    "PRENOM_CLIENT": "Prénom client",
    "PPE": "PPE",
    "TYPOLOGIE": "Typologie",
    "MONTANT_CONCERNE": "Montant concerné",
    "DATE_OPERATION": "Date opération",
}


class HistMailsAlertesExtraction(Extraction):
    id = "hist_mails_alertes"
    label = "Alertes mails"
    description = (
        "Historique des alertes mails envoyées (typologie à risque, PPE, montant "
        "concerné), avec l'utilisateur récepteur et la date de réception."
    )
    icon = "📧"

    column_labels = LIBELLES_COLONNES
    montant_cols = {"MONTANT_CONCERNE"}
    date_cols = {"DATE_RECEPTION", "DATE_OPERATION"}
    total_cols = {"MONTANT_CONCERNE"}

    def render_form(self) -> Optional[HistMailsAlertesFilters]:
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

        try:
            valeurs_utilisateur = _valeurs_utilisateur_recepteur_cached()
        except Exception:  # noqa: BLE001
            valeurs_utilisateur = []

        st.subheader("Critères de recherche")
        col1, col2, col3 = st.columns(3)
        with col1:
            date_reception_debut = st.date_input(
                "Date réception (début)", value=None
            )
        with col2:
            date_reception_fin = st.date_input("Date réception (fin)", value=None)
        with col3:
            choix_ppe = st.selectbox(
                "PPE", options=_PPE_OPTIONS, index=None, placeholder="Tous"
            )
            ppe = _PPE_CODE_PAR_OPTION.get(choix_ppe, "")

        with st.expander("Filtres avancés (facultatifs)"):
            st.caption("Localisation (Mutuelle → Agence → Bureau)")
            code_mutuelle, code_agence, code_bureau = render_localisation_cascade(
                ref_localisation_df, key_prefix="hma_"
            )

            st.caption("Autres critères")
            utilisateur_recepteur = select_valeur(
                "Utilisateur récepteur", valeurs_utilisateur, "Tous", "hma_utilisateur_recepteur"
            )

        submitted = st.button("🔍 Générer la liste des alertes mails", width="stretch", type="primary")

        if not submitted:
            return None

        filters = HistMailsAlertesFilters(
            date_reception_debut=date_reception_debut or None,
            date_reception_fin=date_reception_fin or None,
            utilisateur_recepteur=utilisateur_recepteur or None,
            ppe=ppe or None,
            code_mutuelle=code_mutuelle or None,
            code_agence=code_agence or None,
            code_bureau=code_bureau or None,
        )

        erreur = filters.validate()
        if erreur:
            st.error(erreur)
            return None
        return filters

    def execute(self, filters: HistMailsAlertesFilters) -> pd.DataFrame:
        return get_hist_mails_alertes(filters)

    def excel_filename(self, filters: HistMailsAlertesFilters) -> str:
        return f"alertes_mails_{dt.date.today():%Y%m%d}.xlsx"


@st.cache_data(ttl=1800, show_spinner=False)
def _valeurs_utilisateur_recepteur_cached() -> list[str]:
    return get_valeurs_utilisateur_recepteur()

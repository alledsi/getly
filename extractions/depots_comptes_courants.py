"""
Extraction : Liste dépôts courants.

Liste des comptes courants de dépôt à une date d'arrêté choisie (table de
reporting RPT_DEPOTS_COMPTES_COURANTS, un instantané par compte et par
date d'arrêté).

Champ obligatoire : date d'arrêté (liste déroulante des dates
disponibles, la plus récente par défaut). Filtres facultatifs :
localisation hiérarchique (Mutuelle -> Agence -> Bureau).

Les colonnes affichées reproduisent exactement la requête fournie par
l'utilisateur (ne pas en ajouter/retirer) : seule la clause des filtres
change selon ce qui est choisi dans le formulaire.
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
    dates_arrete_depots_comptes_courants_cached,
    referentiel_localisation_cached,
    render_localisation_cascade,
)

# ---------------------------------------------------------------------------
# Filtres du formulaire
# ---------------------------------------------------------------------------


@dataclass
class DepotsComptesCourantsFilters:
    date_arrete: Optional[dt.date]
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
        d.NUMERO_COMPTE       AS NUMERO_COMPTE,
        d.NOM_DEPOSANT        AS NOM_DEPOSANT,
        tc.INT_TYPE_CPT       AS TYPE_COMPTE,
        cat.INT_CATEGORIE     AS TYPE_CLIENT,
        r.LIB_REGION          AS AGENCE,
        b.LIBELLE_BUREAU      AS BUREAU,
        d.DEPOT_INITIAL       AS DEPOT_INITIAL,
        d.ENCOURS_DEPOT       AS ENCOURS_DEPOT,
        d.DATE_MISE_EN_PLACE  AS DATE_MISE_EN_PLACE,
        d.DUREE_JOURS         AS DUREE_JOURS,
        d.TAUX_INTERET        AS TAUX_INTERET,
        d.STATUS_COMPTE       AS STATUS_COMPTE,
        d.DATE_ARRETE         AS DATE_ARRETE
    FROM RPT_DEPOTS_COMPTES_COURANTS d
    JOIN TYPE_COMPTE tc     ON tc.CODE_TYPE_CPT = d.CODE_TYPE_CPT
    JOIN BUREAU b            ON b.CODE_BUREAU = d.CODE_BUREAU
    JOIN REGION r             ON r.CODE_REGION = b.CODE_REGION
    LEFT JOIN MUTUELLE mut    ON mut.CODE_MUTUELLE = r.CODE_MUTUELLE
    LEFT JOIN CLIENT cl       ON cl.MATRICULE_CLIENT = d.MATRICULE_CLIENT
    LEFT JOIN CATEGORIE cat   ON cat.CODE_CATEGORIE = cl.CODE_CATEGORIE
    WHERE d.DATE_ARRETE = :date_arrete
"""

_ORDER_SQL = " ORDER BY r.LIB_REGION, b.LIBELLE_BUREAU, d.NUMERO_COMPTE"

_COLONNES_FINALES = [
    "NUMERO_COMPTE",
    "NOM_DEPOSANT",
    "TYPE_COMPTE",
    "TYPE_CLIENT",
    "AGENCE",
    "BUREAU",
    "DEPOT_INITIAL",
    "ENCOURS_DEPOT",
    "DATE_MISE_EN_PLACE",
    "DUREE_JOURS",
    "TAUX_INTERET",
    "STATUS_COMPTE",
    "DATE_ARRETE",
]


def get_depots_comptes_courants(filters: DepotsComptesCourantsFilters) -> pd.DataFrame:
    """Construit et exécute la requête de la liste des dépôts courants à la date d'arrêté choisie."""
    error = filters.validate()
    if error:
        raise ValueError(error)

    sql = _BASE_SQL
    params: dict = {
        "date_arrete": dt.datetime.combine(filters.date_arrete, dt.time.min),
    }

    if filters.code_mutuelle:
        sql += " AND mut.CODE_MUTUELLE = :code_mutuelle"
        params["code_mutuelle"] = filters.code_mutuelle.strip()

    if filters.code_agence:
        sql += " AND r.CODE_REGION = :code_agence"
        params["code_agence"] = filters.code_agence.strip()

    if filters.code_bureau:
        sql += " AND d.CODE_BUREAU = :code_bureau"
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
    "NUMERO_COMPTE": "N° compte",
    "NOM_DEPOSANT": "Nom déposant",
    "TYPE_COMPTE": "Type de compte",
    "TYPE_CLIENT": "Type de client",
    "AGENCE": "Agence",
    "BUREAU": "Bureau",
    "DEPOT_INITIAL": "Dépôt initial",
    "ENCOURS_DEPOT": "Encours dépôt",
    "DATE_MISE_EN_PLACE": "Date mise en place",
    "DUREE_JOURS": "Durée (jours)",
    "TAUX_INTERET": "Taux d'intérêt",
    "STATUS_COMPTE": "Statut compte",
    "DATE_ARRETE": "Date arrêté",
}


class DepotsComptesCourantsExtraction(Extraction):
    id = "depots_comptes_courants"
    label = "Liste dépôts courants"
    description = "Liste des comptes courants de dépôt à une date d'arrêté donnée."
    icon = "💳"

    column_labels = LIBELLES_COLONNES
    montant_cols = {"DEPOT_INITIAL", "ENCOURS_DEPOT"}
    date_cols = {"DATE_MISE_EN_PLACE", "DATE_ARRETE"}
    total_cols = {"DEPOT_INITIAL", "ENCOURS_DEPOT"}

    def render_form(self) -> Optional[DepotsComptesCourantsFilters]:
        # NB : pas de st.form ici — les menus Mutuelle/Agence/Bureau sont en
        # cascade et doivent se recalculer immédiatement quand on change un
        # choix, ce que st.form empêche (il ne rerun qu'à la soumission).

        try:
            dates_dispo = dates_arrete_depots_comptes_courants_cached()
        except Exception:  # noqa: BLE001
            dates_dispo = []
            st.warning(
                "Impossible de charger les dates d'arrêté disponibles "
                "(vérifie que le fichier .env est bien configuré et que le "
                "serveur a accès à la base)."
            )

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
                "Aucune date d'arrêté trouvée. Cette extraction ne peut "
                "pas être calculée pour le moment."
            )
            date_arrete = None

        with st.expander("Filtres avancés (facultatifs)"):
            st.caption("Localisation (Mutuelle → Agence → Bureau)")
            code_mutuelle, code_agence, code_bureau = render_localisation_cascade(
                ref_localisation_df, key_prefix="dcc_"
            )

        submitted = st.button("🔍 Générer la liste des dépôts courants", width="stretch", type="primary")

        if not submitted:
            return None

        filters = DepotsComptesCourantsFilters(
            date_arrete=date_arrete,
            code_mutuelle=code_mutuelle or None,
            code_agence=code_agence or None,
            code_bureau=code_bureau or None,
        )

        erreur = filters.validate()
        if erreur:
            st.error(erreur)
            return None
        return filters

    def execute(self, filters: DepotsComptesCourantsFilters) -> pd.DataFrame:
        return get_depots_comptes_courants(filters)

    def excel_filename(self, filters: DepotsComptesCourantsFilters) -> str:
        return f"depots_comptes_courants_{filters.date_arrete:%Y%m%d}.xlsx"

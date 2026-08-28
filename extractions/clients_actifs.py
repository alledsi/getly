"""
Extraction : Clients actifs.

Liste des clients actifs (STATUT_CLIENT = 'A') ayant adhéré au plus tard
à la date d'arrêté choisie, avec leur localisation (Mutuelle -> Agence ->
Bureau), leur genre, leur type de client et leur secteur d'activité.

Champ obligatoire : date d'arrêté (un client est retenu s'il a adhéré à
cette date ou avant). Filtres facultatifs : genre, type client, secteur
d'activité, et localisation hiérarchique.
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
    select_code_libelle,
    select_valeur,
)

# ---------------------------------------------------------------------------
# Filtres du formulaire
# ---------------------------------------------------------------------------


@dataclass
class ClientsActifsFilters:
    date_arrete: Optional[dt.date]
    genre: Optional[str] = None
    code_categorie: Optional[str] = None
    code_sect: Optional[str] = None
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
    SELECT DISTINCT
        m.CODE_MUTUELLE           AS CODE_MUTUELLE,
        m.NOM_MUTUELLE            AS NOM_MUTUELLE,
        r.CODE_REGION             AS CODE_AGENCE,
        r.LIB_REGION              AS NOM_AGENCE,
        cl.CODE_BUREAU            AS CODE_BUREAU,
        b.LIBELLE_BUREAU          AS NOM_BUREAU,
        cl.MATRICULE_CLIENT       AS MATRICULE_CLIENT,
        cl.RAISON_SOCIALE_CLIENT  AS RAISON_SOCIALE_CLIENT,
        cl.PRENOM_CLIENT          AS PRENOM_CLIENT,
        cl.SEXE                   AS GENRE,
        cat.INT_CATEGORIE         AS TYPE_CLIENT,
        sec.LIB_SECT              AS SECTEUR,
        cl.NB_MAS                 AS NB_HOMMES,
        cl.NB_FEM                 AS NB_FEMMES,
        cl.DATE_ADHESION_CLIENT   AS DATE_ADHESION
    FROM CLIENT cl
    JOIN BUREAU b            ON b.CODE_BUREAU = cl.CODE_BUREAU
    JOIN REGION r             ON r.CODE_REGION = b.CODE_REGION
    LEFT JOIN MUTUELLE m      ON m.CODE_MUTUELLE = r.CODE_MUTUELLE
    LEFT JOIN CATEGORIE cat   ON cat.CODE_CATEGORIE = cl.CODE_CATEGORIE
    LEFT JOIN SOUS_SECTEUR ss ON ss.CODE_SSECT = cl.CODE_SSECT
    LEFT JOIN SECTEUR sec     ON sec.CODE_SECT = ss.CODE_SECT
    WHERE cl.STATUT_CLIENT = 'A'
      AND cl.DATE_ADHESION_CLIENT <= :date_arrete
"""

_ORDER_SQL = " ORDER BY CODE_AGENCE, CODE_BUREAU, MATRICULE_CLIENT"

_COLONNES_FINALES = [
    "CODE_MUTUELLE",
    "NOM_MUTUELLE",
    "CODE_AGENCE",
    "NOM_AGENCE",
    "CODE_BUREAU",
    "NOM_BUREAU",
    "MATRICULE_CLIENT",
    "RAISON_SOCIALE_CLIENT",
    "PRENOM_CLIENT",
    "GENRE",
    "TYPE_CLIENT",
    "SECTEUR",
    "NB_HOMMES",
    "NB_FEMMES",
    "DATE_ADHESION",
]


def get_valeurs_genre() -> list[str]:
    """Valeurs distinctes de SEXE présentes dans CLIENT."""
    df = fetch_df("SELECT DISTINCT SEXE FROM CLIENT WHERE SEXE IS NOT NULL ORDER BY SEXE")
    return df["SEXE"].dropna().tolist()


def get_categories() -> pd.DataFrame:
    """Types de client (table CATEGORIE), pour le menu déroulant."""
    return fetch_df("SELECT CODE_CATEGORIE, INT_CATEGORIE FROM CATEGORIE ORDER BY INT_CATEGORIE")


def get_secteurs() -> pd.DataFrame:
    """Secteurs d'activité (table SECTEUR), pour le menu déroulant."""
    return fetch_df("SELECT CODE_SECT, LIB_SECT FROM SECTEUR ORDER BY LIB_SECT")


def get_clients_actifs(filters: ClientsActifsFilters) -> pd.DataFrame:
    """Construit et exécute la requête des clients actifs à la date d'arrêté choisie."""
    error = filters.validate()
    if error:
        raise ValueError(error)

    sql = _BASE_SQL
    params: dict = {
        "date_arrete": dt.datetime.combine(filters.date_arrete, dt.time.min),
    }

    if filters.genre:
        sql += " AND cl.SEXE = :genre"
        params["genre"] = filters.genre.strip()

    if filters.code_categorie:
        sql += " AND cl.CODE_CATEGORIE = :code_categorie"
        params["code_categorie"] = filters.code_categorie.strip()

    if filters.code_sect:
        sql += " AND sec.CODE_SECT = :code_sect"
        params["code_sect"] = filters.code_sect.strip()

    if filters.code_mutuelle:
        sql += " AND m.CODE_MUTUELLE = :code_mutuelle"
        params["code_mutuelle"] = filters.code_mutuelle.strip()

    if filters.code_agence:
        sql += " AND r.CODE_REGION = :code_agence"
        params["code_agence"] = filters.code_agence.strip()

    if filters.code_bureau:
        sql += " AND cl.CODE_BUREAU = :code_bureau"
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
def _valeurs_genre_cached() -> list[str]:
    return get_valeurs_genre()


@st.cache_data(ttl=3600, show_spinner=False)
def _categories_cached() -> pd.DataFrame:
    return get_categories()


@st.cache_data(ttl=3600, show_spinner=False)
def _secteurs_cached() -> pd.DataFrame:
    return get_secteurs()


LIBELLES_COLONNES = {
    "CODE_MUTUELLE": "Code mutuelle",
    "NOM_MUTUELLE": "Mutuelle",
    "CODE_AGENCE": "Code agence",
    "NOM_AGENCE": "Agence",
    "CODE_BUREAU": "Code bureau",
    "NOM_BUREAU": "Bureau",
    "MATRICULE_CLIENT": "Matricule client",
    "RAISON_SOCIALE_CLIENT": "Raison sociale",
    "PRENOM_CLIENT": "Prénom client",
    "GENRE": "Genre",
    "TYPE_CLIENT": "Type client",
    "SECTEUR": "Secteur",
    "NB_HOMMES": "Nombre d'hommes",
    "NB_FEMMES": "Nombre de femmes",
    "DATE_ADHESION": "Date adhésion",
}


class ClientsActifsExtraction(Extraction):
    id = "clients_actifs"
    label = "Clients actifs"
    description = (
        "Clients actifs ayant adhéré au plus tard à la date d'arrêté choisie, "
        "avec leur genre, leur type et leur secteur d'activité."
    )
    icon = "👥"

    column_labels = LIBELLES_COLONNES
    montant_cols: set[str] = set()
    date_cols = {"DATE_ADHESION"}
    total_cols: set[str] = set()

    def render_form(self) -> Optional[ClientsActifsFilters]:
        # NB : pas de st.form ici — les menus Mutuelle/Agence/Bureau sont en
        # cascade et doivent se recalculer immédiatement quand on change un
        # choix, ce que st.form empêche (il ne rerun qu'à la soumission).

        try:
            valeurs_genre = _valeurs_genre_cached()
        except Exception:  # noqa: BLE001
            valeurs_genre = []

        try:
            categories_df = _categories_cached()
        except Exception:  # noqa: BLE001
            categories_df = pd.DataFrame(columns=["CODE_CATEGORIE", "INT_CATEGORIE"])

        try:
            secteurs_df = _secteurs_cached()
        except Exception:  # noqa: BLE001
            secteurs_df = pd.DataFrame(columns=["CODE_SECT", "LIB_SECT"])

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
        date_arrete = st.date_input("Date d'arrêté *", value=dt.date.today())
        st.caption(
            "Un client est retenu s'il a adhéré à cette date ou avant, et s'il "
            "est actif."
        )

        with st.expander("Filtres avancés (facultatifs)"):
            c1, c2, c3 = st.columns(3)
            with c1:
                genre = select_valeur("Genre", valeurs_genre, "Tous", "clients_actifs_genre", max_chars=1)
            with c2:
                code_categorie = select_code_libelle(
                    "Type client", categories_df, "CODE_CATEGORIE", "INT_CATEGORIE",
                    "Tous", "clients_actifs_categorie",
                )
            with c3:
                code_sect = select_code_libelle(
                    "Secteur d'activité", secteurs_df, "CODE_SECT", "LIB_SECT",
                    "Tous", "clients_actifs_secteur",
                )

            st.caption("Localisation (Mutuelle → Agence → Bureau)")
            code_mutuelle, code_agence, code_bureau = render_localisation_cascade(
                ref_localisation_df, key_prefix="clients_actifs_"
            )

        submitted = st.button("🔍 Générer la liste des clients actifs", width="stretch", type="primary")

        if not submitted:
            return None

        filters = ClientsActifsFilters(
            date_arrete=date_arrete,
            genre=genre or None,
            code_categorie=code_categorie or None,
            code_sect=code_sect or None,
            code_mutuelle=code_mutuelle or None,
            code_agence=code_agence or None,
            code_bureau=code_bureau or None,
        )

        erreur = filters.validate()
        if erreur:
            st.error(erreur)
            return None
        return filters

    def execute(self, filters: ClientsActifsFilters) -> pd.DataFrame:
        return get_clients_actifs(filters)

    def excel_filename(self, filters: ClientsActifsFilters) -> str:
        return f"clients_actifs_{filters.date_arrete:%Y%m%d}.xlsx"

"""
Accès aux données pour les tableaux de bord de pilotage (RPT_RENTABILITE,
RPT_ENCOURS).

Ces deux tables sont alimentées mensuellement par des scripts SQL générés
à partir de la balance consolidée (voir la compétence "acep-balance-
mensuelle-rpt-rentabilite") : une ligne par compte général et par date
d'arrêté dans RPT_RENTABILITE (avec la rubrique et le solde déjà signé
correctement selon la classe du compte), une ligne par catégorie et date
d'arrêté dans RPT_ENCOURS.

Ce module ne fait que lire ces deux tables (jamais les tables brutes du
core banking) et les agréger par rubrique / catégorie / date d'arrêté —
les tableaux de bord n'ont donc besoin d'aucun accès aux tables
comptables détaillées.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from db import fetch_df

# ---------------------------------------------------------------------------
# Rubriques : noms exacts tels que chargés dans RPT_RENTABILITE.RUBRIQUE
# (voir la compétence de chargement mensuel — ne pas modifier sans mettre à
# jour les scripts d'insertion en même temps).
# ---------------------------------------------------------------------------

RUB_FRAIS_DOSSIER = "Frais de dossier"
RUB_INTERET = "Intérêts payés"
RUB_INTERET_PENALITE = "Intérêts sur pénalités payés"
RUB_FRAIS_PENALITE = "Frais de pénalité payés"
RUB_DROIT_ADHESION = "Droit d'adhésion"
RUB_REPRISES_PROVISIONS = "Reprises de provisions"
RUB_RECUPERATION_PERTES = "Récupération pertes et créances amorties"
RUB_PRODUITS_MP = "Produits moyens de paiement"
RUB_PRODUITS_PSF = "Produits prestations services financiers"
RUB_AUTRES_PRODUITS = "Autres produits"
RUB_CHARGES_GROUPE_RETROCEDE = "Charges de groupe rétrocédé"

RUB_FRAIS_PERSONNEL = "Frais de personnel"
RUB_PROVISIONS = "Provisions"
RUB_AMORTISSEMENTS = "Amortissements"
RUB_PERTES = "Pertes"
RUB_LOYERS_CH_LOC = "Loyers et charges locatives"
RUB_IMPOTS_TAXES = "Impôts et taxes"
RUB_CHARGES_FINANCIERES = "Charges financières"
RUB_AUTRES_CHARGES = "Autres charges"
RUB_CHARGES_INT_EPARGNE = "Charges intérêts épargne"
RUB_CHARGES_GROUPE_IMPUTE = "Charges de groupe imputé"

CATEGORIE_CONSOLIDE = "Consolidé"


# ---------------------------------------------------------------------------
# Listes pour les filtres
# ---------------------------------------------------------------------------


def get_categories() -> list[str]:
    """Catégories disponibles (Consolidé + mutuelles éventuelles), Consolidé en tête."""
    df = fetch_df("SELECT DISTINCT CATEGORIE FROM RPT_RENTABILITE ORDER BY CATEGORIE")
    cats = df["CATEGORIE"].dropna().tolist() if not df.empty else []
    if CATEGORIE_CONSOLIDE in cats:
        cats.remove(CATEGORIE_CONSOLIDE)
        cats = [CATEGORIE_CONSOLIDE] + cats
    return cats


@st.cache_data(ttl=600, show_spinner=False)
def categories_cached() -> list[str]:
    return get_categories()


def get_dates_arrete() -> list[dt.date]:
    """Dates d'arrêté disponibles dans RPT_RENTABILITE, la plus récente en premier."""
    df = fetch_df("SELECT DISTINCT DATE_ARRETE FROM RPT_RENTABILITE ORDER BY DATE_ARRETE DESC")
    if df.empty:
        return []
    valeurs = df.iloc[:, 0].tolist()
    return [v.date() if isinstance(v, dt.datetime) else v for v in valeurs]


@st.cache_data(ttl=600, show_spinner=False)
def dates_arrete_cached() -> list[dt.date]:
    return get_dates_arrete()


# ---------------------------------------------------------------------------
# Agrégats pour une catégorie + date d'arrêté données
# ---------------------------------------------------------------------------


def get_rubrique_totals(categorie: str, date_arrete: dt.date) -> dict[str, float]:
    """Solde total (somme des comptes) par rubrique, pour une catégorie et une
    date d'arrêté données. Rubrique absente du résultat = aucun compte
    trouvé -> à traiter comme 0 par l'appelant."""
    sql = """
        SELECT RUBRIQUE, SUM(SOLDE) AS TOTAL
        FROM RPT_RENTABILITE
        WHERE CATEGORIE = :categorie AND DATE_ARRETE = :date_arrete
        GROUP BY RUBRIQUE
    """
    df = fetch_df(
        sql,
        {
            "categorie": categorie,
            "date_arrete": dt.datetime.combine(date_arrete, dt.time.min),
        },
    )
    if df.empty:
        return {}
    return dict(zip(df["RUBRIQUE"], df["TOTAL"].astype(float)))


@st.cache_data(ttl=300, show_spinner=False)
def rubrique_totals_cached(categorie: str, date_arrete: dt.date) -> dict[str, float]:
    return get_rubrique_totals(categorie, date_arrete)


def get_encours(categorie: str, date_arrete: dt.date) -> float | None:
    """Montant d'encours pour une catégorie et une date d'arrêté. None si absent."""
    sql = "SELECT MONTANT FROM RPT_ENCOURS WHERE CATEGORIE = :categorie AND DATE_ARRETE = :date_arrete"
    df = fetch_df(
        sql,
        {
            "categorie": categorie,
            "date_arrete": dt.datetime.combine(date_arrete, dt.time.min),
        },
    )
    if df.empty:
        return None
    return float(df.iloc[0]["MONTANT"])


@st.cache_data(ttl=300, show_spinner=False)
def encours_cached(categorie: str, date_arrete: dt.date) -> float | None:
    return get_encours(categorie, date_arrete)


# ---------------------------------------------------------------------------
# Répartitions "par mutuelle" (toutes les catégories hors Consolidé), pour
# les visuels affichés quand la catégorie sélectionnée est "Consolidé"
# ---------------------------------------------------------------------------


def get_rubrique_totals_par_categorie(date_arrete: dt.date) -> pd.DataFrame:
    """Solde total par catégorie (hors Consolidé) et rubrique, à une date
    d'arrêté donnée. Colonnes : CATEGORIE, RUBRIQUE, TOTAL."""
    sql = """
        SELECT CATEGORIE, RUBRIQUE, SUM(SOLDE) AS TOTAL
        FROM RPT_RENTABILITE
        WHERE DATE_ARRETE = :date_arrete AND CATEGORIE <> :consolide
        GROUP BY CATEGORIE, RUBRIQUE
    """
    return fetch_df(
        sql,
        {
            "date_arrete": dt.datetime.combine(date_arrete, dt.time.min),
            "consolide": CATEGORIE_CONSOLIDE,
        },
    )


@st.cache_data(ttl=300, show_spinner=False)
def rubrique_totals_par_categorie_cached(date_arrete: dt.date) -> pd.DataFrame:
    return get_rubrique_totals_par_categorie(date_arrete)


def get_encours_par_categorie(date_arrete: dt.date) -> pd.DataFrame:
    """Encours par catégorie (hors Consolidé), à une date d'arrêté donnée.
    Colonnes : CATEGORIE, MONTANT."""
    sql = """
        SELECT CATEGORIE, MONTANT
        FROM RPT_ENCOURS
        WHERE DATE_ARRETE = :date_arrete AND CATEGORIE <> :consolide
    """
    return fetch_df(
        sql,
        {
            "date_arrete": dt.datetime.combine(date_arrete, dt.time.min),
            "consolide": CATEGORIE_CONSOLIDE,
        },
    )


@st.cache_data(ttl=300, show_spinner=False)
def encours_par_categorie_cached(date_arrete: dt.date) -> pd.DataFrame:
    return get_encours_par_categorie(date_arrete)

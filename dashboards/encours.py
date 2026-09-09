"""
Tableau de bord : Encours.

Contrairement aux autres tableaux de bord (photo à une date d'arrêté
unique), celui-ci trace l'évolution mensuelle de l'encours sur une année.
Il réutilise le filtre "catégorie" commun à tous les tableaux de bord,
mais remplace le filtre "date d'arrêté" par son propre filtre "année"
(dashboards.base.Dashboard.filtre_date_arrete = False pour ce tableau de
bord — voir dashboards/__init__.py). `date_arrete` reste reçu par
`render` pour respecter la signature commune, mais sert seulement à
présélectionner l'année par défaut.
"""

from __future__ import annotations

import datetime as dt

import streamlit as st

from dashboards import components as c
from dashboards import data


def render(categorie: str, date_arrete: dt.date) -> None:
    c.inject_css()

    annees = data.annees_encours_cached()
    if not annees:
        c.empty_note("Aucun encours chargé pour le moment dans RPT_ENCOURS.")
        return

    annee_defaut = date_arrete.year if date_arrete.year in annees else annees[0]
    annee_choisie = st.selectbox(
        "Année *",
        options=annees,
        index=annees.index(annee_defaut),
    )

    df = data.encours_mensuel_cached(categorie, annee_choisie)
    if df.empty:
        c.empty_note(f"Aucun encours chargé pour « {categorie} » sur {annee_choisie}.")
        return

    dernier = df.iloc[-1]
    dernier_montant = float(dernier["MONTANT"])
    dernier_date = dernier["DATE_ARRETE"]
    if isinstance(dernier_date, dt.datetime):
        dernier_date = dernier_date.date()

    c.hero_metric(
        "Encours",
        c.fmt_montant(dernier_montant),
        sub=f"{categorie} · {dernier_date:%m/%Y}",
    )

    st.write("")
    c.section_title(f"Évolution mensuelle — {annee_choisie}")
    fig = c.line_evolution_mensuelle(df, "DATE_ARRETE", "MONTANT")
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

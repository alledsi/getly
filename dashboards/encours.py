"""
Tableau de bord : Encours.

Contrairement aux autres tableaux de bord (photo à une date d'arrêté
unique), celui-ci trace l'évolution mensuelle de l'encours sur une année.
Il réutilise le filtre "catégorie" commun à tous les tableaux de bord,
mais remplace le filtre "date d'arrêté" par un filtre "année"
(dashboards.base.Dashboard.filtre_date_arrete = False pour ce tableau de
bord — voir dashboards/__init__.py). Les deux filtres (catégorie, année)
sont rendus côte à côte par app.py ; l'année choisie transite via
`date_arrete` (son `.year`) plutôt que par un widget propre à ce module,
pour rester aligné avec le filtre catégorie dans la même ligne.
"""

from __future__ import annotations

import datetime as dt

import streamlit as st

from dashboards import components as c
from dashboards import data


def render(categorie: str, date_arrete: dt.date) -> None:
    c.inject_css()

    annee_choisie = date_arrete.year

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
    fig = c.bar_evolution_mensuelle(df, "DATE_ARRETE", "MONTANT")
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

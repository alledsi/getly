"""
Tableau de bord : Situation des adhésions.

Affiche simplement le montant des droits d'adhésion, à une date d'arrêté
et pour une catégorie (mutuelle ou Consolidé) données.
"""

from __future__ import annotations

import datetime as dt

import streamlit as st

from dashboards import components as c
from dashboards import data


def render(categorie: str, date_arrete: dt.date) -> None:
    c.inject_css()

    totals = data.rubrique_totals_cached(categorie, date_arrete)
    montant = totals.get(data.RUB_DROIT_ADHESION, 0.0)

    c.hero_metric(
        "Droits d'adhésion",
        c.fmt_montant(montant),
        sub=f"{categorie} · {date_arrete:%d/%m/%Y}",
    )

    if categorie == data.CATEGORIE_CONSOLIDE:
        c.section_title("Droits d'adhésion par mutuelle")
        _render_par_mutuelle(date_arrete)


def _render_par_mutuelle(date_arrete: dt.date) -> None:
    df_rub = data.rubrique_totals_par_categorie_cached(date_arrete)
    if df_rub.empty:
        c.empty_note(
            "Aucune donnée par mutuelle chargée pour cette date d'arrêté pour l'instant."
        )
        return

    d = df_rub[df_rub["RUBRIQUE"] == data.RUB_DROIT_ADHESION]
    if d.empty:
        c.empty_note("Aucune mutuelle avec un droit d'adhésion renseigné à cette date.")
        return

    fig = c.bar_classement(d, "CATEGORIE", "TOTAL")
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

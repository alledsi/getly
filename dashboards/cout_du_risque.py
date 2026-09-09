"""
Tableau de bord : Coût du risque.

Coût du risque = (Provisions + Pertes - Reprises de provisions -
Récupération pertes) / Encours, à une date d'arrêté et pour une catégorie
(mutuelle ou Consolidé) données.
"""

from __future__ import annotations

import datetime as dt

import streamlit as st

from dashboards import components as c
from dashboards import data


def _cout_du_risque(categorie: str, date_arrete: dt.date) -> tuple[float | None, dict]:
    totals = data.rubrique_totals_cached(categorie, date_arrete)
    provisions = totals.get(data.RUB_PROVISIONS, 0.0)
    pertes = totals.get(data.RUB_PERTES, 0.0)
    reprises_provisions = totals.get(data.RUB_REPRISES_PROVISIONS, 0.0)
    recuperation_pertes = totals.get(data.RUB_RECUPERATION_PERTES, 0.0)
    encours = data.encours_cached(categorie, date_arrete)

    numerateur = provisions + pertes - reprises_provisions - recuperation_pertes
    cout = (numerateur / encours) if encours else None

    detail = {
        "provisions": provisions,
        "pertes": pertes,
        "reprises_provisions": reprises_provisions,
        "recuperation_pertes": recuperation_pertes,
        "encours": encours,
    }
    return cout, detail


def render(categorie: str, date_arrete: dt.date) -> None:
    c.inject_css()

    cout, d = _cout_du_risque(categorie, date_arrete)

    col1, col2 = st.columns([1, 2])
    with col1:
        negatif = cout is not None and cout > 0  # un coût du risque > 0 dégrade le résultat
        c.hero_metric(
            "Coût du risque",
            c.fmt_pct(cout) if cout is not None else "—",
            sub=f"{categorie} · {date_arrete:%d/%m/%Y}",
            negative=negatif,
        )
    with col2:
        if cout is None:
            c.empty_note(
                "Encours indisponible pour cette catégorie et cette date d'arrêté "
                "— impossible de calculer le coût du risque."
            )

    st.write("")
    c.kpi_row(
        [
            ("Provisions", c.fmt_montant(d["provisions"])),
            ("Pertes", c.fmt_montant(d["pertes"])),
            ("Reprises de provisions", c.fmt_montant(d["reprises_provisions"])),
            ("Récupération pertes", c.fmt_montant(d["recuperation_pertes"])),
            ("Encours", c.fmt_montant(d["encours"])),
        ]
    )

    if categorie == data.CATEGORIE_CONSOLIDE:
        c.section_title("Coût du risque par mutuelle")
        _render_par_mutuelle(date_arrete)


def _render_par_mutuelle(date_arrete: dt.date) -> None:
    df_rub = data.rubrique_totals_par_categorie_cached(date_arrete)
    df_enc = data.encours_par_categorie_cached(date_arrete)

    if df_rub.empty or df_enc.empty:
        c.empty_note(
            "Aucune donnée par mutuelle chargée pour cette date d'arrêté pour l'instant."
        )
        return

    pivot = df_rub.pivot_table(index="CATEGORIE", columns="RUBRIQUE", values="TOTAL", aggfunc="sum").fillna(0.0)
    for rub in (data.RUB_PROVISIONS, data.RUB_PERTES, data.RUB_REPRISES_PROVISIONS, data.RUB_RECUPERATION_PERTES):
        if rub not in pivot.columns:
            pivot[rub] = 0.0

    numerateur = (
        pivot[data.RUB_PROVISIONS]
        + pivot[data.RUB_PERTES]
        - pivot[data.RUB_REPRISES_PROVISIONS]
        - pivot[data.RUB_RECUPERATION_PERTES]
    ).rename("NUMERATEUR")

    enc = df_enc.set_index("CATEGORIE")["MONTANT"].rename("ENCOURS")

    merged = numerateur.to_frame().join(enc, how="inner")
    merged = merged[merged["ENCOURS"] != 0]
    if merged.empty:
        c.empty_note("Aucune mutuelle avec un encours renseigné à cette date.")
        return

    merged["COUT_RISQUE"] = merged["NUMERATEUR"] / merged["ENCOURS"]
    merged = merged.reset_index()

    fig = c.bar_classement(merged, "CATEGORIE", "COUT_RISQUE", value_fmt=c.fmt_pct, color=c.RED)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

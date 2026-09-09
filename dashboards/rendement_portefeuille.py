"""
Tableau de bord : Rendement du portefeuille.

Rendement = (Frais de dossier + Intérêts + Intérêts pénalité + Frais de
pénalité) / Encours, à une date d'arrêté et pour une catégorie (mutuelle
ou Consolidé) données.
"""

from __future__ import annotations

import datetime as dt

import streamlit as st

from dashboards import components as c
from dashboards import data


def _rendement(categorie: str, date_arrete: dt.date) -> tuple[float | None, dict]:
    totals = data.rubrique_totals_cached(categorie, date_arrete)
    frais_dossier = totals.get(data.RUB_FRAIS_DOSSIER, 0.0)
    interet = totals.get(data.RUB_INTERET, 0.0)
    interet_penalite = totals.get(data.RUB_INTERET_PENALITE, 0.0)
    frais_penalite = totals.get(data.RUB_FRAIS_PENALITE, 0.0)
    encours = data.encours_cached(categorie, date_arrete)

    numerateur = frais_dossier + interet + interet_penalite + frais_penalite
    rendement = (numerateur / encours) if encours else None

    detail = {
        "frais_dossier": frais_dossier,
        "interet": interet,
        "interet_penalite": interet_penalite,
        "frais_penalite": frais_penalite,
        "encours": encours,
    }
    return rendement, detail


def render(categorie: str, date_arrete: dt.date) -> None:
    c.inject_css()

    rendement, d = _rendement(categorie, date_arrete)

    col1, col2 = st.columns([1, 2])
    with col1:
        c.hero_metric(
            "Rendement du portefeuille",
            c.fmt_pct(rendement) if rendement is not None else "—",
            sub=f"{categorie} · {date_arrete:%d/%m/%Y}",
        )
    with col2:
        if rendement is None:
            c.empty_note(
                "Encours indisponible pour cette catégorie et cette date d'arrêté "
                "— impossible de calculer le rendement."
            )

    st.write("")
    c.kpi_row(
        [
            ("Frais de dossier", c.fmt_montant(d["frais_dossier"])),
            ("Intérêts", c.fmt_montant(d["interet"])),
            ("Intérêts pénalité", c.fmt_montant(d["interet_penalite"])),
            ("Frais de pénalité", c.fmt_montant(d["frais_penalite"])),
            ("Encours", c.fmt_montant(d["encours"])),
        ]
    )

    if categorie == data.CATEGORIE_CONSOLIDE:
        c.section_title("Rendement par mutuelle")
        _render_par_mutuelle(date_arrete)


def _render_par_mutuelle(date_arrete: dt.date) -> None:
    df_rub = data.rubrique_totals_par_categorie_cached(date_arrete)
    df_enc = data.encours_par_categorie_cached(date_arrete)

    if df_rub.empty or df_enc.empty:
        c.empty_note(
            "Aucune donnée par mutuelle chargée pour cette date d'arrêté pour l'instant."
        )
        return

    rubs = [data.RUB_FRAIS_DOSSIER, data.RUB_INTERET, data.RUB_INTERET_PENALITE, data.RUB_FRAIS_PENALITE]
    num = (
        df_rub[df_rub["RUBRIQUE"].isin(rubs)]
        .groupby("CATEGORIE")["TOTAL"]
        .sum()
        .rename("NUMERATEUR")
    )
    enc = df_enc.set_index("CATEGORIE")["MONTANT"].rename("ENCOURS")

    merged = num.to_frame().join(enc, how="inner")
    merged = merged[merged["ENCOURS"] != 0]
    if merged.empty:
        c.empty_note("Aucune mutuelle avec un encours renseigné à cette date.")
        return

    merged["RENDEMENT"] = merged["NUMERATEUR"] / merged["ENCOURS"]
    merged = merged.reset_index()

    fig = c.bar_classement(merged, "CATEGORIE", "RENDEMENT", value_fmt=c.fmt_pct)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

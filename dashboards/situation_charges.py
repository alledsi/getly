"""
Tableau de bord : Situation des charges.

Total des charges = Frais de personnel + Provisions + Amortissements +
Pertes + Loyers et charges locatives + Impôts et taxes + Charges
financières + Autres charges + Charges intérêts épargne.

Quand la catégorie sélectionnée est une mutuelle (pas Consolidé), les
Charges de groupe imputé s'ajoutent au total et apparaissent en KPI à part.
"""

from __future__ import annotations

import datetime as dt

import streamlit as st

from dashboards import components as c
from dashboards import data

_TYPES_CHARGE = [
    "Frais de personnel",
    "Provisions",
    "Amortissements",
    "Pertes",
    "Loyers et charges locatives",
    "Impôts et taxes",
    "Charges financières",
    "Autres charges",
    "Charges intérêts épargne",
]

_RUBRIQUES_CHARGE = [
    data.RUB_FRAIS_PERSONNEL,
    data.RUB_PROVISIONS,
    data.RUB_AMORTISSEMENTS,
    data.RUB_PERTES,
    data.RUB_LOYERS_CH_LOC,
    data.RUB_IMPOTS_TAXES,
    data.RUB_CHARGES_FINANCIERES,
    data.RUB_AUTRES_CHARGES,
    data.RUB_CHARGES_INT_EPARGNE,
]


def _detail(categorie: str, date_arrete: dt.date) -> dict:
    totals = data.rubrique_totals_cached(categorie, date_arrete)

    valeurs = {rub: totals.get(rub, 0.0) for rub in _RUBRIQUES_CHARGE}
    charges_groupe_impute = totals.get(data.RUB_CHARGES_GROUPE_IMPUTE, 0.0)

    total = sum(valeurs.values())
    est_mutuelle = categorie != data.CATEGORIE_CONSOLIDE
    if est_mutuelle:
        total += charges_groupe_impute

    return {
        "valeurs": valeurs,
        "charges_groupe_impute": charges_groupe_impute,
        "total": total,
        "est_mutuelle": est_mutuelle,
    }


def render(categorie: str, date_arrete: dt.date) -> None:
    c.inject_css()

    d = _detail(categorie, date_arrete)

    c.hero_metric(
        "Total des charges",
        c.fmt_montant(d["total"]),
        sub=f"{categorie} · {date_arrete:%d/%m/%Y}",
        negative=True,
    )

    st.write("")
    kpis = [(label, c.fmt_montant(d["valeurs"][rub])) for label, rub in zip(_TYPES_CHARGE, _RUBRIQUES_CHARGE)]
    if d["est_mutuelle"]:
        kpis.append(("Charges de groupe imputé", c.fmt_montant(d["charges_groupe_impute"])))

    for i in range(0, len(kpis), 4):
        c.kpi_row(kpis[i : i + 4])

    c.section_title("Répartition des charges par type")
    labels = list(_TYPES_CHARGE)
    values = [d["valeurs"][rub] for rub in _RUBRIQUES_CHARGE]
    if d["est_mutuelle"]:
        labels.append("Charges de groupe imputé")
        values.append(d["charges_groupe_impute"])

    fig = c.bar_repartition(labels, values)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    if categorie == data.CATEGORIE_CONSOLIDE:
        c.section_title("Charges par mutuelle")
        _render_par_mutuelle(date_arrete)


def _render_par_mutuelle(date_arrete: dt.date) -> None:
    df_rub = data.rubrique_totals_par_categorie_cached(date_arrete)
    if df_rub.empty:
        c.empty_note(
            "Aucune donnée par mutuelle chargée pour cette date d'arrêté pour l'instant."
        )
        return

    rubs = _RUBRIQUES_CHARGE + [data.RUB_CHARGES_GROUPE_IMPUTE]
    par_mut = (
        df_rub[df_rub["RUBRIQUE"].isin(rubs)]
        .groupby("CATEGORIE")["TOTAL"]
        .sum()
        .reset_index()
        .rename(columns={"TOTAL": "CHARGES_TOTAL"})
    )
    if par_mut.empty:
        c.empty_note("Aucune mutuelle avec des charges renseignées à cette date.")
        return

    fig = c.bar_classement(par_mut, "CATEGORIE", "CHARGES_TOTAL", color=c.RED)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

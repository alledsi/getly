"""
Tableau de bord : Résultat.

Résultat = Total des revenus - Total des charges (mêmes définitions que
les tableaux de bord "Situation des revenus" et "Situation des charges",
Charges de groupe rétrocédé/imputé inclus dès qu'une mutuelle précise est
sélectionnée).
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from dashboards import components as c
from dashboards import data
from dashboards.situation_charges import _RUBRIQUES_CHARGE
from dashboards.situation_charges import _detail as _detail_charges
from dashboards.situation_revenus import _detail as _detail_revenus

_RUBRIQUES_REVENU = [
    data.RUB_FRAIS_DOSSIER,
    data.RUB_INTERET,
    data.RUB_INTERET_PENALITE,
    data.RUB_FRAIS_PENALITE,
    data.RUB_DROIT_ADHESION,
    data.RUB_REPRISES_PROVISIONS,
    data.RUB_RECUPERATION_PERTES,
    data.RUB_PRODUITS_MP,
    data.RUB_PRODUITS_PSF,
    data.RUB_AUTRES_PRODUITS,
]


def render(categorie: str, date_arrete: dt.date) -> None:
    c.inject_css()

    rev = _detail_revenus(categorie, date_arrete)
    chg = _detail_charges(categorie, date_arrete)
    resultat = rev["total"] - chg["total"]

    c.hero_metric(
        "Résultat",
        c.fmt_montant(resultat),
        sub=f"{categorie} · {date_arrete:%d/%m/%Y}",
        negative=resultat < 0,
    )

    st.write("")
    kpis = [
        ("Total des revenus", c.fmt_montant(rev["total"])),
        ("Total des charges", c.fmt_montant(chg["total"])),
    ]
    if rev["est_mutuelle"]:
        kpis.append(("Charges de groupe rétrocédé", c.fmt_montant(rev["charges_groupe_retrocede"])))
    if chg["est_mutuelle"]:
        kpis.append(("Charges de groupe imputé", c.fmt_montant(chg["charges_groupe_impute"])))
    c.kpi_row(kpis)

    if categorie == data.CATEGORIE_CONSOLIDE:
        c.section_title("Résultat par mutuelle")
        par_mut = _par_mutuelle(date_arrete)
        if par_mut.empty:
            c.empty_note(
                "Aucune donnée par mutuelle chargée pour cette date d'arrêté pour l'instant."
            )
        else:
            fig = c.bar_classement_signe(par_mut, "CATEGORIE", "RESULTAT")
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

            c.section_title("Produits et charges par mutuelle")
            fig2 = c.bar_produits_charges(
                par_mut.rename(columns={"REVENU_TOTAL": "PRODUITS", "CHARGES_TOTAL": "CHARGES"}),
                "CATEGORIE",
            )
            st.plotly_chart(fig2, width="stretch", config={"displayModeBar": False})


def _par_mutuelle(date_arrete: dt.date) -> pd.DataFrame:
    df_rub = data.rubrique_totals_par_categorie_cached(date_arrete)
    if df_rub.empty:
        return pd.DataFrame(columns=["CATEGORIE", "REVENU_TOTAL", "CHARGES_TOTAL", "RESULTAT"])

    rubs_revenu = _RUBRIQUES_REVENU + [data.RUB_CHARGES_GROUPE_RETROCEDE]
    rubs_charge = list(_RUBRIQUES_CHARGE) + [data.RUB_CHARGES_GROUPE_IMPUTE]

    revenu = (
        df_rub[df_rub["RUBRIQUE"].isin(rubs_revenu)]
        .groupby("CATEGORIE")["TOTAL"]
        .sum()
        .rename("REVENU_TOTAL")
    )
    charges = (
        df_rub[df_rub["RUBRIQUE"].isin(rubs_charge)]
        .groupby("CATEGORIE")["TOTAL"]
        .sum()
        .rename("CHARGES_TOTAL")
    )

    merged = revenu.to_frame().join(charges, how="outer").fillna(0.0)
    merged["RESULTAT"] = merged["REVENU_TOTAL"] - merged["CHARGES_TOTAL"]
    return merged.reset_index()

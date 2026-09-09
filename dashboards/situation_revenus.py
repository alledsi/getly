"""
Tableau de bord : Situation des revenus.

Total des revenus = Revenu du portefeuille (Frais de dossier + Intérêts +
Intérêts pénalité + Frais de pénalité) + Droit d'adhésion + Reprises de
provisions + Récupération pertes + Produits moyens de paiement + Produits
prestations services financiers + Autres produits.

Quand la catégorie sélectionnée est une mutuelle (pas Consolidé), les
Charges de groupe rétrocédé s'ajoutent au total et apparaissent en KPI à
part (répartition inter-entités du groupe, propre à chaque mutuelle).
"""

from __future__ import annotations

import datetime as dt

import streamlit as st

from dashboards import components as c
from dashboards import data

_TYPES_REVENU = [
    "Revenu du portefeuille",
    "Droit d'adhésion",
    "Reprises de provisions",
    "Récupération pertes",
    "Produits moyens de paiement",
    "Produits prestations services financiers",
    "Autres produits",
]


def _detail(categorie: str, date_arrete: dt.date) -> dict:
    totals = data.rubrique_totals_cached(categorie, date_arrete)

    revenu_portefeuille = (
        totals.get(data.RUB_FRAIS_DOSSIER, 0.0)
        + totals.get(data.RUB_INTERET, 0.0)
        + totals.get(data.RUB_INTERET_PENALITE, 0.0)
        + totals.get(data.RUB_FRAIS_PENALITE, 0.0)
    )
    droit_adhesion = totals.get(data.RUB_DROIT_ADHESION, 0.0)
    reprises_provisions = totals.get(data.RUB_REPRISES_PROVISIONS, 0.0)
    recuperation_pertes = totals.get(data.RUB_RECUPERATION_PERTES, 0.0)
    produits_mp = totals.get(data.RUB_PRODUITS_MP, 0.0)
    produits_psf = totals.get(data.RUB_PRODUITS_PSF, 0.0)
    autres_produits = totals.get(data.RUB_AUTRES_PRODUITS, 0.0)
    charges_groupe_retrocede = totals.get(data.RUB_CHARGES_GROUPE_RETROCEDE, 0.0)

    total = (
        revenu_portefeuille
        + droit_adhesion
        + reprises_provisions
        + recuperation_pertes
        + produits_mp
        + produits_psf
        + autres_produits
    )

    est_mutuelle = categorie != data.CATEGORIE_CONSOLIDE
    if est_mutuelle:
        total += charges_groupe_retrocede

    return {
        "revenu_portefeuille": revenu_portefeuille,
        "droit_adhesion": droit_adhesion,
        "reprises_provisions": reprises_provisions,
        "recuperation_pertes": recuperation_pertes,
        "produits_mp": produits_mp,
        "produits_psf": produits_psf,
        "autres_produits": autres_produits,
        "charges_groupe_retrocede": charges_groupe_retrocede,
        "total": total,
        "est_mutuelle": est_mutuelle,
    }


def render(categorie: str, date_arrete: dt.date) -> None:
    c.inject_css()

    d = _detail(categorie, date_arrete)

    c.hero_metric(
        "Total des revenus",
        c.fmt_montant(d["total"]),
        sub=f"{categorie} · {date_arrete:%d/%m/%Y}",
    )

    st.write("")
    kpis = [
        ("Revenu du portefeuille", c.fmt_montant(d["revenu_portefeuille"])),
        ("Droit d'adhésion", c.fmt_montant(d["droit_adhesion"])),
        ("Reprises de provisions", c.fmt_montant(d["reprises_provisions"])),
        ("Récupération pertes", c.fmt_montant(d["recuperation_pertes"])),
        ("Produits moyens de paiement", c.fmt_montant(d["produits_mp"])),
        ("Produits prestations services financiers", c.fmt_montant(d["produits_psf"])),
        ("Autres produits", c.fmt_montant(d["autres_produits"])),
    ]
    if d["est_mutuelle"]:
        kpis.append(("Charges de groupe rétrocédé", c.fmt_montant(d["charges_groupe_retrocede"])))

    # 4 cartes par ligne pour rester lisible
    for i in range(0, len(kpis), 4):
        c.kpi_row(kpis[i : i + 4])

    c.section_title("Répartition des revenus par type")
    labels = list(_TYPES_REVENU)
    values = [
        d["revenu_portefeuille"],
        d["droit_adhesion"],
        d["reprises_provisions"],
        d["recuperation_pertes"],
        d["produits_mp"],
        d["produits_psf"],
        d["autres_produits"],
    ]
    if d["est_mutuelle"]:
        labels.append("Charges de groupe rétrocédé")
        values.append(d["charges_groupe_retrocede"])

    fig = c.bar_repartition(labels, values)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    if categorie == data.CATEGORIE_CONSOLIDE:
        c.section_title("Revenus par mutuelle")
        _render_par_mutuelle(date_arrete)


def _render_par_mutuelle(date_arrete: dt.date) -> None:
    df_rub = data.rubrique_totals_par_categorie_cached(date_arrete)
    if df_rub.empty:
        c.empty_note(
            "Aucune donnée par mutuelle chargée pour cette date d'arrêté pour l'instant."
        )
        return

    rubs_revenu = [
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
        data.RUB_CHARGES_GROUPE_RETROCEDE,  # chaque mutuelle inclut son rétrocédé
    ]
    par_mut = (
        df_rub[df_rub["RUBRIQUE"].isin(rubs_revenu)]
        .groupby("CATEGORIE")["TOTAL"]
        .sum()
        .reset_index()
        .rename(columns={"TOTAL": "REVENU_TOTAL"})
    )
    if par_mut.empty:
        c.empty_note("Aucune mutuelle avec des revenus renseignés à cette date.")
        return

    fig = c.bar_classement(par_mut, "CATEGORIE", "REVENU_TOTAL")
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

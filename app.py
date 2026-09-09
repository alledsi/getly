"""
Getly — rapports et extractions ACEP

Menu latéral pour choisir un rapport, formulaire propre à l'extraction
sélectionnée, tableau de résultat, export Excel.

Lancement :
    streamlit run app.py
"""

from __future__ import annotations

import datetime as dt

import streamlit as st

import auth
from auth_ui import (
    afficher_message_en_attente,
    render_account_page,
    render_admin_page,
    render_forced_password_change,
    render_login,
)
from dashboards import DASHBOARDS, get_dashboard
from dashboards import components as c
from dashboards import data as dashboard_data
from export_excel import build_excel
from extractions import EXTRACTIONS, get_extraction

st.set_page_config(page_title="Getly", page_icon="📊", layout="wide")

auth.init_db()


# ---------------------------------------------------------------------------
# Authentification : bloque tout le reste tant que l'utilisateur n'est pas
# connecté (et, le cas échéant, tant qu'il n'a pas changé son mot de passe
# provisoire).
# ---------------------------------------------------------------------------
if "user" not in st.session_state:
    render_login()
    st.stop()

utilisateur = st.session_state["user"]

# Affiche un éventuel message laissé par l'écran précédent (ex. "utilisateur
# créé") avant un st.rerun() — sinon le message n'a pas le temps de s'afficher.
afficher_message_en_attente()

if utilisateur.get("doit_changer_mdp"):
    render_forced_password_change(utilisateur)
    st.stop()


# ---------------------------------------------------------------------------
# Permissions : rapports et tableaux de bord visibles pour cet utilisateur,
# selon sa direction (voir auth.get_visible_item_ids). Un administrateur
# voit toujours tout. Un utilisateur sans direction voit tous les rapports
# (accès historique) mais aucun tableau de bord (fonctionnalité réservée
# par direction, voir « 🛠️ Administration » → « Permissions par direction »).
# ---------------------------------------------------------------------------
extraction_ids_visibles = auth.get_visible_item_ids(utilisateur, "extraction")
dashboard_ids_visibles = auth.get_visible_item_ids(utilisateur, "dashboard")

extractions_visibles = (
    EXTRACTIONS
    if extraction_ids_visibles is None
    else [e for e in EXTRACTIONS if e.id in extraction_ids_visibles]
)
dashboards_visibles = (
    DASHBOARDS
    if dashboard_ids_visibles is None
    else [d for d in DASHBOARDS if d.id in dashboard_ids_visibles]
)

# ---------------------------------------------------------------------------
# Barre latérale : identité de l'appli, utilisateur connecté, navigation
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("📊 Getly")
    st.caption("Rapports et extractions — ACEP")

    role_libelle = "Administrateur" if utilisateur["role"] == "admin" else "Utilisateur"
    st.caption(f"Connecté : **{utilisateur['username']}** ({role_libelle})")
    if utilisateur.get("direction_nom"):
        st.caption(f"Direction : **{utilisateur['direction_nom']}**")
    if st.button("Se déconnecter", width="stretch"):
        del st.session_state["user"]
        st.rerun()

    st.divider()

    sections = ["📁 Rapports"]
    if dashboards_visibles:
        sections.append("📊 Tableaux de bord")
    sections.append("👤 Mon compte")
    if utilisateur["role"] == "admin":
        sections.append("🛠️ Administration")
    section = st.radio("Navigation", sections, label_visibility="collapsed")

    extraction_id = None
    if section == "📁 Rapports" and extractions_visibles:
        st.subheader("Choisir un rapport")
        labels = {f"{e.icon}  {e.label}": e.id for e in extractions_visibles}
        choix_label = st.radio(
            "Choisir un rapport", list(labels.keys()), label_visibility="collapsed"
        )
        extraction_id = labels[choix_label]

    dashboard_id = None
    if section == "📊 Tableaux de bord" and dashboards_visibles:
        st.subheader("Choisir un tableau de bord")
        labels_db = {f"{d.icon}  {d.label}": d.id for d in dashboards_visibles}
        choix_db = st.radio(
            "Choisir un tableau de bord", list(labels_db.keys()), label_visibility="collapsed"
        )
        dashboard_id = labels_db[choix_db]

if section == "👤 Mon compte":
    render_account_page(utilisateur)
    st.stop()

if section == "🛠️ Administration":
    render_admin_page(utilisateur)
    st.stop()

if section == "📁 Rapports" and not extractions_visibles:
    st.header("📁 Rapports")
    st.info(
        "Aucun rapport n'est disponible pour ta direction pour le moment. "
        "Contacte un administrateur."
    )
    st.stop()

if section == "📊 Tableaux de bord":
    dashboard = get_dashboard(dashboard_id)

    c.inject_css()
    c.user_badge(utilisateur["username"], utilisateur.get("direction_nom"))
    st.header(f"{dashboard.icon} {dashboard.label}")
    if dashboard.description:
        st.caption(dashboard.description)

    try:
        categories = dashboard_data.categories_cached()
    except Exception as exc:  # noqa: BLE001
        categories = []
        st.error(f"Impossible de charger les catégories disponibles : {exc}")

    try:
        dates_dispo = dashboard_data.dates_arrete_cached()
    except Exception as exc:  # noqa: BLE001
        dates_dispo = []
        st.error(f"Impossible de charger les dates d'arrêté disponibles : {exc}")

    if not categories or not dates_dispo:
        st.warning(
            "Aucune donnée disponible pour le moment dans RPT_RENTABILITE / "
            "RPT_ENCOURS — charge d'abord une balance mensuelle."
        )
        st.stop()

    fcol1, fcol2 = st.columns(2)
    if dashboard.filtre_date_arrete:
        with fcol1:
            categorie_choisie = st.selectbox("Catégorie *", options=categories, index=0)
        with fcol2:
            date_choisie = st.selectbox(
                "Date d'arrêté *",
                options=dates_dispo,
                index=0,
                format_func=lambda d: d.strftime("%d/%m/%Y"),
            )
    else:
        # Tableaux de bord "par année" (ex. Encours) : pas de filtre "Date
        # d'arrêté", remplacé par un filtre "Année" aligné dans la même
        # ligne. On fait transiter l'année choisie via `date_choisie` (1er
        # janvier de l'année) plutôt que de changer la signature commune de
        # `Dashboard.render` — le dashboard n'en récupère que `.year`.
        annees_dispo = dashboard_data.annees_encours_cached()
        with fcol1:
            categorie_choisie = st.selectbox("Catégorie *", options=categories, index=0)
        with fcol2:
            if annees_dispo:
                annee_choisie = st.selectbox("Année *", options=annees_dispo, index=0)
            else:
                annee_choisie = dt.date.today().year
                st.selectbox(
                    "Année *", options=[annee_choisie], index=0, disabled=True
                )
        date_choisie = dt.date(annee_choisie, 1, 1)

    st.divider()
    dashboard.render(categorie_choisie, date_choisie)
    st.stop()

extraction = get_extraction(extraction_id)


# ---------------------------------------------------------------------------
# Zone principale : formulaire + résultat de l'extraction sélectionnée
# ---------------------------------------------------------------------------
st.header(f"{extraction.icon} {extraction.label}")
if extraction.description:
    st.caption(extraction.description)

filters = extraction.render_form()

res_key = f"resultat::{extraction.id}"
filtres_key = f"filtres::{extraction.id}"

if filters is not None:
    with st.spinner("Extraction en cours..."):
        try:
            df = extraction.execute(filters)
            st.session_state[res_key] = df
            st.session_state[filtres_key] = filters
        except Exception as exc:  # noqa: BLE001
            st.session_state.pop(res_key, None)
            st.error(f"Erreur lors de l'extraction : {exc}")

if res_key in st.session_state:
    df = st.session_state[res_key]
    filtres_actifs = st.session_state[filtres_key]

    st.subheader("Résultat")

    if df.empty:
        st.info("Aucune donnée ne correspond à ces critères.")
    else:
        cols_metric = st.columns(3)
        cols_metric[0].metric("Nombre de lignes", f"{len(df):,}".replace(",", " "))
        if "DEBIT" in df.columns and "CREDIT" in df.columns:
            cols_metric[1].metric(
                "Total débit", f"{df['DEBIT'].sum():,.2f}".replace(",", " ")
            )
            cols_metric[2].metric(
                "Total crédit", f"{df['CREDIT'].sum():,.2f}".replace(",", " ")
            )

        column_config = {}
        for c in extraction.date_cols:
            if c in df.columns:
                column_config[c] = st.column_config.DateColumn(
                    extraction.column_labels.get(c, c), format="DD/MM/YYYY"
                )
        for c in extraction.montant_cols:
            if c in df.columns:
                column_config[c] = st.column_config.NumberColumn(
                    extraction.column_labels.get(c, c), format="%.2f"
                )

        st.dataframe(
            df,
            width="stretch",
            hide_index=True,
            column_config=column_config,
        )

        excel_buffer = build_excel(
            df,
            column_labels=extraction.column_labels,
            montant_cols=extraction.montant_cols,
            date_cols=extraction.date_cols,
            total_cols=extraction.total_cols,
            sheet_name=extraction.label,
        )
        st.download_button(
            label="⬇️ Télécharger en Excel",
            data=excel_buffer,
            file_name=extraction.excel_filename(filtres_actifs),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )

"""
Getly — rapports et extractions ACEP

Menu latéral pour choisir un rapport, formulaire propre à l'extraction
sélectionnée, tableau de résultat, export Excel.

Lancement :
    streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

import auth
from auth_ui import (
    afficher_message_en_attente,
    render_account_page,
    render_admin_page,
    render_forced_password_change,
    render_login,
)
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
# Barre latérale : identité de l'appli, utilisateur connecté, navigation
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("📊 Getly")
    st.caption("Rapports et extractions — ACEP")

    role_libelle = "Administrateur" if utilisateur["role"] == "admin" else "Utilisateur"
    st.caption(f"Connecté : **{utilisateur['username']}** ({role_libelle})")
    if st.button("Se déconnecter", width="stretch"):
        del st.session_state["user"]
        st.rerun()

    st.divider()

    sections = ["📁 Rapports", "👤 Mon compte"]
    if utilisateur["role"] == "admin":
        sections.append("🛠️ Administration")
    section = st.radio("Navigation", sections, label_visibility="collapsed")

    extraction_id = None
    if section == "📁 Rapports":
        st.subheader("Choisir un rapport")
        labels = {f"{e.icon}  {e.label}": e.id for e in EXTRACTIONS}
        choix_label = st.radio(
            "Choisir un rapport", list(labels.keys()), label_visibility="collapsed"
        )
        extraction_id = labels[choix_label]

if section == "👤 Mon compte":
    render_account_page(utilisateur)
    st.stop()

if section == "🛠️ Administration":
    render_admin_page(utilisateur)
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

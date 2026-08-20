"""
Référentiel partagé Mutuelle -> Agence -> Bureau, et petit utilitaire de
menu déroulant "CODE — Libellé". Utilisé par plusieurs extractions (ex.
Journal des écritures, État des dépôts) pour proposer les mêmes filtres
de localisation en cascade, sans dupliquer la requête ni le widget.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
import streamlit as st

from db import fetch_df


def get_referentiel_localisation() -> pd.DataFrame:
    """
    Bureaux avec leur agence et leur mutuelle (hiérarchie
    Mutuelle -> Agence -> Bureau), pour construire les menus déroulants
    en cascade des formulaires.
    """
    sql = """
        SELECT
            b.CODE_BUREAU, b.LIBELLE_BUREAU,
            r.CODE_REGION, r.LIB_REGION,
            m.CODE_MUTUELLE, m.NOM_MUTUELLE
        FROM BUREAU b
        LEFT JOIN REGION r   ON r.CODE_REGION = b.CODE_REGION
        LEFT JOIN MUTUELLE m ON m.CODE_MUTUELLE = r.CODE_MUTUELLE
        ORDER BY m.NOM_MUTUELLE, r.LIB_REGION, b.LIBELLE_BUREAU
    """
    return fetch_df(sql)


@st.cache_data(ttl=3600, show_spinner=False)
def referentiel_localisation_cached() -> pd.DataFrame:
    return get_referentiel_localisation()


def select_code_libelle(
    label: str,
    df: pd.DataFrame,
    code_col: str,
    libelle_col: str,
    placeholder: str,
    key: str,
    max_chars: Optional[int] = None,
    allow_text_fallback: bool = True,
) -> str:
    """
    Menu déroulant "CODE — Libellé" construit à partir d'un DataFrame de
    référence (éventuellement déjà filtré par le choix précédent dans une
    cascade). Retourne le code sélectionné (chaîne vide si aucun choix).

    - Si `df` est vide ET `allow_text_fallback` est vrai (liste de
      référence indisponible), retombe sur un champ texte libre.
    - Si `df` est vide et `allow_text_fallback` est faux (cas d'une
      cascade dont le filtre parent ne laisse aucun résultat), affiche un
      menu désactivé plutôt qu'un champ texte trompeur.
    """
    if df.empty:
        if allow_text_fallback:
            return st.text_input(label, max_chars=max_chars, key=f"{key}_txt") or ""
        st.selectbox(
            label, options=[], placeholder="Aucun résultat", disabled=True, key=f"{key}_vide"
        )
        return ""

    options = [f"{getattr(row, code_col)} — {getattr(row, libelle_col)}" for row in df.itertuples()]
    choix = st.selectbox(label, options=options, index=None, placeholder=placeholder, key=key)
    return choix.split(" — ")[0] if choix else ""


def render_localisation_cascade(
    ref_localisation_df: pd.DataFrame,
    key_prefix: str = "",
) -> tuple[str, str, str]:
    """
    Affiche les 3 menus déroulants en cascade Mutuelle -> Agence -> Bureau
    et retourne (code_mutuelle, code_agence, code_bureau) sélectionnés
    (chaîne vide si "Tous/Toutes"). `key_prefix` permet d'avoir plusieurs
    cascades indépendantes sur une même page (une par extraction).
    """
    localisation_indisponible = ref_localisation_df.empty

    k_mutuelle = f"{key_prefix}code_mutuelle"
    k_agence = f"{key_prefix}code_agence"
    k_bureau = f"{key_prefix}code_bureau"
    k_last_mutuelle = f"{key_prefix}_last_code_mutuelle"
    k_last_agence = f"{key_prefix}_last_code_agence"

    c4, c5, c6 = st.columns(3)

    with c4:
        mutuelles_df = (
            ref_localisation_df[["CODE_MUTUELLE", "NOM_MUTUELLE"]]
            .dropna()
            .drop_duplicates()
            .sort_values("NOM_MUTUELLE")
        )
        code_mutuelle = select_code_libelle(
            "Mutuelle", mutuelles_df, "CODE_MUTUELLE", "NOM_MUTUELLE",
            "Toutes", k_mutuelle,
            allow_text_fallback=localisation_indisponible,
        )

    # Réinitialise les choix dépendants quand la mutuelle change
    if code_mutuelle != st.session_state.get(k_last_mutuelle):
        st.session_state.pop(k_agence, None)
        st.session_state.pop(k_bureau, None)
        st.session_state[k_last_mutuelle] = code_mutuelle

    perimetre_mutuelle = (
        ref_localisation_df
        if not code_mutuelle
        else ref_localisation_df[ref_localisation_df["CODE_MUTUELLE"] == code_mutuelle]
    )

    with c5:
        agences_df = (
            perimetre_mutuelle[["CODE_REGION", "LIB_REGION"]]
            .dropna()
            .drop_duplicates()
            .sort_values("LIB_REGION")
        )
        code_agence = select_code_libelle(
            "Agence", agences_df, "CODE_REGION", "LIB_REGION",
            "Toutes", k_agence,
            allow_text_fallback=localisation_indisponible,
        )

    # Réinitialise le bureau quand l'agence change
    if code_agence != st.session_state.get(k_last_agence):
        st.session_state.pop(k_bureau, None)
        st.session_state[k_last_agence] = code_agence

    perimetre_agence = (
        perimetre_mutuelle
        if not code_agence
        else perimetre_mutuelle[perimetre_mutuelle["CODE_REGION"] == code_agence]
    )

    with c6:
        bureaux_df = (
            perimetre_agence[["CODE_BUREAU", "LIBELLE_BUREAU"]]
            .dropna()
            .drop_duplicates()
            .sort_values("LIBELLE_BUREAU")
        )
        code_bureau = select_code_libelle(
            "Bureau", bureaux_df, "CODE_BUREAU", "LIBELLE_BUREAU",
            "Tous", k_bureau,
            allow_text_fallback=localisation_indisponible,
        )

    return code_mutuelle, code_agence, code_bureau

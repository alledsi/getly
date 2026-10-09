"""
Extraction : Évaluation CC (attrition).

Évaluation mensuelle de l'activité et de l'attrition des comptes
courants/épargne par agence/bureau, comparant la période N à la période
N-1, à partir de la vue SV_EVAL_CC.

Champ obligatoire : date d'arrêté (liste déroulante des dates
disponibles, la plus récente par défaut). Filtres facultatifs :
localisation hiérarchique (Mutuelle -> Agence -> Bureau).

Les colonnes affichées reproduisent exactement la requête fournie par
l'utilisateur (ne pas en ajouter/retirer) : seule la clause des filtres
change selon ce qui est choisi dans le formulaire. Les noms de colonnes
source de la vue SV_EVAL_CC sont reproduits tels quels (certains sont
entre guillemets et sensibles à la casse côté Oracle, avec une casse
mixte conservée volontairement par l'alias — ne pas les modifier).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import streamlit as st

from db import fetch_df
from extractions.base import Extraction
from extractions.reference_data import (
    dates_arrete_eval_cc_cached,
    referentiel_localisation_cached,
    render_localisation_cascade,
)

# ---------------------------------------------------------------------------
# Filtres du formulaire
# ---------------------------------------------------------------------------


@dataclass
class EvalCcAttritionFilters:
    date_arrete: Optional[dt.date]
    code_mutuelle: Optional[str] = None
    code_agence: Optional[str] = None
    code_bureau: Optional[str] = None

    def validate(self) -> Optional[str]:
        if not self.date_arrete:
            return "La date d'arrêté est obligatoire."
        return None


# ---------------------------------------------------------------------------
# Accès aux données
# ---------------------------------------------------------------------------

_BASE_SQL = """
    SELECT
        e.DATE_ARRETE, e.CODE_REGION, e.LIB_REGION, e.CODE_BUREAU, e.LIBELLE_BUREAU,
        -- Période N
        e."NB_nouv_client", e.NB_CLIENT_TOTAL, e.NB_CLIENT_ACTIF,
        e.NB_WALLET_TOTAL, e.NB_WALLET_ACTIF, e.NB_WALLET_PERIODE,
        e.NB_OUV_CPT_PERIODE, e.NB_OUV_CPT_EPA_PERIODE,
        e.NB_CPT_TOTAL, e.NB_CPT_ACTIF, e.NB_PRET,
        ROUND(e."Enc_crd", 2)      AS "Enc_crd",
        ROUND(e."Enc_cc", 2)       AS "Enc_cc",
        ROUND(e."Enc_spec", 2)     AS "Enc_spec",
        ROUND(e."Enc_dav", 2)      AS "Enc_dav",
        ROUND(e."Enc_dat", 2)      AS "Enc_dat",
        ROUND(e."Enc_epj", 2)      AS "Enc_epj",
        ROUND(e."Enc_epa_vol", 2)  AS "Enc_epa_vol",
        e."NB_dav", e."NB_ces", e."NB_dat", e."NB_pep",
        ROUND(e."Taux_couv_EPARGNE", 4) AS "Taux_couv_EPARGNE",
        e."NB_mep", e."NB_nouv_mep", e."NB_emprunteurs", e."NB_nouv_emprunteurs",
        e."NB_desistements", e."NB_non_renouv_pret", e."NB_ces_crediteur",
        e."NB_virement", e."NB_bq_assur", e."NB_vente_carte", e."NB_recharge_carte",
        ROUND(e."mt_prod_cions", 2) AS "mt_prod_cions",
        -- Période N-1
        e."NB_nouv_client_N1", e.NB_CLIENT_TOTAL_N1, e.NB_CLIENT_ACTIF_N1,
        e.NB_WALLET_TOTAL_N1, e.NB_WALLET_ACTIF_N1, e.NB_WALLET_PERIODE_N1,
        e.NB_OUV_CPT_PERIODE_N1, e.NB_OUV_CPT_EPA_PERIODE_N1,
        e.NB_CPT_TOTAL_N1, e.NB_CPT_ACTIF_N1, e.NB_PRET_N1,
        ROUND(e."Enc_crd_N1", 2)     AS "Enc_crd_N1",
        ROUND(e."Enc_cc_N1", 2)      AS "Enc_cc_N1",
        ROUND(e."Enc_spec_N1", 2)    AS "Enc_spec_N1",
        ROUND(e."Enc_dav_N1", 2)     AS "Enc_dav_N1",
        ROUND(e."Enc_dat_N1", 2)     AS "Enc_dat_N1",
        ROUND(e."Enc_epj_N1", 2)     AS "Enc_epj_N1",
        ROUND(e."Enc_epa_vol_N1", 2) AS "Enc_epa_vol_N1",
        e."NB_dav_N1", e."NB_ces_N1", e."NB_dat_N1", e."NB_pep_N1",
        ROUND(e."Taux_couv_EPARGNE_N1", 4) AS "Taux_couv_EPARGNE_N1",
        e."NB_mep_N1", e."NB_nouv_mep_N1", e."NB_emprunteurs_N1", e."NB_nouv_emprunteurs_N1",
        e."NB_desistements_N1", e."NB_non_renouv_pret_N1", e."NB_ces_crediteur_N1",
        e."NB_virement_N1", e."NB_bq_assur_N1", e."NB_vente_carte_N1", e."NB_recharge_carte_N1",
        ROUND(e."mt_prod_cions_N1", 2) AS "mt_prod_cions_N1",
        -- Taux
        ROUND(e."Taux_abandon", 4)      AS "Taux_abandon",
        ROUND(e."Taux_attrition", 4)    AS "Taux_attrition",
        ROUND(e."Taux_equip", 4)        AS "Taux_equip",
        ROUND(e."Taux_ouv_CC", 4)       AS "Taux_ouv_CC",
        ROUND(e."Taux_ouv_CE", 4)       AS "Taux_ouv_CE",
        ROUND(e."Taux_ouv_epa", 4)      AS "Taux_ouv_epa",
        ROUND(e."Taux_act_b2w", 4)      AS "Taux_act_b2w",
        ROUND(e."Taux_abandon_N1", 4)   AS "Taux_abandon_N1",
        ROUND(e."Taux_fidele_N1", 4)    AS "Taux_fidele_N1",
        ROUND(e."Taux_equip_N1", 4)     AS "Taux_equip_N1",
        ROUND(e."Taux_ouv_CC_N1", 4)    AS "Taux_ouv_CC_N1",
        ROUND(e."Taux_ouv_CE_N1", 4)    AS "Taux_ouv_CE_N1",
        ROUND(e."Taux_Couv_epa_N1", 4)  AS "Taux_Couv_epa_N1",
        ROUND(e."Taux_act_b2w_N1", 4)   AS "Taux_act_b2w_N1",
        e.NB_PRODUIT_ACTIVE, e.NB_PRODUIT_ACTIVE_N1
    FROM sv_eval_cc e
    LEFT JOIN REGION r      ON r.CODE_REGION = e.CODE_REGION
    LEFT JOIN MUTUELLE mut  ON mut.CODE_MUTUELLE = r.CODE_MUTUELLE
    WHERE e.DATE_ARRETE = :date_arrete
"""

_ORDER_SQL = " ORDER BY e.LIB_REGION, e.LIBELLE_BUREAU"

_COLONNES_FINALES = [
    "DATE_ARRETE", "CODE_REGION", "LIB_REGION", "CODE_BUREAU", "LIBELLE_BUREAU",
    # Période N
    "NB_nouv_client", "NB_CLIENT_TOTAL", "NB_CLIENT_ACTIF",
    "NB_WALLET_TOTAL", "NB_WALLET_ACTIF", "NB_WALLET_PERIODE",
    "NB_OUV_CPT_PERIODE", "NB_OUV_CPT_EPA_PERIODE",
    "NB_CPT_TOTAL", "NB_CPT_ACTIF", "NB_PRET",
    "Enc_crd", "Enc_cc", "Enc_spec", "Enc_dav", "Enc_dat", "Enc_epj", "Enc_epa_vol",
    "NB_dav", "NB_ces", "NB_dat", "NB_pep",
    "Taux_couv_EPARGNE",
    "NB_mep", "NB_nouv_mep", "NB_emprunteurs", "NB_nouv_emprunteurs",
    "NB_desistements", "NB_non_renouv_pret", "NB_ces_crediteur",
    "NB_virement", "NB_bq_assur", "NB_vente_carte", "NB_recharge_carte",
    "mt_prod_cions",
    # Période N-1
    "NB_nouv_client_N1", "NB_CLIENT_TOTAL_N1", "NB_CLIENT_ACTIF_N1",
    "NB_WALLET_TOTAL_N1", "NB_WALLET_ACTIF_N1", "NB_WALLET_PERIODE_N1",
    "NB_OUV_CPT_PERIODE_N1", "NB_OUV_CPT_EPA_PERIODE_N1",
    "NB_CPT_TOTAL_N1", "NB_CPT_ACTIF_N1", "NB_PRET_N1",
    "Enc_crd_N1", "Enc_cc_N1", "Enc_spec_N1", "Enc_dav_N1", "Enc_dat_N1",
    "Enc_epj_N1", "Enc_epa_vol_N1",
    "NB_dav_N1", "NB_ces_N1", "NB_dat_N1", "NB_pep_N1",
    "Taux_couv_EPARGNE_N1",
    "NB_mep_N1", "NB_nouv_mep_N1", "NB_emprunteurs_N1", "NB_nouv_emprunteurs_N1",
    "NB_desistements_N1", "NB_non_renouv_pret_N1", "NB_ces_crediteur_N1",
    "NB_virement_N1", "NB_bq_assur_N1", "NB_vente_carte_N1", "NB_recharge_carte_N1",
    "mt_prod_cions_N1",
    # Taux
    "Taux_abandon", "Taux_attrition", "Taux_equip", "Taux_ouv_CC", "Taux_ouv_CE",
    "Taux_ouv_epa", "Taux_act_b2w",
    "Taux_abandon_N1", "Taux_fidele_N1", "Taux_equip_N1", "Taux_ouv_CC_N1",
    "Taux_ouv_CE_N1", "Taux_Couv_epa_N1", "Taux_act_b2w_N1",
    "NB_PRODUIT_ACTIVE", "NB_PRODUIT_ACTIVE_N1",
]


def get_eval_cc_attrition(filters: EvalCcAttritionFilters) -> pd.DataFrame:
    """Construit et exécute la requête d'évaluation CC (attrition) à la date d'arrêté choisie."""
    error = filters.validate()
    if error:
        raise ValueError(error)

    sql = _BASE_SQL
    params: dict = {
        "date_arrete": dt.datetime.combine(filters.date_arrete, dt.time.min),
    }

    if filters.code_mutuelle:
        sql += " AND mut.CODE_MUTUELLE = :code_mutuelle"
        params["code_mutuelle"] = filters.code_mutuelle.strip()

    if filters.code_agence:
        sql += " AND e.CODE_REGION = :code_agence"
        params["code_agence"] = filters.code_agence.strip()

    if filters.code_bureau:
        sql += " AND e.CODE_BUREAU = :code_bureau"
        params["code_bureau"] = filters.code_bureau.strip()

    sql += _ORDER_SQL

    df = fetch_df(sql, params)
    if df.empty:
        return pd.DataFrame(columns=_COLONNES_FINALES)
    return df[_COLONNES_FINALES]


# ---------------------------------------------------------------------------
# Formulaire Streamlit
# ---------------------------------------------------------------------------

LIBELLES_COLONNES = {
    "DATE_ARRETE": "Date arrêté",
    "CODE_REGION": "Code agence",
    "LIB_REGION": "Agence",
    "CODE_BUREAU": "Code bureau",
    "LIBELLE_BUREAU": "Bureau",
    "NB_nouv_client": "Nouveaux clients",
    "NB_CLIENT_TOTAL": "Clients total",
    "NB_CLIENT_ACTIF": "Clients actifs",
    "NB_WALLET_TOTAL": "Wallets total",
    "NB_WALLET_ACTIF": "Wallets actifs",
    "NB_WALLET_PERIODE": "Wallets ouverts (période)",
    "NB_OUV_CPT_PERIODE": "Comptes ouverts (période)",
    "NB_OUV_CPT_EPA_PERIODE": "Comptes épargne ouverts (période)",
    "NB_CPT_TOTAL": "Comptes total",
    "NB_CPT_ACTIF": "Comptes actifs",
    "NB_PRET": "Nombre de prêts",
    "Enc_crd": "Encours créditeur",
    "Enc_cc": "Encours compte courant",
    "Enc_spec": "Encours épargne spéciale",
    "Enc_dav": "Encours DAV",
    "Enc_dat": "Encours DAT",
    "Enc_epj": "Encours épargne projet",
    "Enc_epa_vol": "Encours épargne volontaire",
    "NB_dav": "Nombre de comptes DAV",
    "NB_ces": "Nombre de comptes CES",
    "NB_dat": "Nombre de comptes DAT",
    "NB_pep": "Nombre de PEP",
    "Taux_couv_EPARGNE": "Taux de couverture épargne",
    "NB_mep": "Nombre de MEP",
    "NB_nouv_mep": "Nouveaux MEP",
    "NB_emprunteurs": "Nombre d'emprunteurs",
    "NB_nouv_emprunteurs": "Nouveaux emprunteurs",
    "NB_desistements": "Désistements",
    "NB_non_renouv_pret": "Prêts non renouvelés",
    "NB_ces_crediteur": "CES créditeurs",
    "NB_virement": "Nombre de virements",
    "NB_bq_assur": "Bancassurance",
    "NB_vente_carte": "Ventes de cartes",
    "NB_recharge_carte": "Recharges de carte",
    "mt_prod_cions": "Montant produit commissions",
    "NB_nouv_client_N1": "Nouveaux clients (N-1)",
    "NB_CLIENT_TOTAL_N1": "Clients total (N-1)",
    "NB_CLIENT_ACTIF_N1": "Clients actifs (N-1)",
    "NB_WALLET_TOTAL_N1": "Wallets total (N-1)",
    "NB_WALLET_ACTIF_N1": "Wallets actifs (N-1)",
    "NB_WALLET_PERIODE_N1": "Wallets ouverts (période N-1)",
    "NB_OUV_CPT_PERIODE_N1": "Comptes ouverts (période N-1)",
    "NB_OUV_CPT_EPA_PERIODE_N1": "Comptes épargne ouverts (période N-1)",
    "NB_CPT_TOTAL_N1": "Comptes total (N-1)",
    "NB_CPT_ACTIF_N1": "Comptes actifs (N-1)",
    "NB_PRET_N1": "Nombre de prêts (N-1)",
    "Enc_crd_N1": "Encours créditeur (N-1)",
    "Enc_cc_N1": "Encours compte courant (N-1)",
    "Enc_spec_N1": "Encours épargne spéciale (N-1)",
    "Enc_dav_N1": "Encours DAV (N-1)",
    "Enc_dat_N1": "Encours DAT (N-1)",
    "Enc_epj_N1": "Encours épargne projet (N-1)",
    "Enc_epa_vol_N1": "Encours épargne volontaire (N-1)",
    "NB_dav_N1": "Nombre de comptes DAV (N-1)",
    "NB_ces_N1": "Nombre de comptes CES (N-1)",
    "NB_dat_N1": "Nombre de comptes DAT (N-1)",
    "NB_pep_N1": "Nombre de PEP (N-1)",
    "Taux_couv_EPARGNE_N1": "Taux de couverture épargne (N-1)",
    "NB_mep_N1": "Nombre de MEP (N-1)",
    "NB_nouv_mep_N1": "Nouveaux MEP (N-1)",
    "NB_emprunteurs_N1": "Nombre d'emprunteurs (N-1)",
    "NB_nouv_emprunteurs_N1": "Nouveaux emprunteurs (N-1)",
    "NB_desistements_N1": "Désistements (N-1)",
    "NB_non_renouv_pret_N1": "Prêts non renouvelés (N-1)",
    "NB_ces_crediteur_N1": "CES créditeurs (N-1)",
    "NB_virement_N1": "Nombre de virements (N-1)",
    "NB_bq_assur_N1": "Bancassurance (N-1)",
    "NB_vente_carte_N1": "Ventes de cartes (N-1)",
    "NB_recharge_carte_N1": "Recharges de carte (N-1)",
    "mt_prod_cions_N1": "Montant produit commissions (N-1)",
    "Taux_abandon": "Taux d'abandon",
    "Taux_attrition": "Taux d'attrition",
    "Taux_equip": "Taux d'équipement",
    "Taux_ouv_CC": "Taux d'ouverture CC",
    "Taux_ouv_CE": "Taux d'ouverture CE",
    "Taux_ouv_epa": "Taux d'ouverture épargne",
    "Taux_act_b2w": "Taux d'activation B2W",
    "Taux_abandon_N1": "Taux d'abandon (N-1)",
    "Taux_fidele_N1": "Taux de fidélité (N-1)",
    "Taux_equip_N1": "Taux d'équipement (N-1)",
    "Taux_ouv_CC_N1": "Taux d'ouverture CC (N-1)",
    "Taux_ouv_CE_N1": "Taux d'ouverture CE (N-1)",
    "Taux_Couv_epa_N1": "Taux de couverture épargne (N-1)",
    "Taux_act_b2w_N1": "Taux d'activation B2W (N-1)",
    "NB_PRODUIT_ACTIVE": "Produits activés",
    "NB_PRODUIT_ACTIVE_N1": "Produits activés (N-1)",
}

_MONTANT_COLS = {
    "Enc_crd", "Enc_cc", "Enc_spec", "Enc_dav", "Enc_dat", "Enc_epj", "Enc_epa_vol",
    "mt_prod_cions",
    "Enc_crd_N1", "Enc_cc_N1", "Enc_spec_N1", "Enc_dav_N1", "Enc_dat_N1",
    "Enc_epj_N1", "Enc_epa_vol_N1",
    "mt_prod_cions_N1",
}


class EvalCcAttritionExtraction(Extraction):
    id = "eval_cc_attrition"
    label = "Évaluation CC (attrition)"
    description = (
        "Évaluation mensuelle de l'activité et de l'attrition des comptes "
        "par agence/bureau, période N vs N-1."
    )
    icon = "📉"

    column_labels = LIBELLES_COLONNES
    montant_cols = _MONTANT_COLS
    date_cols = {"DATE_ARRETE"}
    total_cols = _MONTANT_COLS

    def render_form(self) -> Optional[EvalCcAttritionFilters]:
        # NB : pas de st.form ici — les menus Mutuelle/Agence/Bureau sont en
        # cascade et doivent se recalculer immédiatement quand on change un
        # choix, ce que st.form empêche (il ne rerun qu'à la soumission).

        try:
            dates_dispo = dates_arrete_eval_cc_cached()
        except Exception:  # noqa: BLE001
            dates_dispo = []
            st.warning(
                "Impossible de charger les dates d'arrêté disponibles "
                "(vérifie que le fichier .env est bien configuré et que le "
                "serveur a accès à la base)."
            )

        try:
            ref_localisation_df = referentiel_localisation_cached()
        except Exception:  # noqa: BLE001
            ref_localisation_df = pd.DataFrame(
                columns=[
                    "CODE_BUREAU", "LIBELLE_BUREAU",
                    "CODE_REGION", "LIB_REGION",
                    "CODE_MUTUELLE", "NOM_MUTUELLE",
                ]
            )
            st.warning(
                "Impossible de charger la liste des mutuelles/agences/bureaux "
                "depuis la base. Tu peux réessayer plus tard."
            )

        st.subheader("Critères de recherche")

        if dates_dispo:
            date_arrete = st.selectbox(
                "Date d'arrêté *",
                options=dates_dispo,
                index=0,  # la plus récente (liste triée du plus récent au plus ancien)
                format_func=lambda d: d.strftime("%d/%m/%Y"),
            )
        else:
            st.error(
                "Aucune date d'arrêté trouvée. Cette extraction ne peut "
                "pas être calculée pour le moment."
            )
            date_arrete = None

        with st.expander("Filtres avancés (facultatifs)"):
            st.caption("Localisation (Mutuelle → Agence → Bureau)")
            code_mutuelle, code_agence, code_bureau = render_localisation_cascade(
                ref_localisation_df, key_prefix="eval_cc_"
            )

        submitted = st.button("🔍 Générer l'évaluation CC", width="stretch", type="primary")

        if not submitted:
            return None

        filters = EvalCcAttritionFilters(
            date_arrete=date_arrete,
            code_mutuelle=code_mutuelle or None,
            code_agence=code_agence or None,
            code_bureau=code_bureau or None,
        )

        erreur = filters.validate()
        if erreur:
            st.error(erreur)
            return None
        return filters

    def execute(self, filters: EvalCcAttritionFilters) -> pd.DataFrame:
        return get_eval_cc_attrition(filters)

    def excel_filename(self, filters: EvalCcAttritionFilters) -> str:
        return f"eval_cc_attrition_{filters.date_arrete:%Y%m%d}.xlsx"

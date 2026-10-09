"""
Extraction : Suivi Épargne.

Suivi mensuel des encours et objectifs d'épargne par agence/bureau,
à partir de la vue SV_EPARGNE.

Champs obligatoires : Année et Mois (listes déroulantes, par défaut la
dernière année et le dernier mois disponibles). Filtres facultatifs :
localisation hiérarchique (Mutuelle -> Agence -> Bureau).

Les colonnes affichées reproduisent exactement la requête fournie par
l'utilisateur (ne pas en ajouter/retirer) : seule la clause des filtres
change selon ce qui est choisi dans le formulaire. Les noms de colonnes
source de la vue SV_EPARGNE sont reproduits tels quels (certains sont
entre guillemets et sensibles à la casse côté Oracle — ne pas les
modifier).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd
import streamlit as st

from db import fetch_df
from extractions.base import Extraction
from extractions.reference_data import (
    annees_mois_sv_epargne_cached,
    referentiel_localisation_cached,
    render_annee_mois,
    render_localisation_cascade,
)

# ---------------------------------------------------------------------------
# Filtres du formulaire
# ---------------------------------------------------------------------------


@dataclass
class SuiviEpargneFilters:
    annee: Optional[int]
    num_mois: Optional[int]
    code_mutuelle: Optional[str] = None
    code_agence: Optional[str] = None
    code_bureau: Optional[str] = None

    def validate(self) -> Optional[str]:
        if not self.annee or not self.num_mois:
            return "L'année et le mois sont obligatoires."
        return None


# ---------------------------------------------------------------------------
# Accès aux données
# ---------------------------------------------------------------------------

_BASE_SQL = """
    SELECT
        e.ANNEE, e.NUM_MOIS,
        e.CODE_REGION, e.LIB_REGION,
        e.CODE_BUREAU, e.LIBELLE_BUREAU,
        ROUND(e."enc_dav_init", 2)      AS ENC_DAV_INIT,
        ROUND(e."enc_dat_init", 2)      AS ENC_DAT_INIT,
        ROUND(e."enc_epj_init", 2)      AS ENC_EPJ_INIT,
        ROUND(e."enc_cc_init", 2)       AS ENC_CC_INIT,
        ROUND(e."enc_spec_init", 2)     AS ENC_SPEC_INIT,
        ROUND(e."enc_epo_init", 2)      AS ENC_EPO_INIT,
        ROUND(e."enc_epa_vol_init", 2)  AS ENC_EPA_VOL_INIT,
        ROUND(e."obj_dav", 2)           AS OBJ_DAV,
        ROUND(e."obj_dat", 2)           AS OBJ_DAT,
        ROUND(e."obj_epj", 2)           AS OBJ_EPJ,
        ROUND(e."Enc_crd", 2)           AS ENC_CRD,
        ROUND(e."Enc_cc", 2)            AS ENC_CC,
        ROUND(e."Enc_spec", 2)          AS ENC_SPEC,
        ROUND(e."Enc_dav", 2)           AS ENC_DAV,
        ROUND(e."Enc_dat", 2)           AS ENC_DAT,
        ROUND(e."Enc_epj", 2)           AS ENC_EPJ,
        ROUND(e."enc_epo", 2)           AS ENC_EPO,
        ROUND(e."Enc_epa_vol", 2)       AS ENC_EPA_VOL,
        ROUND(e."ecart_rea_dav", 2)     AS ECART_REA_DAV,
        ROUND(e."ecart_rea_dat", 2)     AS ECART_REA_DAT,
        ROUND(e."ecart_rea_epj", 2)     AS ECART_REA_EPJ,
        ROUND(e."ecart_rea_epa_vol", 2) AS ECART_REA_EPA_VOL,
        ROUND(e.OBJ_EPA, 2)             AS OBJ_EPA,
        ROUND(e."tx_couv", 4)           AS TX_COUV,
        ROUND(e."taux_att_dav", 4)      AS TAUX_ATT_DAV,
        ROUND(e."taux_att_dat", 4)      AS TAUX_ATT_DAT,
        ROUND(e."taux_att_epj", 4)      AS TAUX_ATT_EPJ,
        ROUND(e."taux_att_epa_vol", 4)  AS TAUX_ATT_EPA_VOL,
        ROUND(e.TAUX_COUV_DAT, 4)       AS TAUX_COUV_DAT,
        ROUND(e.TAUX_COUV_DAV, 4)       AS TAUX_COUV_DAV,
        ROUND(e.TAUX_COUV_EPJ, 4)       AS TAUX_COUV_EPJ,
        ROUND(e.TX_COUV_EP_VOL, 4)      AS TX_COUV_EP_VOL
    FROM sv_epargne e
    LEFT JOIN REGION r      ON r.CODE_REGION = e.CODE_REGION
    LEFT JOIN MUTUELLE mut  ON mut.CODE_MUTUELLE = r.CODE_MUTUELLE
    WHERE e.ANNEE = :annee AND e.NUM_MOIS = :num_mois
"""

_ORDER_SQL = " ORDER BY e.LIB_REGION, e.LIBELLE_BUREAU"

_COLONNES_FINALES = [
    "ANNEE",
    "NUM_MOIS",
    "CODE_REGION",
    "LIB_REGION",
    "CODE_BUREAU",
    "LIBELLE_BUREAU",
    "ENC_DAV_INIT",
    "ENC_DAT_INIT",
    "ENC_EPJ_INIT",
    "ENC_CC_INIT",
    "ENC_SPEC_INIT",
    "ENC_EPO_INIT",
    "ENC_EPA_VOL_INIT",
    "OBJ_DAV",
    "OBJ_DAT",
    "OBJ_EPJ",
    "ENC_CRD",
    "ENC_CC",
    "ENC_SPEC",
    "ENC_DAV",
    "ENC_DAT",
    "ENC_EPJ",
    "ENC_EPO",
    "ENC_EPA_VOL",
    "ECART_REA_DAV",
    "ECART_REA_DAT",
    "ECART_REA_EPJ",
    "ECART_REA_EPA_VOL",
    "OBJ_EPA",
    "TX_COUV",
    "TAUX_ATT_DAV",
    "TAUX_ATT_DAT",
    "TAUX_ATT_EPJ",
    "TAUX_ATT_EPA_VOL",
    "TAUX_COUV_DAT",
    "TAUX_COUV_DAV",
    "TAUX_COUV_EPJ",
    "TX_COUV_EP_VOL",
]


def get_suivi_epargne(filters: SuiviEpargneFilters) -> pd.DataFrame:
    """Construit et exécute la requête du suivi épargne pour l'année/mois choisis."""
    error = filters.validate()
    if error:
        raise ValueError(error)

    sql = _BASE_SQL
    params: dict = {
        "annee": filters.annee,
        "num_mois": filters.num_mois,
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
    "ANNEE": "Année",
    "NUM_MOIS": "Mois",
    "CODE_REGION": "Code agence",
    "LIB_REGION": "Agence",
    "CODE_BUREAU": "Code bureau",
    "LIBELLE_BUREAU": "Bureau",
    "ENC_DAV_INIT": "Encours DAV initial",
    "ENC_DAT_INIT": "Encours DAT initial",
    "ENC_EPJ_INIT": "Encours épargne projet initial",
    "ENC_CC_INIT": "Encours compte courant initial",
    "ENC_SPEC_INIT": "Encours épargne spéciale initial",
    "ENC_EPO_INIT": "Encours épargne obligatoire initial",
    "ENC_EPA_VOL_INIT": "Encours épargne volontaire initial",
    "OBJ_DAV": "Objectif DAV",
    "OBJ_DAT": "Objectif DAT",
    "OBJ_EPJ": "Objectif épargne projet",
    "ENC_CRD": "Encours créditeur",
    "ENC_CC": "Encours compte courant",
    "ENC_SPEC": "Encours épargne spéciale",
    "ENC_DAV": "Encours DAV",
    "ENC_DAT": "Encours DAT",
    "ENC_EPJ": "Encours épargne projet",
    "ENC_EPO": "Encours épargne obligatoire",
    "ENC_EPA_VOL": "Encours épargne volontaire",
    "ECART_REA_DAV": "Écart réalisation DAV",
    "ECART_REA_DAT": "Écart réalisation DAT",
    "ECART_REA_EPJ": "Écart réalisation épargne projet",
    "ECART_REA_EPA_VOL": "Écart réalisation épargne volontaire",
    "OBJ_EPA": "Objectif épargne",
    "TX_COUV": "Taux de couverture",
    "TAUX_ATT_DAV": "Taux d'atteinte DAV",
    "TAUX_ATT_DAT": "Taux d'atteinte DAT",
    "TAUX_ATT_EPJ": "Taux d'atteinte épargne projet",
    "TAUX_ATT_EPA_VOL": "Taux d'atteinte épargne volontaire",
    "TAUX_COUV_DAT": "Taux de couverture DAT",
    "TAUX_COUV_DAV": "Taux de couverture DAV",
    "TAUX_COUV_EPJ": "Taux de couverture épargne projet",
    "TX_COUV_EP_VOL": "Taux de couverture épargne volontaire",
}

_MONTANT_COLS = {
    "ENC_DAV_INIT", "ENC_DAT_INIT", "ENC_EPJ_INIT", "ENC_CC_INIT",
    "ENC_SPEC_INIT", "ENC_EPO_INIT", "ENC_EPA_VOL_INIT",
    "OBJ_DAV", "OBJ_DAT", "OBJ_EPJ",
    "ENC_CRD", "ENC_CC", "ENC_SPEC", "ENC_DAV", "ENC_DAT", "ENC_EPJ",
    "ENC_EPO", "ENC_EPA_VOL",
    "ECART_REA_DAV", "ECART_REA_DAT", "ECART_REA_EPJ", "ECART_REA_EPA_VOL",
    "OBJ_EPA",
}


class SuiviEpargneExtraction(Extraction):
    id = "suivi_epargne"
    label = "Suivi Épargne"
    description = "Suivi mensuel des encours et objectifs d'épargne par agence/bureau."
    icon = "📈"

    column_labels = LIBELLES_COLONNES
    montant_cols = _MONTANT_COLS
    date_cols: set[str] = set()
    total_cols = _MONTANT_COLS

    def render_form(self) -> Optional[SuiviEpargneFilters]:
        # NB : pas de st.form ici — les menus Année/Mois et
        # Mutuelle/Agence/Bureau sont en cascade et doivent se recalculer
        # immédiatement quand on change un choix, ce que st.form empêche
        # (il ne rerun qu'à la soumission).

        try:
            annees_mois = annees_mois_sv_epargne_cached()
        except Exception:  # noqa: BLE001
            annees_mois = []
            st.warning(
                "Impossible de charger les périodes (année/mois) disponibles "
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

        if annees_mois:
            annee, num_mois = render_annee_mois(annees_mois, key_prefix="se_")
        else:
            st.error(
                "Aucune période (année/mois) trouvée. Cette extraction ne "
                "peut pas être calculée pour le moment."
            )
            annee, num_mois = None, None

        with st.expander("Filtres avancés (facultatifs)"):
            st.caption("Localisation (Mutuelle → Agence → Bureau)")
            code_mutuelle, code_agence, code_bureau = render_localisation_cascade(
                ref_localisation_df, key_prefix="se_"
            )

        submitted = st.button("🔍 Générer le suivi épargne", width="stretch", type="primary")

        if not submitted:
            return None

        filters = SuiviEpargneFilters(
            annee=annee,
            num_mois=num_mois,
            code_mutuelle=code_mutuelle or None,
            code_agence=code_agence or None,
            code_bureau=code_bureau or None,
        )

        erreur = filters.validate()
        if erreur:
            st.error(erreur)
            return None
        return filters

    def execute(self, filters: SuiviEpargneFilters) -> pd.DataFrame:
        return get_suivi_epargne(filters)

    def excel_filename(self, filters: SuiviEpargneFilters) -> str:
        return f"suivi_epargne_{filters.annee}{filters.num_mois:02d}.xlsx"

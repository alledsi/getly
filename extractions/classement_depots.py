"""
Extractions : Plus gros déposants, Plus petits déposants.

Variantes du même classement (top 50 des clients par solde de dépôts
cumulé), à partir de la table de reporting RPT_ETAT_DEPOTS (déjà
pré-calculée en base, une ligne par compte de dépôt et par date
d'arrêté) — solde net par compte = solde créditeur - solde débiteur,
puis agrégé (somme) par client à la date d'arrêté choisie.

Les deux extractions ne diffèrent que par :
  - l'ordre du classement (décroissant pour les gros déposants, croissant
    pour les petits) ;
  - le seuil sur le solde cumulé (> 0 pour les gros, >= 1000 pour les
    petits, afin d'exclure les soldes résiduels quasi nuls du
    classement — même convention que `extractions/classement_encours.py`).

Le seuil s'applique sur le solde cumulé PAR CLIENT (après agrégation de
tous ses comptes de dépôts), pas compte par compte, et sans valeur
absolue : un client dont le cumul est négatif (en position débitrice
nette sur ses comptes de "dépôts") est exclu des deux classements plutôt
que de remonter en tête des "petits déposants" — ce n'est pas un
déposant, quel que soit le montant. (Un tel cas, s'il existe, relève
plutôt de l'extraction Comptes débiteurs.)

Champ obligatoire : date d'arrêté (liste déroulante des dates
disponibles dans RPT_ETAT_DEPOTS, la plus récente par défaut). Seul
filtre facultatif : localisation hiérarchique (Mutuelle -> Agence ->
Bureau) — pas de filtre par matricule client/compte ici, puisqu'il s'agit
d'un classement agrégé par client.
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
    dates_arrete_etat_depots_cached,
    referentiel_localisation_cached,
    render_localisation_cascade,
)

# ---------------------------------------------------------------------------
# Filtres du formulaire (communs aux 2 extractions)
# ---------------------------------------------------------------------------


@dataclass
class DepotsClassementFilters:
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


def _build_sql(ordre: str, seuil_operateur: str, seuil_valeur: int, filtres_localisation: str) -> str:
    return f"""
        WITH compte_solde AS (
            SELECT
                d.MATRICULE_CLIENT                                        AS matricule_client,
                d.PRENOM_CLIENT || ' ' || d.RAISON_SOCIALE_CLIENT         AS nom_client,
                (NVL(d.SLD_CREDITEUR, 0) - NVL(d.SLD_DEBITEUR, 0))        AS solde_net,
                d.CODE_MUTUELLE                                           AS code_mutuelle,
                mut.NOM_MUTUELLE                                          AS nom_mutuelle,
                d.CODE_AGENCE                                             AS code_agence,
                r.LIB_REGION                                              AS nom_agence,
                d.CODE_BUREAU                                             AS code_bureau,
                b.LIBELLE_BUREAU                                          AS nom_bureau
            FROM RPT_ETAT_DEPOTS d
            JOIN BUREAU b          ON b.CODE_BUREAU = d.CODE_BUREAU
            JOIN REGION r          ON r.CODE_REGION = d.CODE_AGENCE
            LEFT JOIN MUTUELLE mut ON mut.CODE_MUTUELLE = d.CODE_MUTUELLE
            WHERE d.DATE_ARRETE = :date_arrete
              AND d.MATRICULE_CLIENT IS NOT NULL
              {filtres_localisation}
        ),
        client_agg AS (
            SELECT
                matricule_client,
                MAX(nom_client)    AS nom_client,
                SUM(solde_net)     AS solde_cumule,
                MAX(code_bureau)   AS code_bureau,
                MAX(nom_bureau)    AS nom_bureau,
                MAX(code_agence)   AS code_agence,
                MAX(nom_agence)    AS nom_agence,
                MAX(code_mutuelle) AS code_mutuelle,
                MAX(nom_mutuelle)  AS nom_mutuelle
            FROM compte_solde
            GROUP BY matricule_client
            HAVING SUM(solde_net) {seuil_operateur} {seuil_valeur}
        ),
        client_rank AS (
            SELECT
                ca.*,
                ROW_NUMBER() OVER (ORDER BY solde_cumule {ordre}) AS rang
            FROM client_agg ca
        )
        SELECT
            matricule_client,
            nom_client,
            solde_cumule,
            code_bureau, nom_bureau,
            code_agence, nom_agence,
            code_mutuelle, nom_mutuelle,
            rang
        FROM client_rank
        WHERE rang <= 50
        ORDER BY rang
    """


_COLONNES_FINALES = [
    "MATRICULE_CLIENT",
    "NOM_CLIENT",
    "SOLDE_CUMULE",
    "CODE_BUREAU",
    "NOM_BUREAU",
    "CODE_AGENCE",
    "NOM_AGENCE",
    "CODE_MUTUELLE",
    "NOM_MUTUELLE",
    "RANG",
]


def get_classement_depots(
    filters: DepotsClassementFilters,
    *,
    ordre: str,
    seuil_operateur: str,
    seuil_valeur: int,
) -> pd.DataFrame:
    """Exécute le classement (top 50) des clients par solde de dépôts cumulé."""
    error = filters.validate()
    if error:
        raise ValueError(error)

    params: dict = {
        "date_arrete": dt.datetime.combine(filters.date_arrete, dt.time.min),
    }

    filtres_localisation = ""
    if filters.code_mutuelle:
        filtres_localisation += " AND d.CODE_MUTUELLE = :code_mutuelle"
        params["code_mutuelle"] = filters.code_mutuelle.strip()

    if filters.code_agence:
        filtres_localisation += " AND d.CODE_AGENCE = :code_agence"
        params["code_agence"] = filters.code_agence.strip()

    if filters.code_bureau:
        filtres_localisation += " AND d.CODE_BUREAU = :code_bureau"
        params["code_bureau"] = filters.code_bureau.strip()

    sql = _build_sql(ordre, seuil_operateur, seuil_valeur, filtres_localisation)

    df = fetch_df(sql, params)
    if df.empty:
        return pd.DataFrame(columns=_COLONNES_FINALES)
    return df[_COLONNES_FINALES]


# ---------------------------------------------------------------------------
# Formulaire Streamlit (partagé par les 2 extractions)
# ---------------------------------------------------------------------------


def _render_form_commun(titre_bouton: str, key_prefix: str) -> Optional[DepotsClassementFilters]:
    try:
        dates_dispo = dates_arrete_etat_depots_cached()
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
            key=f"{key_prefix}date_arrete",
        )
    else:
        st.error(
            "Aucune date d'arrêté trouvée. Cette extraction ne peut pas "
            "être calculée pour le moment."
        )
        date_arrete = None

    with st.expander("Filtres avancés (facultatifs)"):
        st.caption("Localisation (Mutuelle → Agence → Bureau)")
        code_mutuelle, code_agence, code_bureau = render_localisation_cascade(
            ref_localisation_df, key_prefix=key_prefix
        )

    submitted = st.button(titre_bouton, width="stretch", type="primary", key=f"{key_prefix}submit")

    if not submitted:
        return None

    filters = DepotsClassementFilters(
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


LIBELLES_COLONNES = {
    "MATRICULE_CLIENT": "Matricule client",
    "NOM_CLIENT": "Nom client",
    "SOLDE_CUMULE": "Solde cumulé",
    "CODE_BUREAU": "Code bureau",
    "NOM_BUREAU": "Bureau",
    "CODE_AGENCE": "Code agence",
    "NOM_AGENCE": "Agence",
    "CODE_MUTUELLE": "Code mutuelle",
    "NOM_MUTUELLE": "Mutuelle",
    "RANG": "Rang",
}


# ---------------------------------------------------------------------------
# Les 2 extractions
# ---------------------------------------------------------------------------


class PlusGrosDeposantsExtraction(Extraction):
    id = "plus_gros_deposants"
    label = "Plus gros déposants"
    description = (
        "Top 50 des clients par solde de dépôts cumulé à une date d'arrêté "
        "donnée, du plus élevé au plus faible."
    )
    icon = "💰"

    column_labels = LIBELLES_COLONNES
    montant_cols = {"SOLDE_CUMULE"}
    date_cols: set[str] = set()
    total_cols = {"SOLDE_CUMULE"}

    def render_form(self) -> Optional[DepotsClassementFilters]:
        return _render_form_commun("🔍 Générer le classement", key_prefix="gros_depos_")

    def execute(self, filters: DepotsClassementFilters) -> pd.DataFrame:
        return get_classement_depots(filters, ordre="DESC", seuil_operateur=">", seuil_valeur=0)

    def excel_filename(self, filters: DepotsClassementFilters) -> str:
        return f"plus_gros_deposants_{filters.date_arrete:%Y%m%d}.xlsx"


class PlusPetitsDeposantsExtraction(Extraction):
    id = "plus_petits_deposants"
    label = "Plus petits déposants"
    description = (
        "Top 50 des clients par solde de dépôts cumulé le plus faible (au moins "
        "1000 en valeur absolue), du plus faible au plus élevé."
    )
    icon = "🪙"

    column_labels = LIBELLES_COLONNES
    montant_cols = {"SOLDE_CUMULE"}
    date_cols: set[str] = set()
    total_cols = {"SOLDE_CUMULE"}

    def render_form(self) -> Optional[DepotsClassementFilters]:
        return _render_form_commun("🔍 Générer le classement", key_prefix="petits_depos_")

    def execute(self, filters: DepotsClassementFilters) -> pd.DataFrame:
        return get_classement_depots(filters, ordre="ASC", seuil_operateur=">=", seuil_valeur=1000)

    def excel_filename(self, filters: DepotsClassementFilters) -> str:
        return f"plus_petits_deposants_{filters.date_arrete:%Y%m%d}.xlsx"

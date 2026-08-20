"""
Extractions : Plus gros déposants, Plus petits déposants.

Variantes du même classement (top 50 des clients par solde de dépôts
cumulé, sur les comptes dont le compte général commence par "25"), basé
sur le même calcul que l'État des dépôts :

  solde par compte à la date d'arrêté = dernier solde clôturé connu
  (table SOLDE_ARRETE, sa date d'arrêté la plus récente) + mouvements de
  l'ECRITURE entre le lendemain de cette clôture et la date d'arrêté
  choisie (incluse) — puis agrégé (somme) par client.

Les deux extractions ne diffèrent que par :
  - l'ordre du classement (décroissant pour les gros déposants, croissant
    pour les petits) ;
  - le seuil sur le solde cumulé (> 0 pour les gros, >= 1000 en valeur
    absolue pour les petits, afin d'exclure les soldes résiduels quasi
    nuls du classement — même convention que
    `extractions/classement_encours.py`).

Champ obligatoire : date d'arrêté (doit être postérieure à la dernière
clôture connue dans SOLDE_ARRETE, comme pour l'État des dépôts). Seul
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
    derniere_date_arrete_cached,
    referentiel_localisation_cached,
    render_localisation_cascade,
)

# ---------------------------------------------------------------------------
# Filtres du formulaire (communs aux 2 extractions)
# ---------------------------------------------------------------------------


@dataclass
class DepotsClassementFilters:
    date_arrete: Optional[dt.date]
    derniere_cloture: Optional[dt.date]  # dernière date_arrete trouvée dans SOLDE_ARRETE
    code_mutuelle: Optional[str] = None
    code_agence: Optional[str] = None
    code_bureau: Optional[str] = None

    def validate(self) -> Optional[str]:
        if not self.date_arrete:
            return "La date d'arrêté est obligatoire."
        if self.derniere_cloture is None:
            return (
                "Aucune clôture de solde n'a été trouvée : "
                "impossible de calculer ce classement."
            )
        if self.date_arrete <= self.derniere_cloture:
            return (
                "La date d'arrêté doit être postérieure à la dernière clôture "
                f"disponible ({self.derniere_cloture:%d/%m/%Y})."
            )
        return None


# ---------------------------------------------------------------------------
# Accès aux données
# ---------------------------------------------------------------------------


def _build_sql(ordre: str, seuil_operateur: str, seuil_valeur: int, filtres_localisation: str) -> str:
    return f"""
        WITH solde_base AS (
            SELECT s.no_compte, s.solde_cloture
            FROM solde_arrete s
            WHERE s.date_arrete = (SELECT MAX(date_arrete) FROM solde_arrete)
        ),
        mouvements AS (
            SELECT
                e.no_compte,
                SUM(CASE WHEN e.sens_ecr = 'C' THEN e.mt_ecr ELSE 0 END)
              - SUM(CASE WHEN e.sens_ecr = 'D' THEN e.mt_ecr ELSE 0 END) AS mvt_net
            FROM ecriture e
            WHERE e.d_ecr >= :date_debut_mouvements
              AND e.d_ecr <  :date_fin_mouvements_exclusive
            GROUP BY e.no_compte
        ),
        compte_solde AS (
            SELECT
                c.MATRICULE_CLIENT                                       AS matricule_client,
                (NVL(sb.solde_cloture, 0) + NVL(mv.mvt_net, 0))          AS solde_net,
                mut.CODE_MUTUELLE                                        AS code_mutuelle,
                mut.NOM_MUTUELLE                                         AS nom_mutuelle,
                r.CODE_REGION                                            AS code_agence,
                r.LIB_REGION                                             AS nom_agence,
                c.CODE_BUREAU                                            AS code_bureau,
                b.LIBELLE_BUREAU                                         AS nom_bureau
            FROM COMPTE c
            JOIN BUREAU b          ON b.CODE_BUREAU = c.CODE_BUREAU
            JOIN REGION r          ON r.CODE_REGION = b.CODE_REGION
            LEFT JOIN MUTUELLE mut ON mut.CODE_MUTUELLE = r.CODE_MUTUELLE
            LEFT JOIN solde_base sb ON sb.no_compte = c.NO_COMPTE
            LEFT JOIN mouvements  mv ON mv.no_compte = c.NO_COMPTE
            WHERE c.COMPTE_GENERAL LIKE '25%'
              AND c.MATRICULE_CLIENT IS NOT NULL
              AND ABS(NVL(sb.solde_cloture, 0) + NVL(mv.mvt_net, 0)) {seuil_operateur} {seuil_valeur}
              {filtres_localisation}
        ),
        client_agg AS (
            SELECT
                matricule_client,
                SUM(solde_net)     AS solde_cumule,
                MAX(code_bureau)   AS code_bureau,
                MAX(nom_bureau)    AS nom_bureau,
                MAX(code_agence)   AS code_agence,
                MAX(nom_agence)    AS nom_agence,
                MAX(code_mutuelle) AS code_mutuelle,
                MAX(nom_mutuelle)  AS nom_mutuelle
            FROM compte_solde
            GROUP BY matricule_client
        ),
        client_rank AS (
            SELECT
                ca.*,
                ROW_NUMBER() OVER (ORDER BY solde_cumule {ordre}) AS rang
            FROM client_agg ca
        )
        SELECT
            cr.matricule_client,
            cl.prenom_client || ' ' || cl.raison_sociale_client AS nom_client,
            cr.solde_cumule,
            cr.code_bureau, cr.nom_bureau,
            cr.code_agence, cr.nom_agence,
            cr.code_mutuelle, cr.nom_mutuelle,
            cr.rang
        FROM client_rank cr
        JOIN client cl ON cl.matricule_client = cr.matricule_client
        WHERE cr.rang <= 50
        ORDER BY cr.rang
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

    date_debut_mouvements = filters.derniere_cloture + dt.timedelta(days=1)
    params: dict = {
        "date_debut_mouvements": dt.datetime.combine(date_debut_mouvements, dt.time.min),
        "date_fin_mouvements_exclusive": dt.datetime.combine(
            filters.date_arrete + dt.timedelta(days=1), dt.time.min
        ),
    }

    filtres_localisation = ""
    if filters.code_mutuelle:
        filtres_localisation += " AND mut.CODE_MUTUELLE = :code_mutuelle"
        params["code_mutuelle"] = filters.code_mutuelle.strip()

    if filters.code_agence:
        filtres_localisation += " AND r.CODE_REGION = :code_agence"
        params["code_agence"] = filters.code_agence.strip()

    if filters.code_bureau:
        filtres_localisation += " AND c.CODE_BUREAU = :code_bureau"
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
        derniere_cloture = derniere_date_arrete_cached()
    except Exception:  # noqa: BLE001
        derniere_cloture = None
        st.warning(
            "Impossible de charger la dernière clôture disponible "
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

    if derniere_cloture is not None:
        st.caption(
            f"Dernière clôture des soldes disponible : **{derniere_cloture:%d/%m/%Y}**. "
            f"Les mouvements sont comptés à partir du "
            f"**{derniere_cloture + dt.timedelta(days=1):%d/%m/%Y}** jusqu'à la date "
            f"d'arrêté choisie ci-dessous."
        )
        date_arrete = st.date_input(
            "Date d'arrêté *",
            value=derniere_cloture + dt.timedelta(days=1),
            min_value=derniere_cloture + dt.timedelta(days=1),
            key=f"{key_prefix}date_arrete",
        )
    else:
        st.error(
            "Aucune clôture de solde n'a été trouvée. "
            "Cette extraction ne peut pas être calculée pour le moment."
        )
        date_arrete = st.date_input("Date d'arrêté *", value=dt.date.today(), key=f"{key_prefix}date_arrete")

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
        derniere_cloture=derniere_cloture,
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
        "Top 50 des clients par solde de dépôts cumulé (dernière clôture connue "
        "+ mouvements jusqu'à la date d'arrêté choisie), du plus élevé au plus faible."
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

"""
Extraction : État des dépôts.

Situation des soldes de dépôts (comptes dont le compte général commence
par "25") à une date d'arrêté choisie par l'utilisateur :

  solde à la date d'arrêté = dernier solde clôturé connu (table
  SOLDE_ARRETE, sa date d'arrêté la plus récente) + mouvements de
  l'ECRITURE entre le lendemain de cette clôture et la date d'arrêté
  choisie (incluse).

Champ obligatoire : date d'arrêté (doit être postérieure à la dernière
clôture connue). Filtres facultatifs, en deux groupes :
  - identification du compte : matricule client, compte général,
    n° compte, code type compte, statut compte, et une case pour exclure
    les comptes à solde nul (débiteur et créditeur tous deux à 0)
  - localisation, hiérarchique (Mutuelle -> Agence -> Bureau), identique
    au Journal des écritures.
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
# Filtres du formulaire
# ---------------------------------------------------------------------------


@dataclass
class EtatDepotsFilters:
    date_arrete: dt.date
    derniere_cloture: Optional[dt.date]  # dernière date_arrete trouvée dans SOLDE_ARRETE
    matricule_client: Optional[str] = None
    compte_general: Optional[str] = None
    no_compte: Optional[str] = None
    code_type_compte: Optional[str] = None
    status_compte: Optional[str] = None
    exclure_soldes_nuls: bool = False
    code_mutuelle: Optional[str] = None
    code_agence: Optional[str] = None
    code_bureau: Optional[str] = None

    def validate(self) -> Optional[str]:
        if not self.date_arrete:
            return "La date d'arrêté est obligatoire."
        if self.derniere_cloture is None:
            return (
                "Aucune clôture de solde n'a été trouvée : "
                "impossible de calculer l'état des dépôts."
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

_BASE_SQL = """
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
    etat AS (
        SELECT
            mut.CODE_MUTUELLE                                        AS CODE_MUTUELLE,
            mut.NOM_MUTUELLE                                         AS NOM_MUTUELLE,
            r.CODE_REGION                                            AS CODE_AGENCE,
            r.LIB_REGION                                             AS NOM_AGENCE,
            c.CODE_BUREAU                                            AS CODE_BUREAU,
            b.LIBELLE_BUREAU                                         AS NOM_BUREAU,
            c.COMPTE_GENERAL                                         AS COMPTE_GENERAL,
            c.NO_COMPTE                                              AS NUMERO_COMPTE,
            c.CODE_TYPE_CPT                                          AS CODE_TYPE_COMPTE,
            c.MATRICULE_CLIENT                                       AS MATRICULE_CLIENT,
            cl.RAISON_SOCIALE_CLIENT                                 AS RAISON_SOCIALE_CLIENT,
            cl.PRENOM_CLIENT                                         AS PRENOM_CLIENT,
            CASE WHEN (NVL(sb.solde_cloture, 0) + NVL(mv.mvt_net, 0)) < 0
                 THEN ABS(NVL(sb.solde_cloture, 0) + NVL(mv.mvt_net, 0))
                 ELSE 0
            END                                                       AS SLD_DEBITEUR,
            CASE WHEN (NVL(sb.solde_cloture, 0) + NVL(mv.mvt_net, 0)) >= 0
                 THEN (NVL(sb.solde_cloture, 0) + NVL(mv.mvt_net, 0))
                 ELSE 0
            END                                                       AS SLD_CREDITEUR,
            :date_arrete_choisie                                     AS DATE_ARRETE,
            c.STATUS_COMPTE                                          AS STATUS_COMPTE
        FROM COMPTE c
        JOIN BUREAU b          ON b.CODE_BUREAU = c.CODE_BUREAU
        JOIN REGION r          ON r.CODE_REGION = b.CODE_REGION
        LEFT JOIN MUTUELLE mut ON mut.CODE_MUTUELLE = r.CODE_MUTUELLE
        LEFT JOIN CLIENT cl    ON cl.MATRICULE_CLIENT = c.MATRICULE_CLIENT
        LEFT JOIN solde_base sb ON sb.no_compte = c.NO_COMPTE
        LEFT JOIN mouvements  mv ON mv.no_compte = c.NO_COMPTE
        WHERE c.COMPTE_GENERAL LIKE '25%'
    )
    SELECT *
    FROM etat
    WHERE 1 = 1
"""

_ORDER_SQL = " ORDER BY CODE_AGENCE, CODE_BUREAU, NUMERO_COMPTE"

_COLONNES_FINALES = [
    "CODE_MUTUELLE",
    "NOM_MUTUELLE",
    "CODE_AGENCE",
    "NOM_AGENCE",
    "CODE_BUREAU",
    "NOM_BUREAU",
    "COMPTE_GENERAL",
    "NUMERO_COMPTE",
    "CODE_TYPE_COMPTE",
    "MATRICULE_CLIENT",
    "RAISON_SOCIALE_CLIENT",
    "PRENOM_CLIENT",
    "SLD_DEBITEUR",
    "SLD_CREDITEUR",
    "DATE_ARRETE",
    "STATUS_COMPTE",
]


def get_valeurs_compte_general() -> list[str]:
    """Comptes généraux distincts parmi les comptes de dépôts (compte général commençant par '25')."""
    df = fetch_df(
        "SELECT DISTINCT COMPTE_GENERAL FROM COMPTE "
        "WHERE COMPTE_GENERAL LIKE '25%' ORDER BY COMPTE_GENERAL"
    )
    return df["COMPTE_GENERAL"].dropna().tolist()


def get_valeurs_code_type_compte() -> list[str]:
    """Codes type de compte distincts parmi les comptes de dépôts."""
    df = fetch_df(
        "SELECT DISTINCT CODE_TYPE_CPT FROM COMPTE "
        "WHERE COMPTE_GENERAL LIKE '25%' AND CODE_TYPE_CPT IS NOT NULL "
        "ORDER BY CODE_TYPE_CPT"
    )
    return df["CODE_TYPE_CPT"].dropna().tolist()


def get_valeurs_status_compte() -> list[str]:
    """Statuts de compte distincts parmi les comptes de dépôts."""
    df = fetch_df(
        "SELECT DISTINCT STATUS_COMPTE FROM COMPTE "
        "WHERE COMPTE_GENERAL LIKE '25%' AND STATUS_COMPTE IS NOT NULL "
        "ORDER BY STATUS_COMPTE"
    )
    return df["STATUS_COMPTE"].dropna().tolist()


def get_etat_depots(filters: EtatDepotsFilters) -> pd.DataFrame:
    """
    Construit et exécute la requête de l'état des dépôts : dernier solde
    clôturé + mouvements du lendemain de cette clôture jusqu'à la date
    d'arrêté choisie (incluse), pour les comptes de dépôts (compte
    général commençant par "25").
    """
    error = filters.validate()
    if error:
        raise ValueError(error)

    sql = _BASE_SQL
    date_debut_mouvements = filters.derniere_cloture + dt.timedelta(days=1)
    params: dict = {
        "date_debut_mouvements": dt.datetime.combine(date_debut_mouvements, dt.time.min),
        "date_fin_mouvements_exclusive": dt.datetime.combine(
            filters.date_arrete + dt.timedelta(days=1), dt.time.min
        ),
        "date_arrete_choisie": dt.datetime.combine(filters.date_arrete, dt.time.min),
    }

    if filters.matricule_client:
        sql += " AND MATRICULE_CLIENT = :matricule_client"
        params["matricule_client"] = filters.matricule_client.strip()

    if filters.compte_general:
        sql += " AND COMPTE_GENERAL = :compte_general"
        params["compte_general"] = filters.compte_general.strip()

    if filters.no_compte:
        sql += " AND NUMERO_COMPTE = :no_compte"
        params["no_compte"] = filters.no_compte.strip()

    if filters.code_type_compte:
        sql += " AND CODE_TYPE_COMPTE = :code_type_compte"
        params["code_type_compte"] = filters.code_type_compte.strip()

    if filters.status_compte:
        sql += " AND STATUS_COMPTE = :status_compte"
        params["status_compte"] = filters.status_compte.strip()

    if filters.code_mutuelle:
        sql += " AND CODE_MUTUELLE = :code_mutuelle"
        params["code_mutuelle"] = filters.code_mutuelle.strip()

    if filters.code_agence:
        sql += " AND CODE_AGENCE = :code_agence"
        params["code_agence"] = filters.code_agence.strip()

    if filters.code_bureau:
        sql += " AND CODE_BUREAU = :code_bureau"
        params["code_bureau"] = filters.code_bureau.strip()

    if filters.exclure_soldes_nuls:
        sql += " AND NOT (SLD_DEBITEUR = 0 AND SLD_CREDITEUR = 0)"

    sql += _ORDER_SQL

    df = fetch_df(sql, params)
    if df.empty:
        return pd.DataFrame(columns=_COLONNES_FINALES)
    return df[_COLONNES_FINALES]


# ---------------------------------------------------------------------------
# Formulaire Streamlit
# ---------------------------------------------------------------------------


@st.cache_data(ttl=3600, show_spinner=False)
def _valeurs_compte_general_cached() -> list[str]:
    return get_valeurs_compte_general()


@st.cache_data(ttl=3600, show_spinner=False)
def _valeurs_code_type_compte_cached() -> list[str]:
    return get_valeurs_code_type_compte()


@st.cache_data(ttl=3600, show_spinner=False)
def _valeurs_status_compte_cached() -> list[str]:
    return get_valeurs_status_compte()


def _select_valeur(
    label: str,
    valeurs: list[str],
    placeholder: str,
    key: str,
    max_chars: Optional[int] = None,
) -> str:
    """Menu déroulant simple (sans libellé) à partir d'une liste de valeurs
    distinctes. Retombe sur un champ texte libre si la liste est vide."""
    if not valeurs:
        return st.text_input(label, max_chars=max_chars, key=f"{key}_txt") or ""
    choix = st.selectbox(label, options=valeurs, index=None, placeholder=placeholder, key=key)
    return choix or ""


LIBELLES_COLONNES = {
    "CODE_MUTUELLE": "Code mutuelle",
    "NOM_MUTUELLE": "Mutuelle",
    "CODE_AGENCE": "Code agence",
    "NOM_AGENCE": "Agence",
    "CODE_BUREAU": "Code bureau",
    "NOM_BUREAU": "Bureau",
    "COMPTE_GENERAL": "Compte général",
    "NUMERO_COMPTE": "N° compte",
    "CODE_TYPE_COMPTE": "Code type compte",
    "MATRICULE_CLIENT": "Matricule client",
    "RAISON_SOCIALE_CLIENT": "Raison sociale",
    "PRENOM_CLIENT": "Prénom client",
    "SLD_DEBITEUR": "Solde débiteur",
    "SLD_CREDITEUR": "Solde créditeur",
    "DATE_ARRETE": "Date arrêté",
    "STATUS_COMPTE": "Statut compte",
}


class EtatDepotsExtraction(Extraction):
    id = "etat_depots"
    label = "État des dépôts"
    description = (
        "Situation des soldes de dépôts par compte à une date d'arrêté : dernière "
        "clôture connue + mouvements jusqu'à la date choisie."
    )
    icon = "🏦"

    column_labels = LIBELLES_COLONNES
    montant_cols = {"SLD_DEBITEUR", "SLD_CREDITEUR"}
    date_cols = {"DATE_ARRETE"}
    total_cols = {"SLD_DEBITEUR", "SLD_CREDITEUR"}

    def render_form(self) -> Optional[EtatDepotsFilters]:
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
            valeurs_compte_general = _valeurs_compte_general_cached()
        except Exception:  # noqa: BLE001
            valeurs_compte_general = []

        try:
            valeurs_code_type_compte = _valeurs_code_type_compte_cached()
        except Exception:  # noqa: BLE001
            valeurs_code_type_compte = []

        try:
            valeurs_status_compte = _valeurs_status_compte_cached()
        except Exception:  # noqa: BLE001
            valeurs_status_compte = []

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
                "depuis la base. Tu peux saisir les codes manuellement dans "
                "les filtres avancés."
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
            )
        else:
            st.error(
                "Aucune clôture de solde n'a été trouvée. "
                "Cette extraction ne peut pas être calculée pour le moment."
            )
            date_arrete = st.date_input("Date d'arrêté *", value=dt.date.today())

        with st.expander("Filtres avancés (facultatifs)"):
            st.caption("Identification du compte")
            c1, c2, c3 = st.columns(3)
            with c1:
                matricule_client = st.text_input("Matricule client", max_chars=8)
                compte_general = _select_valeur(
                    "Compte général", valeurs_compte_general, "Tous", "compte_general", max_chars=10
                )
            with c2:
                no_compte = st.text_input("N° compte", max_chars=12)
                code_type_compte = _select_valeur(
                    "Code type compte", valeurs_code_type_compte, "Tous", "code_type_compte", max_chars=3
                )
            with c3:
                status_compte = _select_valeur(
                    "Statut compte", valeurs_status_compte, "Tous", "status_compte", max_chars=1
                )
                exclure_soldes_nuls = st.checkbox("Exclure les comptes à solde nul")

            st.caption("Localisation (Mutuelle → Agence → Bureau)")
            code_mutuelle, code_agence, code_bureau = render_localisation_cascade(
                ref_localisation_df, key_prefix="depots_"
            )

        submitted = st.button("🔍 Générer l'état des dépôts", width="stretch", type="primary")

        if not submitted:
            return None

        filters = EtatDepotsFilters(
            date_arrete=date_arrete,
            derniere_cloture=derniere_cloture,
            matricule_client=matricule_client or None,
            compte_general=compte_general or None,
            no_compte=no_compte or None,
            code_type_compte=code_type_compte or None,
            status_compte=status_compte or None,
            exclure_soldes_nuls=exclure_soldes_nuls,
            code_mutuelle=code_mutuelle or None,
            code_agence=code_agence or None,
            code_bureau=code_bureau or None,
        )

        erreur = filters.validate()
        if erreur:
            st.error(erreur)
            return None
        return filters

    def execute(self, filters: EtatDepotsFilters) -> pd.DataFrame:
        return get_etat_depots(filters)

    def excel_filename(self, filters: EtatDepotsFilters) -> str:
        return f"etat_depots_{filters.date_arrete:%Y%m%d}.xlsx"

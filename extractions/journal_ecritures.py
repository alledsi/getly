"""
Extraction : Journal des écritures.

Formulaire (code opération, date début, date fin obligatoires ;
matricule client, n° compte, bureau, agence, mutuelle, sens écriture
facultatifs) => journal des écritures comptables du core banking ACEP,
avec solde cumulé par compte. Toutes les lignes correspondantes sont
retournées, sans plafond.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import streamlit as st

from db import fetch_df
from extractions.base import Extraction

# ---------------------------------------------------------------------------
# Filtres du formulaire
# ---------------------------------------------------------------------------


@dataclass
class JournalFilters:
    code_operation: str
    date_debut: dt.date
    date_fin: dt.date
    matricule_client: Optional[str] = None
    no_compte: Optional[str] = None
    code_bureau: Optional[str] = None
    code_agence: Optional[str] = None
    code_mutuelle: Optional[str] = None
    sens_ecriture: Optional[str] = None

    def validate(self) -> Optional[str]:
        if not self.code_operation:
            return "Le code opération est obligatoire."
        if not self.date_debut or not self.date_fin:
            return "La date de début et la date de fin sont obligatoires."
        if self.date_debut > self.date_fin:
            return "La date de début doit être antérieure ou égale à la date de fin."
        return None


# ---------------------------------------------------------------------------
# Accès aux données
# ---------------------------------------------------------------------------

_BASE_SQL = """
    SELECT
        e.D_ECR              AS DATE_ECRITURE,
        e.D_VAL_ECR          AS DATE_VALEUR,
        e.NO_PIECE           AS NO_PIECE,
        e.JOURN_ECR          AS CODE_JOURNAL,
        e.CODE_OPER          AS CODE_OPERATION,
        o.LIB_OPER           AS LIBELLE_OPERATION,
        e.NO_COMPTE          AS NO_COMPTE,
        cpt.INTITULE_COMPTE  AS INTITULE_COMPTE,
        e.LIB_ECR            AS LIBELLE_ECRITURE,
        e.SENS_ECR           AS SENS_ECR,
        e.MT_ECR             AS MONTANT,
        cl.MATRICULE_CLIENT  AS MATRICULE_CLIENT,
        cl.RAISON_SOCIALE_CLIENT AS RAISON_SOCIALE_CLIENT,
        cl.PRENOM_CLIENT     AS PRENOM_CLIENT,
        b.CODE_BUREAU        AS CODE_BUREAU,
        b.LIBELLE_BUREAU     AS NOM_BUREAU,
        r.CODE_REGION        AS CODE_AGENCE,
        r.LIB_REGION         AS NOM_AGENCE,
        m.CODE_MUTUELLE      AS CODE_MUTUELLE,
        m.NOM_MUTUELLE       AS NOM_MUTUELLE,
        e.NO_ECR             AS NO_ECR
    FROM ECRITURE e
    LEFT JOIN COMPTE   cpt ON cpt.NO_COMPTE = e.NO_COMPTE
    LEFT JOIN CLIENT   cl  ON cl.MATRICULE_CLIENT = cpt.MATRICULE_CLIENT
    LEFT JOIN BUREAU   b   ON b.CODE_BUREAU = e.CODE_BUREAU
    LEFT JOIN REGION   r   ON r.CODE_REGION = b.CODE_REGION
    LEFT JOIN MUTUELLE m   ON m.CODE_MUTUELLE = r.CODE_MUTUELLE
    LEFT JOIN OPERATION o  ON o.CODE_OPER = e.CODE_OPER
    WHERE e.CODE_OPER = :code_operation
      AND e.D_ECR >= :date_debut
      AND e.D_ECR <  :date_fin_exclusive
"""

_ORDER_SQL = " ORDER BY e.NO_COMPTE, e.D_ECR, e.NO_ECR"

_COLONNES_FINALES = [
    "DATE_ECRITURE",
    "DATE_VALEUR",
    "NO_PIECE",
    "CODE_JOURNAL",
    "CODE_OPERATION",
    "LIBELLE_OPERATION",
    "NO_COMPTE",
    "INTITULE_COMPTE",
    "LIBELLE_ECRITURE",
    "DEBIT",
    "CREDIT",
    "SOLDE",
    "MATRICULE_CLIENT",
    "RAISON_SOCIALE_CLIENT",
    "PRENOM_CLIENT",
    "CODE_BUREAU",
    "NOM_BUREAU",
    "CODE_AGENCE",
    "NOM_AGENCE",
    "CODE_MUTUELLE",
    "NOM_MUTUELLE",
]


def get_operations() -> pd.DataFrame:
    """Liste des codes opération disponibles (table OPERATION), pour le menu déroulant."""
    sql = "SELECT CODE_OPER, LIB_OPER FROM OPERATION ORDER BY CODE_OPER"
    return fetch_df(sql)


def get_bureaux() -> pd.DataFrame:
    """Liste des bureaux disponibles (table BUREAU), pour le menu déroulant."""
    sql = "SELECT CODE_BUREAU, LIBELLE_BUREAU FROM BUREAU ORDER BY LIBELLE_BUREAU"
    return fetch_df(sql)


def get_agences() -> pd.DataFrame:
    """Liste des agences disponibles (table REGION), pour le menu déroulant."""
    sql = "SELECT CODE_REGION, LIB_REGION FROM REGION ORDER BY LIB_REGION"
    return fetch_df(sql)


def get_mutuelles() -> pd.DataFrame:
    """Liste des mutuelles disponibles (table MUTUELLE), pour le menu déroulant."""
    sql = "SELECT CODE_MUTUELLE, NOM_MUTUELLE FROM MUTUELLE ORDER BY NOM_MUTUELLE"
    return fetch_df(sql)


def get_journal(filters: JournalFilters) -> pd.DataFrame:
    """
    Construit et exécute la requête du journal des écritures selon les
    filtres du formulaire, puis calcule un solde cumulé (par compte, dans
    l'ordre chronologique) sur les lignes retournées.

    Le "solde" ainsi calculé est un solde de mouvement sur la période/le
    filtre sélectionné, pas le solde comptable total du compte (celui-ci
    dépendrait des écritures antérieures non incluses dans la recherche).
    """
    error = filters.validate()
    if error:
        raise ValueError(error)

    sql = _BASE_SQL
    params: dict = {
        "code_operation": filters.code_operation.strip(),
        "date_debut": dt.datetime.combine(filters.date_debut, dt.time.min),
        "date_fin_exclusive": dt.datetime.combine(
            filters.date_fin + dt.timedelta(days=1), dt.time.min
        ),
    }

    if filters.matricule_client:
        sql += " AND cl.MATRICULE_CLIENT = :matricule_client"
        params["matricule_client"] = filters.matricule_client.strip()

    if filters.no_compte:
        sql += " AND e.NO_COMPTE = :no_compte"
        params["no_compte"] = filters.no_compte.strip()

    if filters.code_bureau:
        sql += " AND b.CODE_BUREAU = :code_bureau"
        params["code_bureau"] = filters.code_bureau.strip()

    if filters.code_agence:
        sql += " AND r.CODE_REGION = :code_agence"
        params["code_agence"] = filters.code_agence.strip()

    if filters.code_mutuelle:
        sql += " AND m.CODE_MUTUELLE = :code_mutuelle"
        params["code_mutuelle"] = filters.code_mutuelle.strip()

    if filters.sens_ecriture:
        sql += " AND e.SENS_ECR = :sens_ecriture"
        params["sens_ecriture"] = filters.sens_ecriture.strip()

    sql += _ORDER_SQL

    df = fetch_df(sql, params)
    return _enrichir_journal(df)


def _enrichir_journal(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute les colonnes Débit / Crédit / Solde cumulé et met en forme."""
    if df.empty:
        for col in ("DEBIT", "CREDIT", "SOLDE"):
            df[col] = pd.Series(dtype="float64")
        return df[[c for c in _COLONNES_FINALES if c in df.columns]]

    df["DEBIT"] = df.apply(
        lambda row: row["MONTANT"] if str(row["SENS_ECR"]).strip().upper() == "D" else 0.0,
        axis=1,
    )
    df["CREDIT"] = df.apply(
        lambda row: row["MONTANT"] if str(row["SENS_ECR"]).strip().upper() == "C" else 0.0,
        axis=1,
    )

    df = df.sort_values(["NO_COMPTE", "DATE_ECRITURE", "NO_ECR"]).reset_index(drop=True)
    df["SOLDE"] = df.groupby("NO_COMPTE")["DEBIT"].cumsum() - df.groupby("NO_COMPTE")[
        "CREDIT"
    ].cumsum()

    return df[_COLONNES_FINALES]


# ---------------------------------------------------------------------------
# Formulaire Streamlit (mise en cache des listes de référence)
# ---------------------------------------------------------------------------


@st.cache_data(ttl=3600, show_spinner=False)
def _liste_operations_cached() -> pd.DataFrame:
    return get_operations()


@st.cache_data(ttl=3600, show_spinner=False)
def _liste_bureaux_cached() -> pd.DataFrame:
    return get_bureaux()


@st.cache_data(ttl=3600, show_spinner=False)
def _liste_agences_cached() -> pd.DataFrame:
    return get_agences()


@st.cache_data(ttl=3600, show_spinner=False)
def _liste_mutuelles_cached() -> pd.DataFrame:
    return get_mutuelles()


def _select_code_libelle(
    label: str,
    df: pd.DataFrame,
    code_col: str,
    libelle_col: str,
    placeholder: str,
    key: str,
    max_chars: Optional[int] = None,
) -> str:
    """
    Menu déroulant "CODE — Libellé" construit à partir d'un DataFrame de
    référence. Si la liste n'a pas pu être chargée, retombe sur un champ
    texte libre. Retourne le code sélectionné (chaîne vide si aucun choix).
    """
    if df.empty:
        return st.text_input(label, max_chars=max_chars, key=f"{key}_txt") or ""

    options = [f"{getattr(row, code_col)} — {getattr(row, libelle_col)}" for row in df.itertuples()]
    choix = st.selectbox(label, options=options, index=None, placeholder=placeholder, key=key)
    return choix.split(" — ")[0] if choix else ""


LIBELLES_COLONNES = {
    "DATE_ECRITURE": "Date écriture",
    "DATE_VALEUR": "Date valeur",
    "NO_PIECE": "N° pièce",
    "CODE_JOURNAL": "Code journal",
    "CODE_OPERATION": "Code opération",
    "LIBELLE_OPERATION": "Libellé opération",
    "NO_COMPTE": "N° compte",
    "INTITULE_COMPTE": "Intitulé compte",
    "LIBELLE_ECRITURE": "Libellé écriture",
    "DEBIT": "Débit",
    "CREDIT": "Crédit",
    "SOLDE": "Solde",
    "MATRICULE_CLIENT": "Matricule client",
    "RAISON_SOCIALE_CLIENT": "Raison sociale",
    "PRENOM_CLIENT": "Prénom client",
    "CODE_BUREAU": "Code bureau",
    "NOM_BUREAU": "Bureau",
    "CODE_AGENCE": "Code agence",
    "NOM_AGENCE": "Agence",
    "CODE_MUTUELLE": "Code mutuelle",
    "NOM_MUTUELLE": "Mutuelle",
}


class JournalEcrituresExtraction(Extraction):
    id = "journal_ecritures"
    label = "Journal des écritures"
    description = "Consultation et export du journal des écritures comptables du core banking."
    icon = "📒"

    column_labels = LIBELLES_COLONNES
    montant_cols = {"DEBIT", "CREDIT", "SOLDE"}
    date_cols = {"DATE_ECRITURE", "DATE_VALEUR"}
    total_cols = {"DEBIT", "CREDIT"}  # on ne totalise pas le solde (cumul), juste débit/crédit

    def render_form(self) -> Optional[JournalFilters]:
        avertissement = (
            "Impossible de charger cette liste depuis la base (vérifie que le "
            "fichier .env est bien configuré et que le serveur a accès à la "
            "base). Tu peux saisir la valeur manuellement ci-dessous."
        )

        try:
            operations_df = _liste_operations_cached()
        except Exception:  # noqa: BLE001
            operations_df = pd.DataFrame(columns=["CODE_OPER", "LIB_OPER"])
            st.warning(f"Codes opération : {avertissement}")

        try:
            bureaux_df = _liste_bureaux_cached()
        except Exception:  # noqa: BLE001
            bureaux_df = pd.DataFrame(columns=["CODE_BUREAU", "LIBELLE_BUREAU"])

        try:
            agences_df = _liste_agences_cached()
        except Exception:  # noqa: BLE001
            agences_df = pd.DataFrame(columns=["CODE_REGION", "LIB_REGION"])

        try:
            mutuelles_df = _liste_mutuelles_cached()
        except Exception:  # noqa: BLE001
            mutuelles_df = pd.DataFrame(columns=["CODE_MUTUELLE", "NOM_MUTUELLE"])

        with st.form("form_journal_ecritures"):
            st.subheader("Critères de recherche")

            col1, col2, col3 = st.columns(3)

            with col1:
                code_operation = _select_code_libelle(
                    "Code opération *",
                    operations_df,
                    "CODE_OPER",
                    "LIB_OPER",
                    "Sélectionner un code opération",
                    "code_operation",
                    max_chars=3,
                )

            with col2:
                date_debut = st.date_input(
                    "Date début *", value=dt.date.today() - dt.timedelta(days=30)
                )

            with col3:
                date_fin = st.date_input("Date fin *", value=dt.date.today())

            with st.expander("Filtres avancés (facultatifs)"):
                c1, c2, c3 = st.columns(3)
                with c1:
                    matricule_client = st.text_input("Matricule client")
                    no_compte = st.text_input("N° compte")
                with c2:
                    code_bureau = _select_code_libelle(
                        "Bureau", bureaux_df, "CODE_BUREAU", "LIBELLE_BUREAU", "Tous", "code_bureau"
                    )
                    code_agence = _select_code_libelle(
                        "Agence", agences_df, "CODE_REGION", "LIB_REGION", "Toutes", "code_agence"
                    )
                with c3:
                    code_mutuelle = _select_code_libelle(
                        "Mutuelle", mutuelles_df, "CODE_MUTUELLE", "NOM_MUTUELLE", "Toutes", "code_mutuelle"
                    )
                    choix_sens = st.selectbox(
                        "Sens écriture",
                        options=["D — Débit", "C — Crédit"],
                        index=None,
                        placeholder="Tous",
                        key="sens_ecriture",
                    )
                    sens_ecriture = choix_sens.split(" — ")[0] if choix_sens else ""

            submitted = st.form_submit_button(
                "🔍 Générer le journal", width="stretch"
            )

        if not submitted:
            return None

        filters = JournalFilters(
            code_operation=code_operation,
            date_debut=date_debut,
            date_fin=date_fin,
            matricule_client=matricule_client or None,
            no_compte=no_compte or None,
            code_bureau=code_bureau or None,
            code_agence=code_agence or None,
            code_mutuelle=code_mutuelle or None,
            sens_ecriture=sens_ecriture or None,
        )

        erreur = filters.validate()
        if erreur:
            st.error(erreur)
            return None
        return filters

    def execute(self, filters: JournalFilters) -> pd.DataFrame:
        return get_journal(filters)

    def excel_filename(self, filters: JournalFilters) -> str:
        return (
            f"journal_{filters.code_operation}_"
            f"{filters.date_debut:%Y%m%d}_{filters.date_fin:%Y%m%d}.xlsx"
        )

"""
Extraction : Journal des écritures.

Formulaire : un ou plusieurs codes opération, date début, date fin
obligatoires. Filtres avancés facultatifs, en deux groupes :
  - identification : matricule client, n° compte, sens écriture
  - localisation, hiérarchique (Mutuelle -> Agence -> Bureau) : choisir
    une mutuelle restreint les agences et bureaux proposés à cette
    mutuelle, choisir une agence restreint en plus les bureaux à cette
    agence.

=> journal des écritures comptables du core banking ACEP, avec solde
cumulé par compte. Toutes les lignes correspondantes sont retournées,
sans plafond.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import streamlit as st

from db import fetch_df
from extractions.base import Extraction
from extractions.reference_data import referentiel_localisation_cached, render_localisation_cascade

# ---------------------------------------------------------------------------
# Filtres du formulaire
# ---------------------------------------------------------------------------


@dataclass
class JournalFilters:
    code_operations: list[str]
    date_debut: dt.date
    date_fin: dt.date
    matricule_client: Optional[str] = None
    no_compte: Optional[str] = None
    sens_ecriture: Optional[str] = None
    code_mutuelle: Optional[str] = None
    code_agence: Optional[str] = None
    code_bureau: Optional[str] = None

    def validate(self) -> Optional[str]:
        if not self.code_operations:
            return "Au moins un code opération est obligatoire."
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
    WHERE e.D_ECR >= :date_debut
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
        "date_debut": dt.datetime.combine(filters.date_debut, dt.time.min),
        "date_fin_exclusive": dt.datetime.combine(
            filters.date_fin + dt.timedelta(days=1), dt.time.min
        ),
    }

    # Un ou plusieurs codes opération (IN)
    placeholders = ", ".join(f":cop_{i}" for i in range(len(filters.code_operations)))
    sql += f" AND e.CODE_OPER IN ({placeholders})"
    for i, code in enumerate(filters.code_operations):
        params[f"cop_{i}"] = code.strip()

    if filters.matricule_client:
        sql += " AND cl.MATRICULE_CLIENT = :matricule_client"
        params["matricule_client"] = filters.matricule_client.strip()

    if filters.no_compte:
        sql += " AND e.NO_COMPTE = :no_compte"
        params["no_compte"] = filters.no_compte.strip()

    if filters.sens_ecriture:
        sql += " AND e.SENS_ECR = :sens_ecriture"
        params["sens_ecriture"] = filters.sens_ecriture.strip()

    if filters.code_mutuelle:
        sql += " AND m.CODE_MUTUELLE = :code_mutuelle"
        params["code_mutuelle"] = filters.code_mutuelle.strip()

    if filters.code_agence:
        sql += " AND r.CODE_REGION = :code_agence"
        params["code_agence"] = filters.code_agence.strip()

    if filters.code_bureau:
        sql += " AND b.CODE_BUREAU = :code_bureau"
        params["code_bureau"] = filters.code_bureau.strip()

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
        # NB : pas de st.form ici — les menus Mutuelle/Agence/Bureau sont en
        # cascade et doivent se recalculer immédiatement quand on change un
        # choix, ce que st.form empêche (il ne rerun qu'à la soumission).

        try:
            operations_df = _liste_operations_cached()
        except Exception:  # noqa: BLE001
            operations_df = pd.DataFrame(columns=["CODE_OPER", "LIB_OPER"])
            st.warning(
                "Impossible de charger la liste des codes opération depuis la "
                "base (vérifie que le fichier .env est bien configuré et que "
                "le serveur a accès à la base). Tu peux saisir les codes "
                "manuellement ci-dessous, séparés par une virgule."
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
                "depuis la base. Tu peux saisir les codes manuellement dans "
                "les filtres avancés."
            )

        st.subheader("Critères de recherche")
        col1, col2, col3 = st.columns(3)

        with col1:
            if not operations_df.empty:
                options = [
                    f"{row.CODE_OPER} — {row.LIB_OPER}" for row in operations_df.itertuples()
                ]
                choix_ops = st.multiselect(
                    "Code(s) opération *",
                    options=options,
                    placeholder="Sélectionner un ou plusieurs codes opération",
                    key="code_operations",
                )
                code_operations = [c.split(" — ")[0] for c in choix_ops]
            else:
                saisie_ops = st.text_input(
                    "Code(s) opération * (séparés par une virgule)", key="code_operations_txt"
                )
                code_operations = [c.strip() for c in saisie_ops.split(",") if c.strip()]

        with col2:
            date_debut = st.date_input(
                "Date début *", value=dt.date.today() - dt.timedelta(days=30)
            )

        with col3:
            date_fin = st.date_input("Date fin *", value=dt.date.today())

        with st.expander("Filtres avancés (facultatifs)"):
            st.caption("Identification")
            c1, c2, c3 = st.columns(3)
            with c1:
                matricule_client = st.text_input("Matricule client")
            with c2:
                no_compte = st.text_input("N° compte")
            with c3:
                choix_sens = st.selectbox(
                    "Sens écriture",
                    options=["D — Débit", "C — Crédit"],
                    index=None,
                    placeholder="Tous",
                    key="sens_ecriture",
                )
                sens_ecriture = choix_sens.split(" — ")[0] if choix_sens else ""

            st.caption("Localisation (Mutuelle → Agence → Bureau)")
            code_mutuelle, code_agence, code_bureau = render_localisation_cascade(
                ref_localisation_df, key_prefix="journal_"
            )

        submitted = st.button("🔍 Générer le journal", width="stretch", type="primary")

        if not submitted:
            return None

        filters = JournalFilters(
            code_operations=code_operations,
            date_debut=date_debut,
            date_fin=date_fin,
            matricule_client=matricule_client or None,
            no_compte=no_compte or None,
            sens_ecriture=sens_ecriture or None,
            code_mutuelle=code_mutuelle or None,
            code_agence=code_agence or None,
            code_bureau=code_bureau or None,
        )

        erreur = filters.validate()
        if erreur:
            st.error(erreur)
            return None
        return filters

    def execute(self, filters: JournalFilters) -> pd.DataFrame:
        return get_journal(filters)

    def excel_filename(self, filters: JournalFilters) -> str:
        codes = filters.code_operations
        if len(codes) <= 3:
            codes_part = "-".join(codes)
        else:
            codes_part = "-".join(codes[:3]) + f"-et{len(codes) - 3}autres"
        return (
            f"journal_{codes_part}_"
            f"{filters.date_debut:%Y%m%d}_{filters.date_fin:%Y%m%d}.xlsx"
        )

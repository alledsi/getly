"""
Extraction : Opérations sur le crédit.

Écritures de décaissement et de remboursement liées à un dossier de prêt
(table ECRITURE), rattachées à leur prêt via le n° de dossier
(`NO_DOSSIER`, dont les positions 8-13 encodent le n° de prêt et la
position 16+ le n° d'échéance — lignes dont le n° de dossier ne respecte
pas ce format exclues via REGEXP_LIKE).

Règle métier reprise telle quelle de la requête fournie par
l'utilisateur : les codes opération 066/041/043/046/054 ne comptent que
pris en sens Crédit ('C' — décaissements), le code 131 ne compte que pris
en sens Débit ('D' — remboursements). Le filtre "Code(s) opération"
choisit lesquels de ces 6 codes inclure ; le sens associé à chacun reste
celui de la règle métier (non modifiable depuis le formulaire).

Champs obligatoires : au moins un code opération (choix multiple parmi
les 6 codes concernés), date début, date fin. Filtres facultatifs :
localisation hiérarchique (Mutuelle -> Agence -> Bureau), compte général,
matricule client, code type de compte (liste déroulante restreinte aux
seuls types concernés : 810, 811, 853, 323, 800).

Les colonnes affichées reproduisent exactement la requête fournie par
l'utilisateur (ne pas en ajouter/retirer) : seule la clause des filtres
change selon ce qui est choisi dans le formulaire.
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
    referentiel_localisation_cached,
    render_localisation_cascade,
    select_valeur,
)

# ---------------------------------------------------------------------------
# Codes opération concernés et règle de sens associée (métier, non
# modifiable depuis le formulaire — voir docstring du module)
# ---------------------------------------------------------------------------

_CODES_OPERATION_CREDIT = ("066", "041", "043", "046", "054")  # pris en sens 'C'
_CODE_OPERATION_REMBOURSEMENT = "131"  # pris en sens 'D'
_CODES_OPERATION_DISPONIBLES = list(_CODES_OPERATION_CREDIT) + [_CODE_OPERATION_REMBOURSEMENT]

_CODES_TYPE_COMPTE_DISPONIBLES = ["810", "811", "853", "323", "800"]

# ---------------------------------------------------------------------------
# Filtres du formulaire
# ---------------------------------------------------------------------------


@dataclass
class OperationsCreditFilters:
    code_operations: list[str]
    date_debut: dt.date
    date_fin: dt.date
    code_mutuelle: Optional[str] = None
    code_agence: Optional[str] = None
    code_bureau: Optional[str] = None
    compte_general: Optional[str] = None
    matricule_client: Optional[str] = None
    code_type_compte: Optional[str] = None

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


def _build_sql(condition_codes_sql: str, filtres_optionnels: str) -> str:
    return f"""
        WITH ecr AS (
            SELECT e.no_ecr, e.code_bureau, e.no_compte, e.code_oper, e.d_ecr, e.d_val_ecr,
                   e.lib_ecr, e.mt_ecr, e.sens_ecr, e.no_dossier,
                   TO_NUMBER(SUBSTR(e.no_dossier, 8, 6)) AS no_pret_dos,
                   TO_NUMBER(SUBSTR(e.no_dossier, 16))   AS no_echeance
            FROM ecriture e
            WHERE REGEXP_LIKE(SUBSTR(e.no_dossier, 8, 6), '^[0-9]{{6}}$')
              AND REGEXP_LIKE(SUBSTR(e.no_dossier, 16), '^[0-9]+$')
              AND e.d_ecr >= :date_debut
              AND e.d_ecr <  :date_fin_exclusive
              AND ({condition_codes_sql})
        )
        SELECT
            r.lib_region       AS "Agence",
            b.libelle_bureau   AS "Bureau",
            ecr.code_oper      AS "Code opération",
            p.matricule_client AS "Matricule",
            ecr.no_compte      AS "No compte",
            ecr.no_dossier     AS "No dossier",
            ecr.no_pret_dos    AS "Numero pret",
            ecr.no_echeance    AS "Echeance",
            ecr.d_ecr          AS "Date écriture",
            ecr.lib_ecr        AS "Lib écriture",
            ecr.mt_ecr         AS "Mt écriture",
            ecr.sens_ecr       AS "Sens écriture"
        FROM ecr
        JOIN pret p             ON p.no_pret = ecr.no_pret_dos AND p.code_bureau = ecr.code_bureau
        JOIN bureau b           ON b.code_bureau = ecr.code_bureau
        JOIN region r           ON r.code_region = b.code_region
        LEFT JOIN mutuelle mut  ON mut.code_mutuelle = r.code_mutuelle
        LEFT JOIN compte cpt    ON cpt.no_compte = ecr.no_compte
        WHERE 1 = 1
          {filtres_optionnels}
        ORDER BY ecr.no_pret_dos, ecr.no_echeance, ecr.d_ecr
    """


_COLONNES_FINALES = [
    "Agence",
    "Bureau",
    "Code opération",
    "Matricule",
    "No compte",
    "No dossier",
    "Numero pret",
    "Echeance",
    "Date écriture",
    "Lib écriture",
    "Mt écriture",
    "Sens écriture",
]


def get_operations_credit(filters: OperationsCreditFilters) -> pd.DataFrame:
    """Construit et exécute la requête des opérations sur le crédit selon
    les filtres du formulaire."""
    error = filters.validate()
    if error:
        raise ValueError(error)

    params: dict = {
        "date_debut": dt.datetime.combine(filters.date_debut, dt.time.min),
        "date_fin_exclusive": dt.datetime.combine(
            filters.date_fin + dt.timedelta(days=1), dt.time.min
        ),
    }

    # Règle métier : les codes 066/041/043/046/054 ne comptent qu'en sens
    # Crédit, le code 131 qu'en sens Débit (voir docstring du module). On
    # ne construit que les branches correspondant aux codes effectivement
    # sélectionnés par l'utilisateur.
    codes_credit_choisis = [c for c in filters.code_operations if c in _CODES_OPERATION_CREDIT]
    rembours_choisi = _CODE_OPERATION_REMBOURSEMENT in filters.code_operations

    branches = []
    if codes_credit_choisis:
        placeholders = ", ".join(f":cop_c_{i}" for i in range(len(codes_credit_choisis)))
        branches.append(f"(ecr.code_oper IN ({placeholders}) AND ecr.sens_ecr = 'C')")
        for i, code in enumerate(codes_credit_choisis):
            params[f"cop_c_{i}"] = code
    if rembours_choisi:
        branches.append("(ecr.code_oper = :cop_d AND ecr.sens_ecr = 'D')")
        params["cop_d"] = _CODE_OPERATION_REMBOURSEMENT
    condition_codes_sql = " OR ".join(branches)

    filtres_optionnels = ""
    if filters.code_mutuelle:
        filtres_optionnels += " AND mut.code_mutuelle = :code_mutuelle"
        params["code_mutuelle"] = filters.code_mutuelle.strip()

    if filters.code_agence:
        filtres_optionnels += " AND r.code_region = :code_agence"
        params["code_agence"] = filters.code_agence.strip()

    if filters.code_bureau:
        filtres_optionnels += " AND b.code_bureau = :code_bureau"
        params["code_bureau"] = filters.code_bureau.strip()

    if filters.compte_general:
        filtres_optionnels += " AND cpt.compte_general = :compte_general"
        params["compte_general"] = filters.compte_general.strip()

    if filters.matricule_client:
        filtres_optionnels += " AND p.matricule_client = :matricule_client"
        params["matricule_client"] = filters.matricule_client.strip()

    if filters.code_type_compte:
        filtres_optionnels += " AND cpt.code_type_cpt = :code_type_compte"
        params["code_type_compte"] = filters.code_type_compte.strip()

    sql = _build_sql(condition_codes_sql, filtres_optionnels)

    df = fetch_df(sql, params)
    if df.empty:
        return pd.DataFrame(columns=_COLONNES_FINALES)
    return df[_COLONNES_FINALES]


def get_operations_credit_libelles() -> pd.DataFrame:
    """Libellés (table OPERATION) des 6 codes opération concernés par
    cette extraction, pour le menu à choix multiple."""
    placeholders = ", ".join(f":c{i}" for i in range(len(_CODES_OPERATION_DISPONIBLES)))
    sql = f"SELECT CODE_OPER, LIB_OPER FROM OPERATION WHERE CODE_OPER IN ({placeholders})"
    params = {f"c{i}": code for i, code in enumerate(_CODES_OPERATION_DISPONIBLES)}
    df = fetch_df(sql, params)
    if df.empty:
        return df
    ordre = {code: i for i, code in enumerate(_CODES_OPERATION_DISPONIBLES)}
    df = df.copy()
    df["_ordre"] = df["CODE_OPER"].map(ordre)
    return df.sort_values("_ordre").drop(columns="_ordre").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Formulaire Streamlit
# ---------------------------------------------------------------------------


@st.cache_data(ttl=3600, show_spinner=False)
def _operations_credit_libelles_cached() -> pd.DataFrame:
    return get_operations_credit_libelles()


LIBELLES_COLONNES = {col: col for col in _COLONNES_FINALES}


class OperationsCreditExtraction(Extraction):
    id = "operations_credit"
    label = "Opérations sur le crédit"
    description = (
        "Écritures de décaissement (066/041/043/046/054, sens Crédit) et de "
        "remboursement (131, sens Débit) rattachées aux dossiers de prêt, sur "
        "une période donnée."
    )
    icon = "💸"

    column_labels = LIBELLES_COLONNES
    montant_cols = {"Mt écriture"}
    date_cols = {"Date écriture"}
    total_cols = {"Mt écriture"}

    def render_form(self) -> Optional[OperationsCreditFilters]:
        # NB : pas de st.form ici — les menus Mutuelle/Agence/Bureau sont en
        # cascade et doivent se recalculer immédiatement quand on change un
        # choix, ce que st.form empêche (il ne rerun qu'à la soumission).

        try:
            operations_df = _operations_credit_libelles_cached()
        except Exception:  # noqa: BLE001
            operations_df = pd.DataFrame(columns=["CODE_OPER", "LIB_OPER"])
            st.warning(
                "Impossible de charger les libellés des codes opération depuis "
                "la base (vérifie que le fichier .env est bien configuré et que "
                "le serveur a accès à la base). Les codes restent sélectionnables "
                "par leur numéro."
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
        col1, col2, col3 = st.columns(3)

        with col1:
            if not operations_df.empty:
                libelle_par_code = dict(
                    zip(operations_df["CODE_OPER"], operations_df["LIB_OPER"])
                )
                options = [
                    f"{code} — {libelle_par_code[code]}" if code in libelle_par_code else code
                    for code in _CODES_OPERATION_DISPONIBLES
                ]
            else:
                options = list(_CODES_OPERATION_DISPONIBLES)

            choix_ops = st.multiselect(
                "Code(s) opération *",
                options=options,
                placeholder="Sélectionner un ou plusieurs codes opération",
                key="opc_code_operations",
            )
            code_operations = [c.split(" — ")[0] for c in choix_ops]

        with col2:
            date_debut = st.date_input(
                "Date début *", value=dt.date.today() - dt.timedelta(days=30), key="opc_date_debut"
            )

        with col3:
            date_fin = st.date_input("Date fin *", value=dt.date.today(), key="opc_date_fin")

        with st.expander("Filtres avancés (facultatifs)"):
            st.caption("Identification")
            c1, c2, c3 = st.columns(3)
            with c1:
                compte_general = st.text_input("Compte général", key="opc_compte_general")
            with c2:
                matricule_client = st.text_input("Matricule client", key="opc_matricule_client")
            with c3:
                code_type_compte = select_valeur(
                    "Code type compte",
                    _CODES_TYPE_COMPTE_DISPONIBLES,
                    "Tous",
                    "opc_code_type_compte",
                    max_chars=3,
                )

            st.caption("Localisation (Mutuelle → Agence → Bureau)")
            code_mutuelle, code_agence, code_bureau = render_localisation_cascade(
                ref_localisation_df, key_prefix="opc_"
            )

        submitted = st.button(
            "🔍 Générer les opérations sur le crédit", width="stretch", type="primary"
        )

        if not submitted:
            return None

        filters = OperationsCreditFilters(
            code_operations=code_operations,
            date_debut=date_debut,
            date_fin=date_fin,
            code_mutuelle=code_mutuelle or None,
            code_agence=code_agence or None,
            code_bureau=code_bureau or None,
            compte_general=compte_general or None,
            matricule_client=matricule_client or None,
            code_type_compte=code_type_compte or None,
        )

        erreur = filters.validate()
        if erreur:
            st.error(erreur)
            return None
        return filters

    def execute(self, filters: OperationsCreditFilters) -> pd.DataFrame:
        return get_operations_credit(filters)

    def excel_filename(self, filters: OperationsCreditFilters) -> str:
        codes_part = "-".join(filters.code_operations)
        return (
            f"operations_credit_{codes_part}_"
            f"{filters.date_debut:%Y%m%d}_{filters.date_fin:%Y%m%d}.xlsx"
        )

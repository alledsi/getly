"""
Extraction : État des provisions.

Classement des encours en souffrance (ENC_BRUT) par tranche de retard
(3-6 mois / 6-12 mois / 12-24 mois, selon DUREE_IMP en jours : <180,
<360, >=360), avec le taux de provision associé (40% / 80% / 100%) et le
montant de provision calculé (solde capital × taux). Reprend telle quelle
la requête SQL fournie par l'utilisateur (CTE "det" + agrégation
ROLLUP) : chaque tranche affiche une ligne par client concerné ET une
ligne "TOTAL <tranche>" (sous-total de la tranche, produite directement
par le ROLLUP Oracle plutôt que recalculée côté application).

Champ obligatoire : date d'arrêté (liste déroulante des dates disponibles
dans ENC_BRUT, la plus récente pré-sélectionnée — comme pour la Balance
Agée et les classements d'encours). Filtres facultatifs : intitulé(s) de
provision (choix multiple parmi les 3 tranches), n° de compte, matricule
client, localisation hiérarchique (Mutuelle -> Agence -> Bureau).

Important : les lignes "TOTAL <tranche>" (sous-totaux ROLLUP) font partie
intégrante du résultat de la requête SQL elle-même, donc AUCUNE colonne
n'est déclarée dans `total_cols` ici (pas de ligne de total générique
ajoutée en bas du tableau/export Excel) — en ajouter une sommerait aussi
les lignes de sous-total déjà présentes, doublant les montants.

Les colonnes affichées reproduisent exactement la requête fournie par
l'utilisateur (ne pas en ajouter/retirer), accents et casse inclus.
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
    dates_arrete_enc_brut_cached,
    referentiel_localisation_cached,
    render_localisation_cascade,
)

# ---------------------------------------------------------------------------
# Intitulés de provision disponibles (fixes, dérivés de DUREE_IMP — pas une
# colonne de base à interroger)
# ---------------------------------------------------------------------------

_INTITULES_PROVISION_DISPONIBLES = [
    "PROVISION DE 3 A 6 MOIS",
    "PROVISION DE 6 A 12 MOIS",
    "PROVISION DE 12 A 24 MOIS",
]

# ---------------------------------------------------------------------------
# Filtres du formulaire
# ---------------------------------------------------------------------------


@dataclass
class EtatProvisionsFilters:
    date_arrete: Optional[dt.date]
    intitule_provision: Optional[list[str]] = None
    numero_compte: Optional[str] = None
    matricule_client: Optional[str] = None
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
    WITH det AS (
        SELECT
            CASE WHEN eb.DUREE_IMP <  180 THEN 1
                 WHEN eb.DUREE_IMP <  360 THEN 2
                 ELSE 3 END                                          AS ordre,
            CASE WHEN eb.DUREE_IMP <  180 THEN 'PROVISION DE 3 A 6 MOIS'
                 WHEN eb.DUREE_IMP <  360 THEN 'PROVISION DE 6 A 12 MOIS'
                 ELSE 'PROVISION DE 12 A 24 MOIS' END                AS intitule,
            CASE WHEN eb.DUREE_IMP <  180 THEN 40
                 WHEN eb.DUREE_IMP <  360 THEN 80
                 ELSE 100 END                                        AS taux,
            eb.MATRICULE_CLIENT                                      AS matricule,
            TRIM(NVL(cl.PRENOM_CLIENT,'') || ' ' || NVL(cl.RAISON_SOCIALE_CLIENT,'')) AS nom_client,
            eb.DATE_IMP                                              AS date_imp,
            NVL((SELECT MIN(c.NO_COMPTE)
                 FROM compte c
                 WHERE c.MATRICULE_CLIENT = eb.MATRICULE_CLIENT
                   AND c.CODE_BUREAU      = eb.CODE_BUREAU
                   AND c.CODE_TYPE_CPT    = CASE WHEN eb.DUREE_IMP < 180 THEN '271'
                                                 WHEN eb.DUREE_IMP < 360 THEN '272'
                                                 ELSE '223' END),
                p.NO_CPTCDL)                                         AS numero_compte,
            p.DATE_BASCUL_CTX                                        AS date_opp,
            NVL(eb.CAP_BASC,0)                                       AS cap_declasse,
            NVL(eb.ENCOURS_CAP,0)                                    AS solde_capital,
            eb.DUREE_IMP                                             AS duree_retard,
            eb.CODE_BUREAU                                           AS code_bureau
        FROM enc_brut eb
        JOIN pret p     ON p.NO_PRET = eb.NO_PRET AND p.CODE_BUREAU = eb.CODE_BUREAU
        JOIN client cl  ON cl.MATRICULE_CLIENT = eb.MATRICULE_CLIENT
                       AND cl.CODE_BUREAU      = eb.CODE_BUREAU
        WHERE eb.DATE_ARRETE = :date_arrete
          AND NVL(eb.ENCOURS_CAP,0) > 0
          AND eb.DUREE_IMP >= 90
          AND eb.DUREE_IMP <  720
    )
    SELECT
        intitule                                    AS "Intitulé Provision",
        taux / 100                                  AS "Taux de Provision",
        CASE WHEN GROUPING(matricule) = 1 THEN 'TOTAL ' || intitule ELSE matricule END AS "Matricule",
        MAX(nom_client)                             AS "Nom du client",
        MAX(date_imp)                               AS "Date Imp",
        MAX(numero_compte)                          AS "Numero compte",
        MAX(date_opp)                               AS "Date Opp",
        ROUND(SUM(cap_declasse), 2)                 AS "Cap. Déclassé",
        ROUND(SUM(solde_capital), 2)                AS "Solde Capital",
        MAX(duree_retard)                           AS "Durée Retard",
        ROUND(SUM(solde_capital * taux / 100), 2)   AS "Montant Provisions"
    FROM det
    LEFT JOIN bureau   b   ON b.code_bureau = det.code_bureau
    LEFT JOIN region   r   ON r.code_region = b.code_region
    LEFT JOIN mutuelle mut ON mut.code_mutuelle = r.code_mutuelle
    WHERE 1 = 1
      {filtres_optionnels}
    GROUP BY ordre, intitule, taux, ROLLUP ((matricule, nom_client, date_imp, numero_compte, date_opp, duree_retard))
    ORDER BY ordre, GROUPING(matricule), SUM(solde_capital) DESC
"""

_COLONNES_FINALES = [
    "Intitulé Provision",
    "Taux de Provision",
    "Matricule",
    "Nom du client",
    "Date Imp",
    "Numero compte",
    "Date Opp",
    "Cap. Déclassé",
    "Solde Capital",
    "Durée Retard",
    "Montant Provisions",
]


def get_etat_provisions(filters: EtatProvisionsFilters) -> pd.DataFrame:
    """Construit et exécute la requête de l'état des provisions à la date
    d'arrêté choisie."""
    error = filters.validate()
    if error:
        raise ValueError(error)

    params: dict = {
        "date_arrete": dt.datetime.combine(filters.date_arrete, dt.time.min),
    }

    filtres_optionnels = ""

    if filters.intitule_provision:
        placeholders = ", ".join(
            f":intitule_{i}" for i in range(len(filters.intitule_provision))
        )
        filtres_optionnels += f" AND det.intitule IN ({placeholders})"
        for i, valeur in enumerate(filters.intitule_provision):
            params[f"intitule_{i}"] = valeur

    if filters.numero_compte:
        filtres_optionnels += " AND det.numero_compte = :numero_compte"
        params["numero_compte"] = filters.numero_compte.strip()

    if filters.matricule_client:
        filtres_optionnels += " AND det.matricule = :matricule_client"
        params["matricule_client"] = filters.matricule_client.strip()

    if filters.code_mutuelle:
        filtres_optionnels += " AND mut.code_mutuelle = :code_mutuelle"
        params["code_mutuelle"] = filters.code_mutuelle.strip()

    if filters.code_agence:
        filtres_optionnels += " AND r.code_region = :code_agence"
        params["code_agence"] = filters.code_agence.strip()

    if filters.code_bureau:
        filtres_optionnels += " AND det.code_bureau = :code_bureau"
        params["code_bureau"] = filters.code_bureau.strip()

    sql = _BASE_SQL.format(filtres_optionnels=filtres_optionnels)

    df = fetch_df(sql, params)
    if df.empty:
        return pd.DataFrame(columns=_COLONNES_FINALES)
    return df[_COLONNES_FINALES]


# ---------------------------------------------------------------------------
# Formulaire Streamlit
# ---------------------------------------------------------------------------

LIBELLES_COLONNES = {col: col for col in _COLONNES_FINALES}


class EtatProvisionsExtraction(Extraction):
    id = "etat_provisions"
    label = "État des provisions"
    description = (
        "Encours en souffrance classés par tranche de retard (3-6, 6-12, 12-24 "
        "mois) avec le taux et le montant de provision associés, à une date "
        "d'arrêté donnée."
    )
    icon = "🧮"

    column_labels = LIBELLES_COLONNES
    montant_cols = {"Taux de Provision", "Cap. Déclassé", "Solde Capital", "Montant Provisions"}
    date_cols = {"Date Imp", "Date Opp"}
    # Volontairement vide : les lignes "TOTAL <tranche>" (sous-totaux) sont
    # déjà produites par le ROLLUP de la requête SQL elle-même — une ligne
    # de total générique en plus doublerait les montants.
    total_cols: set[str] = set()

    def render_form(self) -> Optional[EtatProvisionsFilters]:
        # NB : pas de st.form ici — les menus Mutuelle/Agence/Bureau sont en
        # cascade et doivent se recalculer immédiatement quand on change un
        # choix, ce que st.form empêche (il ne rerun qu'à la soumission).

        try:
            dates_dispo = dates_arrete_enc_brut_cached()
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
                key="ep_date_arrete",
            )
        else:
            st.error(
                "Aucune date d'arrêté trouvée. Cette extraction ne peut pas "
                "être calculée pour le moment."
            )
            date_arrete = None

        with st.expander("Filtres avancés (facultatifs)"):
            st.caption("Identification")
            c1, c2, c3 = st.columns(3)
            with c1:
                intitule_provision = st.multiselect(
                    "Intitulé(s) provision",
                    options=_INTITULES_PROVISION_DISPONIBLES,
                    placeholder="Tous",
                    key="ep_intitule_provision",
                )
            with c2:
                numero_compte = st.text_input("N° compte", key="ep_numero_compte")
            with c3:
                matricule_client = st.text_input("Matricule client", key="ep_matricule_client")

            st.caption("Localisation (Mutuelle → Agence → Bureau)")
            code_mutuelle, code_agence, code_bureau = render_localisation_cascade(
                ref_localisation_df, key_prefix="ep_"
            )

        submitted = st.button(
            "🔍 Générer l'état des provisions", width="stretch", type="primary"
        )

        if not submitted:
            return None

        filters = EtatProvisionsFilters(
            date_arrete=date_arrete,
            intitule_provision=intitule_provision or None,
            numero_compte=numero_compte or None,
            matricule_client=matricule_client or None,
            code_mutuelle=code_mutuelle or None,
            code_agence=code_agence or None,
            code_bureau=code_bureau or None,
        )

        erreur = filters.validate()
        if erreur:
            st.error(erreur)
            return None
        return filters

    def execute(self, filters: EtatProvisionsFilters) -> pd.DataFrame:
        return get_etat_provisions(filters)

    def excel_filename(self, filters: EtatProvisionsFilters) -> str:
        return f"etat_provisions_{filters.date_arrete:%Y%m%d}.xlsx"

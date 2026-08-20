"""
Extraction : Balance Agée.

Détail des prêts en cours (un prêt par ligne) à une date d'arrêté choisie
(table ENC_BRUT), avec les caractéristiques du prêt, du client, des
retards par tranche d'ancienneté (29/30/60/90/180/360/720 jours) et de la
garantie associée.

Champ obligatoire : date d'arrêté (liste déroulante des dates disponibles
dans ENC_BRUT, la plus récente par défaut). Filtres facultatifs : genre,
ressource affectée, matricule client, n° prêt, secteur d'activité, classe
d'âge, et localisation hiérarchique (Mutuelle -> Agence -> Bureau).
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
    select_code_libelle,
)

# ---------------------------------------------------------------------------
# Filtres du formulaire
# ---------------------------------------------------------------------------


@dataclass
class BalanceAgeeFilters:
    date_arrete: Optional[dt.date]
    genre: Optional[str] = None
    ressource_aff: Optional[str] = None
    matricule_client: Optional[str] = None
    no_pret: Optional[str] = None
    code_sect: Optional[str] = None
    classe_age: Optional[str] = None
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
    WITH garantie_agg AS (
        SELECT
            g.no_pret,
            g.matricule_client,
            LISTAGG(tg.int_type_gar, ', ') WITHIN GROUP (ORDER BY tg.int_type_gar) AS DESC_GARANTIE,
            SUM(g.valeur_gar) AS VALEUR_GARANTIE
        FROM garanties g
        JOIN type_garantie tg ON tg.code_type_gar = g.code_type_gar
        GROUP BY g.no_pret, g.matricule_client
    )
    SELECT
        mutuelle.code_mutuelle           AS CODE_MUTUELLE,
        mutuelle.nom_mutuelle            AS NOM_MUTUELLE,
        bureau.code_region               AS CODE_REGION,
        region.lib_region                AS LIB_REGION,
        enc_brut.code_bureau             AS CODE_BUREAU,
        bureau.libelle_bureau            AS LIBELLE_BUREAU,
        enc_brut.matricule_client        AS MATRICULE_CLIENT,
        client.prenom_client || '  ' || client.raison_sociale_client AS NOM_CLIENT,
        enc_brut.genre                   AS GENRE,
        enc_brut.age_cli                 AS AGE_CLI,
        enc_brut.classe_age              AS CLASSE_AGE,
        enc_brut.anciennete              AS ANCIENNETE,
        enc_brut.no_pret                 AS NO_PRET,
        type_pret.int_type_pret          AS INT_TYPE_PRET,
        enc_brut.taille_pret             AS TAILLE_PRET,
        enc_brut.libelle_cycle           AS LIBELLE_CYCLE,
        pret.d_mep_pret                  AS D_MEP_PRET,
        (pret.d_der_ech - pret.d_mep_pret)                        AS DUREE_JOURS,
        ROUND(MONTHS_BETWEEN(pret.d_der_ech, pret.d_mep_pret))    AS DUREE_MOIS,
        pret.mt_pret_cap                 AS MT_CAPITAL_PRET,
        pret.frais_actes                 AS FRAIS_ACTES,
        pret.mt_fraidos                  AS MT_FRAIDOS,
        pret.assur_agricole              AS ASSUR_AGRICOLE,
        pret.mt_pret_int                 AS MT_PRET_INT,
        pret.mt_int_cap                  AS MT_INT_CAPITALISE,
        pret.tx_int_pret                 AS TX_INT_PRET,
        pret.mt_ech_pret                 AS MT_ECH_PRET,
        pret.period_ech                  AS PERIOD_ECH,
        pret.nb_ech_pret                 AS NB_ECH_PRET,
        pret.d_prem_ech                  AS D_PREM_ECH,
        pret.d_der_ech                   AS D_DER_ECH,
        enc_brut.encours_cap             AS ENCOURS_CAP,
        enc_brut.impaye_cap              AS IMPAYE_CAP,
        enc_brut.mt_impaye               AS MT_IMPAYE,
        enc_brut.duree_imp               AS DUREE_IMP,
        enc_brut.crd_jour                AS CRD_JOUR,
        enc_brut.par_29                  AS RETARD_29,
        enc_brut.par_30                  AS RETARD_30,
        enc_brut.par_60                  AS RETARD_60,
        enc_brut.par_90                  AS RETARD_90,
        enc_brut.par_180                 AS RETARD_180,
        enc_brut.par_360                 AS RETARD_360,
        enc_brut.par_720                 AS RETARD_720,
        enc_brut.cycle_pret              AS CYCLE_PRET,
        sous_secteur.code_sect           AS CODE_SECT,
        secteur.lib_sect                 AS LIB_SECT,
        sous_secteur.lib_ssect           AS LIB_SSECT,
        type_pret.ressource_aff          AS RESSOURCE_AFF,
        categorie.int_categorie          AS INT_CATEGORIE,
        NVL(client.nb_mas, 0)            AS NB_HOMMES,
        NVL(client.nb_fem, 0)            AS NB_FEMMES,
        garantie_agg.DESC_GARANTIE       AS DESC_GARANTIE,
        garantie_agg.VALEUR_GARANTIE     AS VALEUR_GARANTIE
    FROM
        enc_brut,
        client,
        pret,
        region,
        bureau,
        type_pret,
        sous_secteur,
        region_operat,
        secteur,
        categorie,
        garantie_agg,
        mutuelle
    WHERE
        enc_brut.no_pret          = pret.no_pret
        AND enc_brut.code_bureau  = pret.code_bureau
        AND enc_brut.matricule_client = client.matricule_client
        AND enc_brut.code_bureau  = client.code_bureau
        AND client.matricule_client   = pret.matricule_client
        AND bureau.code_region_operat = region_operat.code_region_operat
        AND pret.code_type_pret   = type_pret.code_type_pret
        AND client.code_bureau    = pret.code_bureau
        AND region.code_region    = bureau.code_region
        AND bureau.code_bureau    = client.code_bureau
        AND enc_brut.code_ssect   = sous_secteur.code_ssect
        AND secteur.code_sect     = sous_secteur.code_sect
        AND client.code_categorie = categorie.code_categorie
        AND enc_brut.no_pret          = garantie_agg.no_pret (+)
        AND enc_brut.matricule_client = garantie_agg.matricule_client (+)
        AND region.code_mutuelle      = mutuelle.code_mutuelle (+)
        AND ABS(enc_brut.encours_cap) > 0
        AND (enc_brut.enc_perte = 0 OR enc_brut.enc_perte IS NULL)
        AND enc_brut.date_arrete = :date_arrete
"""

_ORDER_SQL = " ORDER BY enc_brut.code_bureau, enc_brut.no_pret"

_COLONNES_FINALES = [
    "CODE_MUTUELLE", "NOM_MUTUELLE",
    "CODE_REGION", "LIB_REGION",
    "CODE_BUREAU", "LIBELLE_BUREAU",
    "MATRICULE_CLIENT", "NOM_CLIENT",
    "GENRE", "AGE_CLI", "CLASSE_AGE", "ANCIENNETE",
    "NO_PRET", "INT_TYPE_PRET", "TAILLE_PRET", "LIBELLE_CYCLE",
    "D_MEP_PRET", "DUREE_JOURS", "DUREE_MOIS",
    "MT_CAPITAL_PRET", "FRAIS_ACTES", "MT_FRAIDOS", "ASSUR_AGRICOLE",
    "MT_PRET_INT", "MT_INT_CAPITALISE", "TX_INT_PRET",
    "MT_ECH_PRET", "PERIOD_ECH", "NB_ECH_PRET", "D_PREM_ECH", "D_DER_ECH",
    "ENCOURS_CAP", "IMPAYE_CAP", "MT_IMPAYE", "DUREE_IMP", "CRD_JOUR",
    "RETARD_29", "RETARD_30", "RETARD_60", "RETARD_90",
    "RETARD_180", "RETARD_360", "RETARD_720",
    "CYCLE_PRET",
    "CODE_SECT", "LIB_SECT", "LIB_SSECT",
    "RESSOURCE_AFF", "INT_CATEGORIE",
    "NB_HOMMES", "NB_FEMMES",
    "DESC_GARANTIE", "VALEUR_GARANTIE",
]


def get_valeurs_genre() -> list[str]:
    df = fetch_df("SELECT DISTINCT GENRE FROM ENC_BRUT WHERE GENRE IS NOT NULL ORDER BY GENRE")
    return df["GENRE"].dropna().tolist()


def get_valeurs_ressource_aff() -> list[str]:
    df = fetch_df(
        "SELECT DISTINCT RESSOURCE_AFF FROM TYPE_PRET "
        "WHERE RESSOURCE_AFF IS NOT NULL ORDER BY RESSOURCE_AFF"
    )
    return df["RESSOURCE_AFF"].dropna().tolist()


def get_valeurs_classe_age() -> list[str]:
    df = fetch_df(
        "SELECT DISTINCT CLASSE_AGE FROM ENC_BRUT WHERE CLASSE_AGE IS NOT NULL ORDER BY CLASSE_AGE"
    )
    return df["CLASSE_AGE"].dropna().tolist()


def get_secteurs() -> pd.DataFrame:
    return fetch_df("SELECT CODE_SECT, LIB_SECT FROM SECTEUR ORDER BY LIB_SECT")


def get_balance_agee(filters: BalanceAgeeFilters) -> pd.DataFrame:
    """Construit et exécute la requête de la Balance Agée à la date d'arrêté choisie."""
    error = filters.validate()
    if error:
        raise ValueError(error)

    sql = _BASE_SQL
    params: dict = {
        "date_arrete": dt.datetime.combine(filters.date_arrete, dt.time.min),
    }

    if filters.genre:
        sql += " AND enc_brut.genre = :genre"
        params["genre"] = filters.genre.strip()

    if filters.ressource_aff:
        sql += " AND type_pret.ressource_aff = :ressource_aff"
        params["ressource_aff"] = filters.ressource_aff.strip()

    if filters.matricule_client:
        sql += " AND enc_brut.matricule_client = :matricule_client"
        params["matricule_client"] = filters.matricule_client.strip()

    if filters.no_pret:
        sql += " AND enc_brut.no_pret = :no_pret"
        params["no_pret"] = filters.no_pret.strip()

    if filters.code_sect:
        sql += " AND secteur.code_sect = :code_sect"
        params["code_sect"] = filters.code_sect.strip()

    if filters.classe_age:
        sql += " AND enc_brut.classe_age = :classe_age"
        params["classe_age"] = filters.classe_age.strip()

    if filters.code_mutuelle:
        sql += " AND mutuelle.code_mutuelle = :code_mutuelle"
        params["code_mutuelle"] = filters.code_mutuelle.strip()

    if filters.code_agence:
        sql += " AND region.code_region = :code_agence"
        params["code_agence"] = filters.code_agence.strip()

    if filters.code_bureau:
        sql += " AND enc_brut.code_bureau = :code_bureau"
        params["code_bureau"] = filters.code_bureau.strip()

    sql += _ORDER_SQL

    df = fetch_df(sql, params)
    if df.empty:
        return pd.DataFrame(columns=_COLONNES_FINALES)
    return df[_COLONNES_FINALES]


# ---------------------------------------------------------------------------
# Formulaire Streamlit
# ---------------------------------------------------------------------------


@st.cache_data(ttl=3600, show_spinner=False)
def _valeurs_genre_cached() -> list[str]:
    return get_valeurs_genre()


@st.cache_data(ttl=3600, show_spinner=False)
def _valeurs_ressource_aff_cached() -> list[str]:
    return get_valeurs_ressource_aff()


@st.cache_data(ttl=3600, show_spinner=False)
def _valeurs_classe_age_cached() -> list[str]:
    return get_valeurs_classe_age()


@st.cache_data(ttl=3600, show_spinner=False)
def _secteurs_cached() -> pd.DataFrame:
    return get_secteurs()


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
    "CODE_REGION": "Code agence",
    "LIB_REGION": "Agence",
    "CODE_BUREAU": "Code bureau",
    "LIBELLE_BUREAU": "Bureau",
    "MATRICULE_CLIENT": "Matricule client",
    "NOM_CLIENT": "Nom client",
    "GENRE": "Genre",
    "AGE_CLI": "Âge",
    "CLASSE_AGE": "Classe d'âge",
    "ANCIENNETE": "Ancienneté",
    "NO_PRET": "N° prêt",
    "INT_TYPE_PRET": "Type de prêt",
    "TAILLE_PRET": "Taille du prêt",
    "LIBELLE_CYCLE": "Cycle",
    "D_MEP_PRET": "Date mise en place",
    "DUREE_JOURS": "Durée (jours)",
    "DUREE_MOIS": "Durée (mois)",
    "MT_CAPITAL_PRET": "Montant capital prêté",
    "FRAIS_ACTES": "Frais d'actes",
    "MT_FRAIDOS": "Montant frais de dossier",
    "ASSUR_AGRICOLE": "Assurance agricole",
    "MT_PRET_INT": "Montant intérêt prêt",
    "MT_INT_CAPITALISE": "Intérêt capitalisé",
    "TX_INT_PRET": "Taux d'intérêt",
    "MT_ECH_PRET": "Montant échéance",
    "PERIOD_ECH": "Périodicité échéance",
    "NB_ECH_PRET": "Nombre d'échéances",
    "D_PREM_ECH": "Date première échéance",
    "D_DER_ECH": "Date dernière échéance",
    "ENCOURS_CAP": "Encours capital",
    "IMPAYE_CAP": "Impayé capital",
    "MT_IMPAYE": "Montant impayé",
    "DUREE_IMP": "Durée impayé",
    "CRD_JOUR": "Crédit jour",
    "RETARD_29": "Retard 29j",
    "RETARD_30": "Retard 30j",
    "RETARD_60": "Retard 60j",
    "RETARD_90": "Retard 90j",
    "RETARD_180": "Retard 180j",
    "RETARD_360": "Retard 360j",
    "RETARD_720": "Retard 720j",
    "CYCLE_PRET": "Cycle prêt",
    "CODE_SECT": "Code secteur",
    "LIB_SECT": "Secteur d'activité",
    "LIB_SSECT": "Sous-secteur d'activité",
    "RESSOURCE_AFF": "Ressource affectée",
    "INT_CATEGORIE": "Catégorie",
    "NB_HOMMES": "Nombre d'hommes",
    "NB_FEMMES": "Nombre de femmes",
    "DESC_GARANTIE": "Garantie(s)",
    "VALEUR_GARANTIE": "Valeur garantie",
}


class BalanceAgeeExtraction(Extraction):
    id = "balance_agee"
    label = "Balance Agée"
    description = (
        "Détail des prêts en cours à une date d'arrêté donnée, avec les "
        "caractéristiques du prêt, du client, des retards par tranche et de "
        "la garantie associée."
    )
    icon = "📋"

    column_labels = LIBELLES_COLONNES
    montant_cols = {
        "MT_CAPITAL_PRET", "FRAIS_ACTES", "MT_FRAIDOS", "MT_PRET_INT",
        "MT_INT_CAPITALISE", "MT_ECH_PRET", "ENCOURS_CAP", "IMPAYE_CAP",
        "MT_IMPAYE", "CRD_JOUR", "RETARD_29", "RETARD_30", "RETARD_60",
        "RETARD_90", "RETARD_180", "RETARD_360", "RETARD_720", "VALEUR_GARANTIE",
    }
    date_cols = {"D_MEP_PRET", "D_PREM_ECH", "D_DER_ECH"}
    total_cols = {
        "MT_CAPITAL_PRET", "ENCOURS_CAP", "IMPAYE_CAP", "MT_IMPAYE",
        "RETARD_29", "RETARD_30", "RETARD_60", "RETARD_90",
        "RETARD_180", "RETARD_360", "RETARD_720",
    }

    def render_form(self) -> Optional[BalanceAgeeFilters]:
        try:
            dates_dispo = dates_arrete_enc_brut_cached()
        except Exception:  # noqa: BLE001
            dates_dispo = []
            st.warning(
                "Impossible de charger les dates d'arrêté disponibles "
                "(vérifie que le fichier .env est bien configuré et que le serveur a "
                "accès à la base)."
            )

        try:
            valeurs_genre = _valeurs_genre_cached()
        except Exception:  # noqa: BLE001
            valeurs_genre = []

        try:
            valeurs_ressource_aff = _valeurs_ressource_aff_cached()
        except Exception:  # noqa: BLE001
            valeurs_ressource_aff = []

        try:
            valeurs_classe_age = _valeurs_classe_age_cached()
        except Exception:  # noqa: BLE001
            valeurs_classe_age = []

        try:
            secteurs_df = _secteurs_cached()
        except Exception:  # noqa: BLE001
            secteurs_df = pd.DataFrame(columns=["CODE_SECT", "LIB_SECT"])

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
            c1, c2, c3 = st.columns(3)
            with c1:
                genre = _select_valeur("Genre", valeurs_genre, "Tous", "balage_genre", max_chars=1)
                no_pret = st.text_input("N° prêt", max_chars=15, key="balage_no_pret")
            with c2:
                ressource_aff = _select_valeur(
                    "Ressource affectée", valeurs_ressource_aff, "Toutes", "balage_ressource_aff", max_chars=1
                )
                classe_age = _select_valeur(
                    "Classe d'âge", valeurs_classe_age, "Toutes", "balage_classe_age"
                )
            with c3:
                matricule_client = st.text_input("Matricule client", max_chars=8, key="balage_matricule")
                code_sect = select_code_libelle(
                    "Secteur d'activité", secteurs_df, "CODE_SECT", "LIB_SECT",
                    "Tous", "balage_secteur",
                    allow_text_fallback=secteurs_df.empty,
                )

            st.caption("Localisation (Mutuelle → Agence → Bureau)")
            code_mutuelle, code_agence, code_bureau = render_localisation_cascade(
                ref_localisation_df, key_prefix="balage_"
            )

        submitted = st.button("🔍 Générer la Balance Agée", width="stretch", type="primary")

        if not submitted:
            return None

        filters = BalanceAgeeFilters(
            date_arrete=date_arrete,
            genre=genre or None,
            ressource_aff=ressource_aff or None,
            matricule_client=matricule_client or None,
            no_pret=no_pret or None,
            code_sect=code_sect or None,
            classe_age=classe_age or None,
            code_mutuelle=code_mutuelle or None,
            code_agence=code_agence or None,
            code_bureau=code_bureau or None,
        )

        erreur = filters.validate()
        if erreur:
            st.error(erreur)
            return None
        return filters

    def execute(self, filters: BalanceAgeeFilters) -> pd.DataFrame:
        return get_balance_agee(filters)

    def excel_filename(self, filters: BalanceAgeeFilters) -> str:
        return f"balance_agee_{filters.date_arrete:%Y%m%d}.xlsx"

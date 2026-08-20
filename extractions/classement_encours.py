"""
Extractions : Plus gros consommateurs, Plus petits consommateurs, Plus
gros contentieux.

Les trois sont des variantes du même classement (top 50 des clients
emprunteurs par encours de crédit cumulé, à une date d'arrêté choisie,
table ENC_BRUT), qui ne diffèrent que par :
  - le seuil sur l'encours (> 0 pour "gros", >= 1000 pour "petits", afin
    d'exclure les encours résiduels quasi nuls du classement des petits) ;
  - la condition sur les impayés (par_90/180/360/720 tous à 0 pour les
    "consommateurs" sains, au moins un des trois premiers buckets > 0
    pour le "contentieux") ;
  - l'ordre du classement (décroissant pour gros/contentieux, croissant
    pour petits) ;
  - la présence ou non des provisions (uniquement pour le contentieux).

Toute la logique commune (requête SQL, formulaire) est donc factorisée
ici ; seules les 3 classes en bas de fichier changent les paramètres.

Champ obligatoire : date d'arrêté (liste déroulante des dates disponibles
dans ENC_BRUT, la plus récente pré-sélectionnée). Filtres facultatifs :
localisation hiérarchique (Mutuelle -> Agence -> Bureau) ; le code et le
nom de chaque niveau choisi sont affichés dans le résultat.
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
# Filtres du formulaire (communs aux 3 extractions)
# ---------------------------------------------------------------------------


@dataclass
class ClassementFilters:
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

_COND_PAR_SAIN = (
    "NVL(eb.par_90, 0) = 0 AND NVL(eb.par_180, 0) = 0 "
    "AND NVL(eb.par_360, 0) = 0 AND NVL(eb.par_720, 0) = 0"
)
_COND_PAR_CONTENTIEUX = "(NVL(eb.par_90, 0) + NVL(eb.par_180, 0) + NVL(eb.par_360, 0)) > 0"


def _colonnes_finales(avec_provisions: bool) -> list[str]:
    cols = ["MATRICULE_CLIENT", "NOM_CLIENT", "SECTEUR", "ENCOURS_CAP_CUMULE", "GARANTIE"]
    if avec_provisions:
        cols.append("PROVISIONS")
    cols += [
        "CODE_BUREAU", "NOM_BUREAU",
        "CODE_AGENCE", "NOM_AGENCE",
        "CODE_MUTUELLE", "NOM_MUTUELLE",
        "RANG",
    ]
    return cols


def _build_sql(
    ordre: str,
    seuil_operateur: str,
    seuil_valeur: int,
    condition_par: str,
    avec_provisions: bool,
    filtres_localisation: str,
) -> str:
    solde_prov_col = "eb.solde_prov_th," if avec_provisions else ""
    provisions_agg = "SUM(solde_prov_th) AS provisions," if avec_provisions else ""
    provisions_select = "cr.provisions," if avec_provisions else ""

    return f"""
        WITH garantie_agg AS (
            SELECT
                g.no_pret,
                g.matricule_client,
                LISTAGG(tg.int_type_gar, ', ') WITHIN GROUP (ORDER BY tg.int_type_gar) AS desc_garantie
            FROM garanties g
            JOIN type_garantie tg ON tg.code_type_gar = g.code_type_gar
            GROUP BY g.no_pret, g.matricule_client
        ),
        enc_filtre AS (
            SELECT
                eb.matricule_client,
                eb.encours_cap,
                {solde_prov_col}
                s.lib_sect,
                ga.desc_garantie,
                eb.code_bureau     AS code_bureau,
                b.libelle_bureau   AS nom_bureau,
                r.code_region      AS code_agence,
                r.lib_region       AS nom_agence,
                mut.code_mutuelle  AS code_mutuelle,
                mut.nom_mutuelle   AS nom_mutuelle
            FROM enc_brut eb
            JOIN pret      p  ON p.no_pret        = eb.no_pret
                              AND p.code_bureau    = eb.code_bureau
            JOIN type_pret tp ON tp.code_type_pret = p.code_type_pret
            LEFT JOIN sous_secteur ss ON ss.code_ssect = eb.code_ssect
            LEFT JOIN secteur      s  ON s.code_sect   = ss.code_sect
            LEFT JOIN garantie_agg ga ON ga.no_pret          = eb.no_pret
                                      AND ga.matricule_client = eb.matricule_client
            LEFT JOIN bureau   b   ON b.code_bureau = eb.code_bureau
            LEFT JOIN region   r   ON r.code_region = b.code_region
            LEFT JOIN mutuelle mut ON mut.code_mutuelle = r.code_mutuelle
            WHERE eb.date_arrete = :date_arrete
              AND ABS(eb.encours_cap) {seuil_operateur} {seuil_valeur}
              AND (eb.enc_perte = 0 OR eb.enc_perte IS NULL)
              AND tp.ressource_aff = 'N'
              AND {condition_par}
              {filtres_localisation}
        ),
        client_agg AS (
            SELECT
                matricule_client,
                SUM(encours_cap) AS encours_cap_cumule,
                {provisions_agg}
                MAX(lib_sect)      AS lib_sect,
                MAX(desc_garantie) AS desc_garantie,
                MAX(code_bureau)   AS code_bureau,
                MAX(nom_bureau)    AS nom_bureau,
                MAX(code_agence)   AS code_agence,
                MAX(nom_agence)    AS nom_agence,
                MAX(code_mutuelle) AS code_mutuelle,
                MAX(nom_mutuelle)  AS nom_mutuelle
            FROM enc_filtre
            GROUP BY matricule_client
        ),
        client_rank AS (
            SELECT
                ca.*,
                ROW_NUMBER() OVER (ORDER BY encours_cap_cumule {ordre}) AS rang
            FROM client_agg ca
        )
        SELECT
            cr.matricule_client,
            cl.prenom_client || ' ' || cl.raison_sociale_client AS nom_client,
            cr.lib_sect      AS secteur,
            cr.encours_cap_cumule,
            cr.desc_garantie AS garantie,
            {provisions_select}
            cr.code_bureau, cr.nom_bureau,
            cr.code_agence, cr.nom_agence,
            cr.code_mutuelle, cr.nom_mutuelle,
            cr.rang
        FROM client_rank cr
        JOIN client cl ON cl.matricule_client = cr.matricule_client
        WHERE cr.rang <= 50
        ORDER BY cr.rang
    """


def get_classement(
    filters: ClassementFilters,
    *,
    ordre: str,
    seuil_operateur: str,
    seuil_valeur: int,
    condition_par: str,
    avec_provisions: bool,
) -> pd.DataFrame:
    """Exécute le classement (top 50) selon les paramètres de la variante appelante."""
    error = filters.validate()
    if error:
        raise ValueError(error)

    params: dict = {
        "date_arrete": dt.datetime.combine(filters.date_arrete, dt.time.min),
    }

    filtres_localisation = ""
    if filters.code_mutuelle:
        filtres_localisation += " AND mut.CODE_MUTUELLE = :code_mutuelle"
        params["code_mutuelle"] = filters.code_mutuelle.strip()

    if filters.code_agence:
        filtres_localisation += " AND r.CODE_REGION = :code_agence"
        params["code_agence"] = filters.code_agence.strip()

    if filters.code_bureau:
        filtres_localisation += " AND eb.CODE_BUREAU = :code_bureau"
        params["code_bureau"] = filters.code_bureau.strip()

    sql = _build_sql(
        ordre, seuil_operateur, seuil_valeur, condition_par, avec_provisions, filtres_localisation
    )

    df = fetch_df(sql, params)
    colonnes = _colonnes_finales(avec_provisions)
    if df.empty:
        return pd.DataFrame(columns=colonnes)
    return df[colonnes]


# ---------------------------------------------------------------------------
# Formulaire Streamlit (partagé par les 3 extractions)
# ---------------------------------------------------------------------------


def _render_form_commun(titre_bouton: str, key_prefix: str) -> Optional[ClassementFilters]:
    try:
        dates_dispo = dates_arrete_enc_brut_cached()
    except Exception:  # noqa: BLE001
        dates_dispo = []
        st.warning(
            "Impossible de charger les dates d'arrêté disponibles depuis ENC_BRUT "
            "(vérifie que le fichier .env est bien configuré et que le serveur a "
            "accès à la base)."
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
            "Impossible de charger la liste des mutuelles/agences/bureaux depuis "
            "la base. Tu peux réessayer plus tard."
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
            "Aucune date d'arrêté trouvée dans ENC_BRUT. Cette extraction ne peut "
            "pas être calculée pour le moment."
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

    filters = ClassementFilters(
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
    "SECTEUR": "Secteur",
    "ENCOURS_CAP_CUMULE": "Encours capital cumulé",
    "GARANTIE": "Garantie(s)",
    "PROVISIONS": "Provisions",
    "CODE_BUREAU": "Code bureau",
    "NOM_BUREAU": "Bureau",
    "CODE_AGENCE": "Code agence",
    "NOM_AGENCE": "Agence",
    "CODE_MUTUELLE": "Code mutuelle",
    "NOM_MUTUELLE": "Mutuelle",
    "RANG": "Rang",
}


# ---------------------------------------------------------------------------
# Les 3 extractions
# ---------------------------------------------------------------------------


class PlusGrosConsommateursExtraction(Extraction):
    id = "plus_gros_consommateurs"
    label = "Plus gros consommateurs"
    description = (
        "Top 50 des clients emprunteurs par encours de crédit cumulé (comptes "
        "sains, sans impayé), à une date d'arrêté donnée."
    )
    icon = "📈"

    column_labels = LIBELLES_COLONNES
    montant_cols = {"ENCOURS_CAP_CUMULE"}
    date_cols: set[str] = set()
    total_cols = {"ENCOURS_CAP_CUMULE"}

    def render_form(self) -> Optional[ClassementFilters]:
        return _render_form_commun("🔍 Générer le classement", key_prefix="gros_conso_")

    def execute(self, filters: ClassementFilters) -> pd.DataFrame:
        return get_classement(
            filters, ordre="DESC", seuil_operateur=">", seuil_valeur=0,
            condition_par=_COND_PAR_SAIN, avec_provisions=False,
        )

    def excel_filename(self, filters: ClassementFilters) -> str:
        return f"plus_gros_consommateurs_{filters.date_arrete:%Y%m%d}.xlsx"


class PlusPetitsConsommateursExtraction(Extraction):
    id = "plus_petits_consommateurs"
    label = "Plus petits consommateurs"
    description = (
        "Top 50 des clients emprunteurs par encours de crédit cumulé le plus "
        "faible (au moins 1000, comptes sains, sans impayé), à une date "
        "d'arrêté donnée."
    )
    icon = "📉"

    column_labels = LIBELLES_COLONNES
    montant_cols = {"ENCOURS_CAP_CUMULE"}
    date_cols: set[str] = set()
    total_cols = {"ENCOURS_CAP_CUMULE"}

    def render_form(self) -> Optional[ClassementFilters]:
        return _render_form_commun("🔍 Générer le classement", key_prefix="petits_conso_")

    def execute(self, filters: ClassementFilters) -> pd.DataFrame:
        return get_classement(
            filters, ordre="ASC", seuil_operateur=">=", seuil_valeur=1000,
            condition_par=_COND_PAR_SAIN, avec_provisions=False,
        )

    def excel_filename(self, filters: ClassementFilters) -> str:
        return f"plus_petits_consommateurs_{filters.date_arrete:%Y%m%d}.xlsx"


class PlusGrosContentieuxExtraction(Extraction):
    id = "plus_gros_contentieux"
    label = "Plus gros contentieux"
    description = (
        "Top 50 des clients emprunteurs en impayé (PAR 90/180/360) par encours "
        "de crédit cumulé, avec les provisions associées, à une date d'arrêté "
        "donnée."
    )
    icon = "⚠️"

    column_labels = LIBELLES_COLONNES
    montant_cols = {"ENCOURS_CAP_CUMULE", "PROVISIONS"}
    date_cols: set[str] = set()
    total_cols = {"ENCOURS_CAP_CUMULE", "PROVISIONS"}

    def render_form(self) -> Optional[ClassementFilters]:
        return _render_form_commun("🔍 Générer le classement", key_prefix="contentieux_")

    def execute(self, filters: ClassementFilters) -> pd.DataFrame:
        return get_classement(
            filters, ordre="DESC", seuil_operateur=">", seuil_valeur=0,
            condition_par=_COND_PAR_CONTENTIEUX, avec_provisions=True,
        )

    def excel_filename(self, filters: ClassementFilters) -> str:
        return f"plus_gros_contentieux_{filters.date_arrete:%Y%m%d}.xlsx"

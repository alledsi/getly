"""
Extraction : Base clientèle personnes morales.

Liste des clients personnes morales (PREFIXE_CLIENT = '0', hors comptes
internes ACEP et hors lignes "ERREUR REPRISE") avec leur forme juridique,
leur nature, leur dernier exercice financier connu (chiffre d'affaires,
résultat net, capital — le plus récent par ANNEE dans INFOS_FIN) et leur
dernier prêt (le plus récent par date de création, puis par numéro de
prêt, dans PRET). Reprend telle quelle la requête SQL fournie par
l'utilisateur le 18/11/2026 (2 CTE "dernier_exercice"/"dernier_pret" en
ROW_NUMBER() pour ne garder qu'une ligne par client sur chacune des deux
jointures).

Aucun filtre obligatoire : par défaut, la liste complète des clients
personnes morales (sur tout le périmètre) est retournée. Filtres
facultatifs : localisation hiérarchique (Mutuelle -> Agence -> Bureau),
sur le même principe que les autres extractions.

Les colonnes affichées reproduisent exactement la requête fournie par
l'utilisateur (libellés, casse et ordre inclus). La ligne commentée
`--AND cl.date_adhesion_client < ...` dans la requête d'origine est
conservée en commentaire SQL (non activée) au cas où l'utilisateur
souhaite un jour la réactiver manuellement.

Pas de ligne de total (liste de clients, pas de montants à additionner
par client — Chiffre d'affaires/Résultats/Capital sont des attributs du
dernier exercice connu, pas des flux à sommer sur la période).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd
import streamlit as st

from db import fetch_df
from extractions.base import Extraction
from extractions.reference_data import (
    referentiel_localisation_cached,
    render_localisation_cascade,
)

# ---------------------------------------------------------------------------
# Filtres du formulaire
# ---------------------------------------------------------------------------


@dataclass
class BaseClientelePersonnesMoralesFilters:
    code_mutuelle: Optional[str] = None
    code_agence: Optional[str] = None
    code_bureau: Optional[str] = None

    def validate(self) -> Optional[str]:
        # Pas de filtre obligatoire pour cette extraction.
        return None


# ---------------------------------------------------------------------------
# Accès aux données
# ---------------------------------------------------------------------------

# NB : jointure LEFT JOIN mutuelle ajoutée (absente de la requête d'origine
# de l'utilisateur) uniquement pour permettre le filtre facultatif par
# mutuelle — comme pour les autres extractions, elle n'ajoute aucune
# colonne au résultat affiché.
_BASE_SQL = """
    WITH dernier_exercice AS (
        SELECT matricule_client, annee, chiffre_affaire, resultat_net, capital,
               ROW_NUMBER() OVER (PARTITION BY matricule_client ORDER BY annee DESC) AS rn
        FROM infos_fin
    ),
    dernier_pret AS (
        SELECT matricule_client, no_pret,
               ROW_NUMBER() OVER (PARTITION BY matricule_client ORDER BY d_cre_pret DESC, no_pret DESC) AS rn
        FROM pret
    )
    SELECT
        b.code_region                                   AS "CODE AGENCE",
        b.libelle_bureau                                AS "BUREAU",
        cl.matricule_client                             AS "Matricule",
        cl.raison_sociale_client                        AS "NOM OU RAISON SOCIALE",
        fj.libelle_forme                                AS "FORME JURIDIQUE",
        nc.lib_nature                                   AS "NATURE",
        cl.code_categorie                               AS "CODE Categorie",
        cl.date_cre                                     AS "Date de création client",
        cl.no_registre_commerce                         AS "N° registre de commerce",
        cl.ninea                                        AS "NINEA",
        cl.code_ssect                                   AS "CODE SOUS SECTEUR",
        de.chiffre_affaire                              AS "Chiffre d'affaires",
        de.resultat_net                                 AS "Résultats",
        de.capital                                      AS "Capital",
        r.lib_region                                    AS "Agence",
        u.nomu                                          AS "Utilisateur ayant créé",
        dp.no_pret                                       AS "Numero pret"
    FROM client cl
    JOIN bureau b                 ON b.code_bureau = cl.code_bureau
    JOIN region r                 ON r.code_region = b.code_region
    LEFT JOIN mutuelle mut        ON mut.code_mutuelle = r.code_mutuelle
    LEFT JOIN forme_juridique fj  ON fj.code_forme = cl.code_forme
    LEFT JOIN nat_client nc       ON nc.code_nature = cl.code_nature
    LEFT JOIN evuti u             ON u.cuti = cl.code_util
    LEFT JOIN dernier_exercice de ON de.matricule_client = cl.matricule_client AND de.rn = 1
    LEFT JOIN dernier_pret dp     ON dp.matricule_client = cl.matricule_client AND dp.rn = 1
    WHERE cl.prefixe_client = '0'
      --AND cl.date_adhesion_client < TO_DATE('2026-07-01','YYYY-MM-DD')
      AND UPPER(NVL(cl.raison_sociale_client,'')) NOT LIKE '%ACEP%'
      AND UPPER(NVL(cl.raison_sociale_client,'')) NOT LIKE '%ERREUR REPRISE%'
      {filtres_optionnels}
    ORDER BY cl.matricule_client
"""

_COLONNES_FINALES = [
    "CODE AGENCE",
    "BUREAU",
    "Matricule",
    "NOM OU RAISON SOCIALE",
    "FORME JURIDIQUE",
    "NATURE",
    "CODE Categorie",
    "Date de création client",
    "N° registre de commerce",
    "NINEA",
    "CODE SOUS SECTEUR",
    "Chiffre d'affaires",
    "Résultats",
    "Capital",
    "Agence",
    "Utilisateur ayant créé",
    "Numero pret",
]


def _construire_filtres(filters: BaseClientelePersonnesMoralesFilters) -> tuple[str, dict]:
    """Construit la clause WHERE optionnelle (localisation) et les
    paramètres associés — seul filtre facultatif de cette extraction."""
    params: dict = {}
    filtres_optionnels = ""

    if filters.code_mutuelle:
        filtres_optionnels += " AND mut.code_mutuelle = :code_mutuelle"
        params["code_mutuelle"] = filters.code_mutuelle.strip()

    if filters.code_agence:
        filtres_optionnels += " AND r.code_region = :code_agence"
        params["code_agence"] = filters.code_agence.strip()

    if filters.code_bureau:
        filtres_optionnels += " AND cl.code_bureau = :code_bureau"
        params["code_bureau"] = filters.code_bureau.strip()

    return filtres_optionnels, params


def get_base_clientele_personnes_morales(
    filters: BaseClientelePersonnesMoralesFilters,
) -> pd.DataFrame:
    """Construit et exécute la requête de la base clientèle personnes
    morales, avec filtrage facultatif par localisation."""
    error = filters.validate()
    if error:
        raise ValueError(error)

    filtres_optionnels, params = _construire_filtres(filters)
    sql = _BASE_SQL.format(filtres_optionnels=filtres_optionnels)

    df = fetch_df(sql, params)
    if df.empty:
        return pd.DataFrame(columns=_COLONNES_FINALES)
    return df[_COLONNES_FINALES]


# ---------------------------------------------------------------------------
# Formulaire Streamlit
# ---------------------------------------------------------------------------

LIBELLES_COLONNES = {col: col for col in _COLONNES_FINALES}


class BaseClientelePersonnesMoralesExtraction(Extraction):
    id = "base_clientele_personnes_morales"
    label = "Base clientèle personnes morales"
    description = (
        "Clients personnes morales (hors ACEP), avec forme juridique, nature, "
        "dernier exercice financier connu et dernier prêt. Aucun filtre "
        "obligatoire."
    )
    icon = "🏢"

    column_labels = LIBELLES_COLONNES
    montant_cols = {"Chiffre d'affaires", "Résultats", "Capital"}
    date_cols = {"Date de création client"}
    total_cols: set[str] = set()

    def render_form(self) -> Optional[BaseClientelePersonnesMoralesFilters]:
        # NB : pas de st.form ici — les menus Mutuelle/Agence/Bureau sont en
        # cascade et doivent se recalculer immédiatement quand on change un
        # choix, ce que st.form empêche (il ne rerun qu'à la soumission).

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
        st.caption(
            "Aucun filtre obligatoire : par défaut, la liste complète des "
            "clients personnes morales (hors ACEP) est retournée."
        )

        with st.expander("Filtres avancés (facultatifs)"):
            st.caption("Localisation (Mutuelle → Agence → Bureau)")
            code_mutuelle, code_agence, code_bureau = render_localisation_cascade(
                ref_localisation_df, key_prefix="bcpm_"
            )

        submitted = st.button(
            "🔍 Générer la base clientèle personnes morales",
            width="stretch",
            type="primary",
        )

        if not submitted:
            return None

        filters = BaseClientelePersonnesMoralesFilters(
            code_mutuelle=code_mutuelle or None,
            code_agence=code_agence or None,
            code_bureau=code_bureau or None,
        )

        erreur = filters.validate()
        if erreur:
            st.error(erreur)
            return None
        return filters

    def execute(self, filters: BaseClientelePersonnesMoralesFilters) -> pd.DataFrame:
        return get_base_clientele_personnes_morales(filters)

    def excel_filename(self, filters: BaseClientelePersonnesMoralesFilters) -> str:
        return "base_clientele_personnes_morales.xlsx"

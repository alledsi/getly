"""
Extraction : Comptes Inactifs et Dormants.

Liste des comptes inactifs (statut N) et/ou dormants (statut D) depuis la
table de reporting RPT_COMPTES_INACTIFS_DORMANTS, avec les informations
du titulaire (nom, adresse, nationalité, pièce d'identité) et la date du
dernier mouvement.

Filtre facultatif : statut compte (Inactif / Dormant / Tous). Filtres
facultatifs supplémentaires : localisation hiérarchique (Mutuelle ->
Agence -> Bureau), obtenue en reliant RPT_COMPTES_INACTIFS_DORMANTS à
COMPTE via NUMERO_COMPTE = NO_COMPTE (la table de reporting elle-même ne
porte pas de code bureau).

La table ne porte qu'une seule date d'arrêté à la fois (même valeur sur
toutes les lignes) : pas de filtre pour la choisir, mais la colonne est
affichée dans le résultat pour que l'utilisateur sache à quelle date les
données correspondent. Quand aucun filtre de statut n'est appliqué, un
résumé affiche le nombre de comptes inactifs et le nombre de comptes
dormants séparément.
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

_STATUT_LABELS = {"N": "Inactif", "D": "Dormant"}
_STATUT_OPTIONS = ["Inactif (N)", "Dormant (D)"]
_STATUT_CODE_PAR_OPTION = {"Inactif (N)": "N", "Dormant (D)": "D"}


@dataclass
class ComptesInactifsDormantsFilters:
    status_compte: Optional[str] = None
    code_mutuelle: Optional[str] = None
    code_agence: Optional[str] = None
    code_bureau: Optional[str] = None

    def validate(self) -> Optional[str]:
        return None


# ---------------------------------------------------------------------------
# Accès aux données
# ---------------------------------------------------------------------------

_BASE_SQL = """
    SELECT
        m.CODE_MUTUELLE            AS CODE_MUTUELLE,
        m.NOM_MUTUELLE             AS NOM_MUTUELLE,
        r.CODE_REGION              AS CODE_AGENCE,
        r.LIB_REGION               AS NOM_AGENCE,
        cpt.CODE_BUREAU            AS CODE_BUREAU,
        b.LIBELLE_BUREAU           AS NOM_BUREAU,
        d.NUMERO_COMPTE            AS NUMERO_COMPTE,
        d.NOM_PRENOM_TITULAIRE     AS NOM_PRENOM_TITULAIRE,
        d.ADRESSE                  AS ADRESSE,
        p.LIB_NATION               AS NATIONALITE,
        d.DATE_NAISSANCE           AS DATE_NAISSANCE,
        d.LIEU_NAISSANCE           AS LIEU_NAISSANCE,
        d.NUMERO_PIECE_IDENTITE    AS NUMERO_PIECE_IDENTITE,
        d.DATE_DERNIER_MOUVEMENT   AS DATE_DERNIER_MOUVEMENT,
        d.SOLDE                    AS SOLDE,
        d.STATUS_COMPTE            AS STATUS_COMPTE,
        d.DATE_ARRETE              AS DATE_ARRETE
    FROM RPT_COMPTES_INACTIFS_DORMANTS d
    LEFT JOIN pays     p   ON p.CODE_PAYS   = d.CODE_NATION
    LEFT JOIN COMPTE   cpt ON cpt.NO_COMPTE = d.NUMERO_COMPTE
    LEFT JOIN BUREAU   b   ON b.CODE_BUREAU = cpt.CODE_BUREAU
    LEFT JOIN REGION   r   ON r.CODE_REGION = b.CODE_REGION
    LEFT JOIN MUTUELLE m   ON m.CODE_MUTUELLE = r.CODE_MUTUELLE
    WHERE 1 = 1
"""

_ORDER_SQL = " ORDER BY d.NUMERO_COMPTE"

_COLONNES_FINALES = [
    "CODE_MUTUELLE",
    "NOM_MUTUELLE",
    "CODE_AGENCE",
    "NOM_AGENCE",
    "CODE_BUREAU",
    "NOM_BUREAU",
    "NUMERO_COMPTE",
    "NOM_PRENOM_TITULAIRE",
    "ADRESSE",
    "NATIONALITE",
    "DATE_NAISSANCE",
    "LIEU_NAISSANCE",
    "NUMERO_PIECE_IDENTITE",
    "DATE_DERNIER_MOUVEMENT",
    "SOLDE",
    "STATUS_COMPTE",
    "DATE_ARRETE",
]


def get_comptes_inactifs_dormants(filters: ComptesInactifsDormantsFilters) -> pd.DataFrame:
    """Construit et exécute la requête des comptes inactifs/dormants."""
    error = filters.validate()
    if error:
        raise ValueError(error)

    sql = _BASE_SQL
    params: dict = {}

    if filters.status_compte:
        sql += " AND d.STATUS_COMPTE = :status_compte"
        params["status_compte"] = filters.status_compte.strip()

    if filters.code_mutuelle:
        sql += " AND m.CODE_MUTUELLE = :code_mutuelle"
        params["code_mutuelle"] = filters.code_mutuelle.strip()

    if filters.code_agence:
        sql += " AND r.CODE_REGION = :code_agence"
        params["code_agence"] = filters.code_agence.strip()

    if filters.code_bureau:
        sql += " AND cpt.CODE_BUREAU = :code_bureau"
        params["code_bureau"] = filters.code_bureau.strip()

    sql += _ORDER_SQL

    df = fetch_df(sql, params)
    if df.empty:
        return pd.DataFrame(columns=_COLONNES_FINALES)

    df = df.copy()
    df["STATUS_COMPTE"] = df["STATUS_COMPTE"].map(
        lambda v: _STATUT_LABELS.get(str(v).strip().upper(), v)
    )
    return df[_COLONNES_FINALES]


# ---------------------------------------------------------------------------
# Formulaire Streamlit
# ---------------------------------------------------------------------------

LIBELLES_COLONNES = {
    "CODE_MUTUELLE": "Code mutuelle",
    "NOM_MUTUELLE": "Mutuelle",
    "CODE_AGENCE": "Code agence",
    "NOM_AGENCE": "Agence",
    "CODE_BUREAU": "Code bureau",
    "NOM_BUREAU": "Bureau",
    "NUMERO_COMPTE": "N° compte",
    "NOM_PRENOM_TITULAIRE": "Nom et prénom du titulaire",
    "ADRESSE": "Adresse",
    "NATIONALITE": "Nationalité",
    "DATE_NAISSANCE": "Date de naissance",
    "LIEU_NAISSANCE": "Lieu de naissance",
    "NUMERO_PIECE_IDENTITE": "N° pièce d'identité",
    "DATE_DERNIER_MOUVEMENT": "Date dernier mouvement",
    "SOLDE": "Solde",
    "STATUS_COMPTE": "Statut compte",
    "DATE_ARRETE": "Date d'arrêté",
}


class ComptesInactifsDormantsExtraction(Extraction):
    id = "comptes_inactifs_dormants"
    label = "Comptes Inactifs et Dormants"
    description = (
        "Comptes inactifs et/ou dormants, avec les informations du titulaire "
        "et la date du dernier mouvement."
    )
    icon = "💤"

    column_labels = LIBELLES_COLONNES
    montant_cols = {"SOLDE"}
    date_cols = {"DATE_NAISSANCE", "DATE_DERNIER_MOUVEMENT", "DATE_ARRETE"}
    total_cols = {"SOLDE"}

    def render_form(self) -> Optional[ComptesInactifsDormantsFilters]:
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

        choix_statut = st.selectbox(
            "Statut compte",
            options=_STATUT_OPTIONS,
            index=None,
            placeholder="Tous",
        )
        status_compte = _STATUT_CODE_PAR_OPTION.get(choix_statut, "")

        with st.expander("Filtres avancés (facultatifs)"):
            st.caption("Localisation (Mutuelle → Agence → Bureau)")
            code_mutuelle, code_agence, code_bureau = render_localisation_cascade(
                ref_localisation_df, key_prefix="cid_"
            )

        submitted = st.button(
            "🔍 Générer la liste des comptes inactifs/dormants", width="stretch", type="primary"
        )

        if not submitted:
            return None

        filters = ComptesInactifsDormantsFilters(
            status_compte=status_compte or None,
            code_mutuelle=code_mutuelle or None,
            code_agence=code_agence or None,
            code_bureau=code_bureau or None,
        )

        erreur = filters.validate()
        if erreur:
            st.error(erreur)
            return None
        return filters

    def execute(self, filters: ComptesInactifsDormantsFilters) -> pd.DataFrame:
        return get_comptes_inactifs_dormants(filters)

    def render_resume_extra(self, df: pd.DataFrame, filters: ComptesInactifsDormantsFilters) -> None:
        if df.empty or filters.status_compte:
            return

        nb_inactifs = int((df["STATUS_COMPTE"] == "Inactif").sum())
        nb_dormants = int((df["STATUS_COMPTE"] == "Dormant").sum())

        c1, c2 = st.columns(2)
        c1.metric("Comptes inactifs", f"{nb_inactifs:,}".replace(",", " "))
        c2.metric("Comptes dormants", f"{nb_dormants:,}".replace(",", " "))

    def excel_filename(self, filters: ComptesInactifsDormantsFilters) -> str:
        suffixe = f"_{filters.status_compte}" if filters.status_compte else ""
        return f"comptes_inactifs_dormants{suffixe}_{dt.date.today():%Y%m%d}.xlsx"

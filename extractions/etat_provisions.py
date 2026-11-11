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

Les colonnes affichées reproduisent la requête fournie par l'utilisateur,
accents et casse inclus, à une correction près (signalée par
l'utilisateur le 09/11/2026) : sur la requête d'origine, les colonnes
"Nom du client"/"Date Imp"/"Numero compte"/"Date Opp"/"Durée Retard"
étaient un simple MAX(...) sur chaque groupe ROLLUP — correct pour une
ligne "détail" (un seul client dans le groupe, donc MAX() renvoie sa
valeur), mais trompeur sur une ligne "TOTAL <tranche>" (plusieurs
clients dans le groupe : MAX() y affichait arbitrairement le nom/la
valeur du client classé en dernier par ordre alphabétique/numérique,
laissant croire que la ligne de total concernait ce client précis).
Ces 5 colonnes sont donc vides sur les lignes "TOTAL <tranche>" (via
`CASE WHEN GROUPING(matricule) = 1 THEN NULL ELSE MAX(...) END`), tout
en gardant exactement le même calcul qu'avant sur les lignes détail.

Export Excel (ajouté le 10/11/2026, à la demande de l'utilisateur) : une
feuille "Récap" est ajoutée en première position, avant la feuille de
détail — 4 petits tableaux empilés (total par type de provision, par
mutuelle, par agence, par bureau), chacun une simple liste valeur/montant
+ une ligne "TOTAL GÉNÉRAL" (pas de tableau croisé type × localisation,
choix explicite de l'utilisateur). Alimentée par une requête séparée
(`get_etat_provisions_recap`/`_RECAP_SQL`) réutilisant la même CTE "det"
que la requête détail (`_DET_CTE_SQL`, désormais factorisée) et les mêmes
filtres (`_construire_filtres`), mais avec une agrégation simple (sans
ROLLUP) par mutuelle/agence/bureau/type de provision — construction des
4 tableaux empilés côté Python (pandas), pas en SQL.

Colonnes de mouvement de provision ajoutées le 11/11/2026, à la demande
de l'utilisateur (détail ET feuille "Récap") :
- **"Provision Comptabilisée au 01/01"** : solde arrêté (table
  SOLDE_ARRETE) du compte de provision du client (le même "Numero compte"
  271/272/223 déjà calculé ci-dessus) représentant l'ouverture de
  l'exercice de la date d'arrêté choisie (ex. date d'arrêté en octobre
  2025 -> solde "au 01/01/2025"). Dans SOLDE_ARRETE, ce solde d'ouverture
  est en réalité enregistré avec DATE_ARRETE = 31/12/(année-1) (clôture
  annuelle de l'exercice précédent, confirmé par l'utilisateur le
  11/11/2026), pas le 1er janvier de la même année — calculé via une CTE
  intermédiaire `det_montants` (sous-requête corrélée sur SOLDE_ARRETE
  par NO_COMPTE + CODE_BUREAU + DATE_ARRETE = 31 décembre précédent).
- **"Reprise Période"** : si le montant de provision calculé (colonne
  "Montant Provisions") est inférieur à la provision comptabilisée au
  01/01, l'excédent à reprendre (`provision comptabilisée − provision`) ;
  sinon 0. Calculée dans une CTE intermédiaire `det_reprise`.
- **"Provision Finale"** : `provision comptabilisée au 01/01 + Montant
  Provisions − Reprise Période`, formule donnée telle quelle par
  l'utilisateur.
Ces 3 colonnes sont sommées sur les lignes "TOTAL <tranche>" du ROLLUP
(même principe que "Cap. Déclassé"/"Solde Capital"/"Montant Provisions" :
ce sont des montants, pas des identifiants arbitraires, donc SUM() et non
MAX()), et réutilisées (sommées par mutuelle/agence/bureau/type) dans les
4 tableaux de la feuille "Récap".
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from io import BytesIO
from typing import Optional

import pandas as pd
import streamlit as st

from db import fetch_df
from export_excel import build_excel_with_recap
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

# CTE "det" partagée entre la requête détail (_BASE_SQL, avec son ROLLUP
# par client) et la requête récap (_RECAP_SQL, simple agrégation par
# mutuelle/agence/bureau/type de provision) — factorisée ici pour que les
# deux requêtes restent toujours cohérentes entre elles (même périmètre
# de lignes, même calcul du taux/intitulé/montant).
_DET_CTE_SQL = """
    WITH det_base AS (
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
    ),
    -- Montant de provision calculé (solde capital x taux) et provision
    -- déjà comptabilisée au 01/01 de l'année de la date d'arrêté (solde
    -- arrêté du compte de provision du client, table SOLDE_ARRETE) —
    -- isolés dans une CTE à part car Oracle interdit de référencer un
    -- alias du SELECT courant dans ce même SELECT. Dans SOLDE_ARRETE,
    -- le solde "au 01/01/AAAA" est en réalité enregistré avec
    -- DATE_ARRETE = 31/12/(AAAA-1) (clôture annuelle de l'exercice
    -- précédent, qui sert d'ouverture) — confirmé par l'utilisateur le
    -- 11/11/2026 : :date_ouverture est donc le 31 décembre de l'année
    -- précédant la date d'arrêté, pas le 1er janvier de la même année.
    det_montants AS (
        SELECT
            det_base.*,
            ROUND(det_base.solde_capital * det_base.taux / 100, 2) AS montant_provision,
            NVL((SELECT sa.SOLDE_CLOTURE
                 FROM solde_arrete sa
                 WHERE sa.NO_COMPTE   = det_base.numero_compte
                   AND sa.CODE_BUREAU = det_base.code_bureau
                   AND sa.DATE_ARRETE = :date_ouverture), 0)        AS provision_comptab_0101
        FROM det_base
    ),
    -- Reprise de la période : excédent de provision comptabilisée par
    -- rapport au montant de provision recalculé à cette date d'arrêté.
    det_reprise AS (
        SELECT
            det_montants.*,
            CASE WHEN montant_provision < provision_comptab_0101
                 THEN provision_comptab_0101 - montant_provision
                 ELSE 0
            END AS reprise_periode
        FROM det_montants
    ),
    det AS (
        SELECT
            det_reprise.*,
            provision_comptab_0101 + montant_provision - reprise_periode AS provision_finale
        FROM det_reprise
    )
"""

_BASE_SQL = _DET_CTE_SQL + """
    SELECT
        intitule                                    AS "Intitulé Provision",
        taux / 100                                  AS "Taux de Provision",
        CASE WHEN GROUPING(matricule) = 1 THEN 'TOTAL ' || intitule ELSE matricule END AS "Matricule",
        CASE WHEN GROUPING(matricule) = 1 THEN NULL ELSE MAX(nom_client)    END AS "Nom du client",
        CASE WHEN GROUPING(matricule) = 1 THEN NULL ELSE MAX(date_imp)      END AS "Date Imp",
        CASE WHEN GROUPING(matricule) = 1 THEN NULL ELSE MAX(numero_compte) END AS "Numero compte",
        CASE WHEN GROUPING(matricule) = 1 THEN NULL ELSE MAX(date_opp)      END AS "Date Opp",
        ROUND(SUM(cap_declasse), 2)                 AS "Cap. Déclassé",
        ROUND(SUM(solde_capital), 2)                AS "Solde Capital",
        CASE WHEN GROUPING(matricule) = 1 THEN NULL ELSE MAX(duree_retard)  END AS "Durée Retard",
        ROUND(SUM(montant_provision), 2)            AS "Montant Provisions",
        ROUND(SUM(provision_comptab_0101), 2)       AS "Provision Comptabilisée au 01/01",
        ROUND(SUM(reprise_periode), 2)               AS "Reprise Période",
        ROUND(SUM(provision_finale), 2)              AS "Provision Finale"
    FROM det
    LEFT JOIN bureau   b   ON b.code_bureau = det.code_bureau
    LEFT JOIN region   r   ON r.code_region = b.code_region
    LEFT JOIN mutuelle mut ON mut.code_mutuelle = r.code_mutuelle
    WHERE 1 = 1
      {filtres_optionnels}
    GROUP BY ordre, intitule, taux, ROLLUP ((matricule, nom_client, date_imp, numero_compte, date_opp, duree_retard))
    ORDER BY ordre, GROUPING(matricule), SUM(solde_capital) DESC
"""

# Requête récap (feuille "Récap" de l'export Excel, demandée le
# 10/11/2026) : une ligne par combinaison (mutuelle, agence, bureau, type
# de provision) avec le montant de provision total — agrégation simple
# (pas de ROLLUP), ensuite recombinée côté Python (pandas) en plusieurs
# petits tableaux "Total par type"/"par mutuelle"/"par agence"/"par
# bureau" (voir `_construire_blocs_recap`). Mêmes filtres optionnels que
# _BASE_SQL (même alias det/mut/r/b), donc même fonction
# `_construire_filtres` pour les deux requêtes.
_RECAP_SQL = _DET_CTE_SQL + """
    SELECT
        mut.NOM_MUTUELLE                             AS "Mutuelle",
        r.LIB_REGION                                 AS "Agence",
        b.LIBELLE_BUREAU                              AS "Bureau",
        intitule                                      AS "Intitulé Provision",
        ROUND(SUM(montant_provision), 2)              AS "Montant Provisions",
        ROUND(SUM(provision_comptab_0101), 2)         AS "Provision Comptabilisée au 01/01",
        ROUND(SUM(reprise_periode), 2)                 AS "Reprise Période",
        ROUND(SUM(provision_finale), 2)                AS "Provision Finale"
    FROM det
    LEFT JOIN bureau   b   ON b.code_bureau = det.code_bureau
    LEFT JOIN region   r   ON r.code_region = b.code_region
    LEFT JOIN mutuelle mut ON mut.code_mutuelle = r.code_mutuelle
    WHERE 1 = 1
      {filtres_optionnels}
    GROUP BY mut.NOM_MUTUELLE, r.LIB_REGION, b.LIBELLE_BUREAU, intitule
"""

_MONTANT_COLS_RECAP = [
    "Montant Provisions",
    "Provision Comptabilisée au 01/01",
    "Reprise Période",
    "Provision Finale",
]

_COLONNES_RECAP = ["Mutuelle", "Agence", "Bureau", "Intitulé Provision", *_MONTANT_COLS_RECAP]

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
    "Provision Comptabilisée au 01/01",
    "Reprise Période",
    "Provision Finale",
]


def _construire_filtres(filters: EtatProvisionsFilters) -> tuple[str, dict]:
    """Construit la clause WHERE optionnelle (alias det/mut/r communs à
    _BASE_SQL et _RECAP_SQL) et les paramètres associés — factorisé pour
    que les deux requêtes restent toujours filtrées de façon identique."""
    params: dict = {
        "date_arrete": dt.datetime.combine(filters.date_arrete, dt.time.min),
        # Provision comptabilisée "au 01/01" de l'année de la date
        # d'arrêté — dans SOLDE_ARRETE, ce solde d'ouverture est
        # enregistré avec DATE_ARRETE = 31/12 de l'année PRÉCÉDENTE
        # (clôture annuelle, confirmé par l'utilisateur le 11/11/2026),
        # pas le 1er janvier de la même année. Utilisé pour retrouver la
        # provision déjà comptabilisée (solde arrêté du compte de
        # provision, voir det_montants dans _DET_CTE_SQL).
        "date_ouverture": dt.datetime.combine(
            dt.date(filters.date_arrete.year - 1, 12, 31), dt.time.min
        ),
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

    return filtres_optionnels, params


def get_etat_provisions(filters: EtatProvisionsFilters) -> pd.DataFrame:
    """Construit et exécute la requête de l'état des provisions à la date
    d'arrêté choisie."""
    error = filters.validate()
    if error:
        raise ValueError(error)

    filtres_optionnels, params = _construire_filtres(filters)
    sql = _BASE_SQL.format(filtres_optionnels=filtres_optionnels)

    df = fetch_df(sql, params)
    if df.empty:
        return pd.DataFrame(columns=_COLONNES_FINALES)
    return df[_COLONNES_FINALES]


def get_etat_provisions_recap(filters: EtatProvisionsFilters) -> pd.DataFrame:
    """Résultat plat (une ligne par combinaison mutuelle/agence/bureau/type
    de provision, avec le montant de provision total) utilisé pour
    construire la feuille "Récap" de l'export Excel — mêmes filtres que
    `get_etat_provisions`, agrégation plus simple (pas de ROLLUP)."""
    error = filters.validate()
    if error:
        raise ValueError(error)

    filtres_optionnels, params = _construire_filtres(filters)
    sql = _RECAP_SQL.format(filtres_optionnels=filtres_optionnels)

    df = fetch_df(sql, params)
    if df.empty:
        return pd.DataFrame(columns=_COLONNES_RECAP)
    return df[_COLONNES_RECAP]


def _construire_blocs_recap(recap_df: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    """
    Construit les 4 tableaux empilés de la feuille "Récap" à partir du
    résultat plat de `get_etat_provisions_recap` : un total simple par
    type de provision, puis par mutuelle, par agence, par bureau — sans
    tableau croisé entre ces dimensions (choix explicite de
    l'utilisateur : un récap simple, une ligne par valeur + un total
    général, pas un tableau croisé type × localisation).
    """
    totaux_generaux = (
        {col: float(recap_df[col].sum()) for col in _MONTANT_COLS_RECAP}
        if not recap_df.empty
        else {col: 0.0 for col in _MONTANT_COLS_RECAP}
    )

    def _total_par(colonne: str) -> pd.DataFrame:
        if recap_df.empty:
            return pd.DataFrame({colonne: [], **{col: [] for col in _MONTANT_COLS_RECAP}})
        total = (
            recap_df.assign(**{colonne: recap_df[colonne].fillna("(Non renseigné)")})
            .groupby(colonne, as_index=False)[_MONTANT_COLS_RECAP]
            .sum()
            .sort_values("Montant Provisions", ascending=False)
        )
        ligne_totale = pd.DataFrame(
            {colonne: ["TOTAL GÉNÉRAL"], **{col: [totaux_generaux[col]] for col in _MONTANT_COLS_RECAP}}
        )
        return pd.concat([total, ligne_totale], ignore_index=True)

    if recap_df.empty:
        par_type = pd.DataFrame(
            {"Intitulé Provision": [], **{col: [] for col in _MONTANT_COLS_RECAP}}
        )
    else:
        ordre = {nom: i for i, nom in enumerate(_INTITULES_PROVISION_DISPONIBLES)}
        par_type = recap_df.groupby("Intitulé Provision", as_index=False)[_MONTANT_COLS_RECAP].sum()
        par_type["_ordre"] = par_type["Intitulé Provision"].map(ordre)
        par_type = par_type.sort_values("_ordre").drop(columns="_ordre")
        ligne_totale = pd.DataFrame(
            {
                "Intitulé Provision": ["TOTAL GÉNÉRAL"],
                **{col: [totaux_generaux[col]] for col in _MONTANT_COLS_RECAP},
            }
        )
        par_type = pd.concat([par_type, ligne_totale], ignore_index=True)

    return [
        ("TOTAL PAR TYPE DE PROVISION", par_type),
        ("TOTAL PAR MUTUELLE", _total_par("Mutuelle")),
        ("TOTAL PAR AGENCE", _total_par("Agence")),
        ("TOTAL PAR BUREAU", _total_par("Bureau")),
    ]


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
    montant_cols = {
        "Taux de Provision",
        "Cap. Déclassé",
        "Solde Capital",
        "Montant Provisions",
        "Provision Comptabilisée au 01/01",
        "Reprise Période",
        "Provision Finale",
    }
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

    def build_excel_export(self, df: pd.DataFrame, filters: EtatProvisionsFilters) -> BytesIO:
        """
        Classeur Excel avec une feuille "Récap" en plus de la feuille de
        détail habituelle (demande explicite de l'utilisateur, 10/11/2026) :
        4 petits tableaux empilés (total par type de provision, par
        mutuelle, par agence, par bureau), construits à partir d'une
        requête d'agrégation séparée (`get_etat_provisions_recap`, mêmes
        filtres que le détail) plutôt que recalculés depuis `df`, pour ne
        pas avoir à exclure/re-séparer les lignes "TOTAL <tranche>" déjà
        mêlées aux lignes détail dans `df`.
        """
        recap_df = get_etat_provisions_recap(filters)
        blocs = _construire_blocs_recap(recap_df)
        return build_excel_with_recap(
            df,
            recap_blocs=blocs,
            column_labels=self.column_labels,
            montant_cols=self.montant_cols,
            date_cols=self.date_cols,
            total_cols=self.total_cols,
            sheet_name=self.label,
            recap_montant_cols=set(_MONTANT_COLS_RECAP),
        )

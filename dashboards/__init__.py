"""
Registre des tableaux de bord de pilotage disponibles dans Getly.

Contrairement aux extractions (extractions/__init__.py), les tableaux de
bord partagent deux filtres communs (catégorie, date d'arrêté) gérés une
fois par app.py, puis chaque tableau de bord dessine son propre contenu
via sa fonction `render(categorie, date_arrete)`.
"""

from __future__ import annotations

from typing import Optional

from dashboards.base import Dashboard
from dashboards.cout_du_risque import render as render_cout_du_risque
from dashboards.encours import render as render_encours
from dashboards.rendement_portefeuille import render as render_rendement_portefeuille
from dashboards.resultat import render as render_resultat
from dashboards.situation_adhesions import render as render_situation_adhesions
from dashboards.situation_charges import render as render_situation_charges
from dashboards.situation_revenus import render as render_situation_revenus

DASHBOARDS: list[Dashboard] = [
    Dashboard(
        id="rendement_portefeuille",
        label="Rendement du portefeuille",
        icon="📈",
        render=render_rendement_portefeuille,
        description="(Frais de dossier + Intérêts + Intérêts pénalité + Frais de pénalité) / Encours.",
    ),
    Dashboard(
        id="cout_du_risque",
        label="Coût du risque",
        icon="🛡️",
        render=render_cout_du_risque,
        description="(Provisions + Pertes - Reprises de provisions - Récupération pertes) / Encours.",
    ),
    Dashboard(
        id="situation_adhesions",
        label="Situation des adhésions",
        icon="🪪",
        render=render_situation_adhesions,
        description="Montant des droits d'adhésion.",
    ),
    Dashboard(
        id="situation_revenus",
        label="Situation des revenus",
        icon="💵",
        render=render_situation_revenus,
        description="Total des revenus et répartition par type de revenu.",
    ),
    Dashboard(
        id="situation_charges",
        label="Situation des charges",
        icon="🧾",
        render=render_situation_charges,
        description="Total des charges et répartition par type de charge.",
    ),
    Dashboard(
        id="resultat",
        label="Résultat",
        icon="⚖️",
        render=render_resultat,
        description="Total des revenus - total des charges.",
    ),
    Dashboard(
        id="encours",
        label="Encours",
        icon="💰",
        render=render_encours,
        description="Évolution mensuelle de l'encours, par année et par catégorie.",
    ),
]


def get_dashboard(dashboard_id: str) -> Optional[Dashboard]:
    for d in DASHBOARDS:
        if d.id == dashboard_id:
            return d
    return None

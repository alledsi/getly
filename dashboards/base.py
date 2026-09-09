"""
Interface commune des tableaux de bord de pilotage.

Contrairement aux extractions (extractions/base.py), un tableau de bord ne
retourne pas un DataFrame à exporter : il dessine directement son contenu
(KPIs, graphiques) dans la page, à partir d'une catégorie et d'une date
d'arrêté déjà choisies par l'utilisateur (filtres communs à tous les
tableaux de bord, gérés une fois dans app.py).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Callable


@dataclass
class Dashboard:
    id: str
    label: str
    icon: str
    render: Callable[[str, dt.date], None]
    description: str = ""

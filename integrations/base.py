"""
Interface commune aux "Intégrations" de Getly.

Une Intégration permet à un utilisateur d'injecter des données dans une
table Oracle à partir d'un fichier (Excel, pour l'instant) uploadé depuis
l'application — à la différence des extractions (`extractions/`), qui ne
font que lire la base.

Pour ajouter une nouvelle intégration : implémente-la dans un nouveau
fichier de ce dossier (voir `regularisation.py` pour un exemple complet),
avec une fonction `render()` qui dessine tout l'écran Streamlit
(sélection des options, upload du fichier, aperçu, bouton de
confirmation, import), puis ajoute une instance d'`Integration` à la
liste `INTEGRATIONS` dans `integrations/__init__.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class Integration:
    id: str
    label: str
    icon: str
    render: Callable[[], None]
    description: str = ""

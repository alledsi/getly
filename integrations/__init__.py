"""
Registre des intégrations disponibles dans Getly.

Pour ajouter une nouvelle intégration : implémente-la dans un nouveau
fichier de ce dossier (voir base.py pour le guide), puis ajoute une
instance de ta classe à la liste INTEGRATIONS ci-dessous.
"""

from __future__ import annotations

from typing import Optional

from integrations.base import Integration
from integrations import regularisation

INTEGRATIONS: list[Integration] = [
    Integration(
        id="regularisation",
        label="Régularisation",
        icon="🔄",
        description=(
            "Importe un fichier Excel de régularisation (Immo ou Classic) "
            "dans TABLE_REGUL — remplace entièrement le contenu de la table."
        ),
        render=regularisation.render,
    ),
    # Ajoute ici les futures intégrations, ex. :
    # Integration(id="...", label="...", icon="...", render=...),
]


def get_integration(integration_id: str) -> Optional[Integration]:
    for integration in INTEGRATIONS:
        if integration.id == integration_id:
            return integration
    return None

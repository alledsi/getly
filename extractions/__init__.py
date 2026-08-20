"""
Registre des extractions disponibles dans Getly.

Pour ajouter un nouveau type d'extraction : implémente-le dans un nouveau
fichier de ce dossier (voir base.py pour le guide), puis ajoute une
instance de ta classe à la liste EXTRACTIONS ci-dessous.
"""

from __future__ import annotations

from typing import Optional

from extractions.base import Extraction
from extractions.balance_agee import BalanceAgeeExtraction
from extractions.journal_ecritures import JournalEcrituresExtraction
from extractions.etat_depots import EtatDepotsExtraction
from extractions.classement_encours import (
    PlusGrosConsommateursExtraction,
    PlusPetitsConsommateursExtraction,
    PlusGrosContentieuxExtraction,
)
from extractions.classement_depots import (
    PlusGrosDeposantsExtraction,
    PlusPetitsDeposantsExtraction,
)

EXTRACTIONS: list[Extraction] = [
    BalanceAgeeExtraction(),
    JournalEcrituresExtraction(),
    EtatDepotsExtraction(),
    PlusGrosConsommateursExtraction(),
    PlusPetitsConsommateursExtraction(),
    PlusGrosContentieuxExtraction(),
    PlusGrosDeposantsExtraction(),
    PlusPetitsDeposantsExtraction(),
    # Ajoute ici les futures extractions, ex. :
    # BalanceComptableExtraction(),
    # GrandLivreExtraction(),
]


def get_extraction(extraction_id: str) -> Optional[Extraction]:
    for extraction in EXTRACTIONS:
        if extraction.id == extraction_id:
            return extraction
    return None

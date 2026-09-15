"""
Registre des extractions disponibles dans Getly.

Pour ajouter un nouveau type d'extraction : implémente-le dans un nouveau
fichier de ce dossier (voir base.py pour le guide), puis ajoute une
instance de ta classe à la liste EXTRACTIONS ci-dessous.
"""

from __future__ import annotations

from typing import Optional

from extractions.base import Extraction
from extractions.clients_actifs import ClientsActifsExtraction
from extractions.balance_agee import BalanceAgeeExtraction
from extractions.journal_ecritures import JournalEcrituresExtraction
from extractions.recapitulatif_ecritures import RecapitulatifEcrituresExtraction
from extractions.etat_depots import EtatDepotsExtraction
from extractions.comptes_debiteurs import ComptesDebiteursExtraction
from extractions.nouveaux_comptes_debiteurs import NouveauxComptesDebiteursExtraction
from extractions.comptes_inactifs_dormants import ComptesInactifsDormantsExtraction
from extractions.ecritures_doublons_suspectes import EcrituresDoublonsSuspectesExtraction
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
    RecapitulatifEcrituresExtraction(),
    EcrituresDoublonsSuspectesExtraction(),
    EtatDepotsExtraction(),
    ComptesDebiteursExtraction(),
    NouveauxComptesDebiteursExtraction(),
    ComptesInactifsDormantsExtraction(),
    PlusGrosConsommateursExtraction(),
    PlusPetitsConsommateursExtraction(),
    PlusGrosContentieuxExtraction(),
    PlusGrosDeposantsExtraction(),
    PlusPetitsDeposantsExtraction(),
    ClientsActifsExtraction(),
    # Ajoute ici les futures extractions, ex. :
    # BalanceComptableExtraction(),
    # GrandLivreExtraction(),
]


def get_extraction(extraction_id: str) -> Optional[Extraction]:
    for extraction in EXTRACTIONS:
        if extraction.id == extraction_id:
            return extraction
    return None

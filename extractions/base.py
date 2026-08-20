"""
Interface commune à tous les types d'extraction proposés par Getly.

Pour ajouter un nouveau type d'extraction plus tard :

1. Crée un fichier `extractions/mon_extraction.py`.
2. Défini une classe de filtres (dataclass) avec une méthode
   `validate() -> str | None` (message d'erreur, ou None si ok).
3. Écris une sous-classe de `Extraction` avec :
   - `id`, `label`, `description`, `icon`
   - `column_labels`, `montant_cols`, `date_cols`, `total_cols`
     (pour l'affichage et l'export Excel)
   - `render_form()` : affiche les widgets Streamlit du formulaire dans
     un `st.form(...)`, et retourne l'objet de filtres une fois soumis et
     validé (ou `None` sinon).
   - `execute(filters)` : exécute la requête (via `db.fetch_df`) et
     retourne un DataFrame.
4. Dans `extractions/__init__.py`, importe ta classe et ajoute une
   instance à la liste `EXTRACTIONS`.

C'est tout : app.py affichera automatiquement la nouvelle extraction dans
le menu, avec formulaire, tableau et export Excel gérés génériquement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

import pandas as pd


class Extraction(ABC):
    """Un type d'extraction Getly (ex. "Journal des écritures")."""

    id: str = ""
    label: str = ""
    description: str = ""
    icon: str = "📄"

    # Personnalisation de l'affichage / export Excel (noms techniques de colonnes)
    column_labels: dict[str, str] = {}
    montant_cols: set[str] = set()
    date_cols: set[str] = set()
    total_cols: set[str] = set()

    @abstractmethod
    def render_form(self) -> Optional[Any]:
        """
        Affiche le formulaire Streamlit propre à cette extraction.

        Retourne l'objet de filtres si le formulaire a été soumis et
        validé au cours de ce run, sinon None.
        """

    @abstractmethod
    def execute(self, filters: Any) -> pd.DataFrame:
        """Exécute l'extraction et retourne le DataFrame résultat."""

    def excel_filename(self, filters: Any) -> str:
        """Nom du fichier Excel proposé au téléchargement."""
        return f"{self.id}.xlsx"

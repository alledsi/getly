"""
Export générique d'un DataFrame vers un fichier Excel formaté
(en-têtes, montants, dates, ligne de total optionnelle, largeur des
colonnes). Utilisé par tous les types d'extraction Getly : chaque module
d'extraction passe ses propres libellés de colonnes et ses colonnes
"montant" / "date" / "à totaliser".

`build_excel_multi_sheet` produit le même formatage mais avec une feuille
par entrée d'un dict {nom_feuille: DataFrame} — utilisé par les
classements (Plus gros/petits consommateurs, Plus gros contentieux, Plus
gros/petits déposants) quand le mode "Par mutuelle" est actif (une feuille
par mutuelle plutôt qu'un classeur à une seule feuille).
"""

from __future__ import annotations

import re
from io import BytesIO

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

EN_TETE_FOND = "1F4E78"
EN_TETE_POLICE = Font(color="FFFFFF", bold=True)
TOTAL_FOND = PatternFill(start_color="DCE6F1", end_color="DCE6F1", fill_type="solid")
TOTAL_POLICE = Font(bold=True)

# Limite dure d'Excel : 1 048 576 lignes par feuille. On réserve la ligne
# 1 pour l'en-tête et une ligne de plus pour une éventuelle ligne TOTAL
# (ajoutée après les données si total_cols est fourni) — donc 1 048 574
# lignes de données maximum par feuille, que cette feuille ait ou non une
# ligne de total (constante unique, plus simple qu'un calcul conditionnel
# par appel).
_EXCEL_MAX_DATA_ROWS = 1_048_574


def _write_formatted_sheet(
    writer,
    df: pd.DataFrame,
    *,
    sheet_name: str,
    column_labels: dict[str, str],
    montant_cols: set[str],
    date_cols: set[str],
    total_cols: set[str],
) -> None:
    """Écrit `df` dans une feuille `sheet_name` du classeur en cours
    (en-têtes, formats montant/date, ligne de total), logique partagée par
    `build_excel` et `build_excel_multi_sheet`."""
    montant_labels = {column_labels.get(c, c) for c in montant_cols}
    date_labels = {column_labels.get(c, c) for c in date_cols}
    total_labels = {column_labels.get(c, c) for c in total_cols}

    df_export = df.rename(columns=column_labels)
    df_export.to_excel(writer, index=False, sheet_name=sheet_name)
    ws = writer.sheets[sheet_name]
    ws.sheet_state = "visible"
    writer.book.active = 0

    n_rows, n_cols = df_export.shape

    # --- En-têtes ---
    for col_idx in range(1, n_cols + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = EN_TETE_POLICE
        cell.fill = PatternFill(
            start_color=EN_TETE_FOND, end_color=EN_TETE_FOND, fill_type="solid"
        )
        cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.freeze_panes = "A2"

    # --- Formats des colonnes montants / dates + largeur ---
    for col_idx, col_name in enumerate(df_export.columns, start=1):
        col_letter = get_column_letter(col_idx)
        if col_name in montant_labels:
            for row_idx in range(2, n_rows + 2):
                ws.cell(row=row_idx, column=col_idx).number_format = "#,##0.00"
        elif col_name in date_labels:
            for row_idx in range(2, n_rows + 2):
                ws.cell(row=row_idx, column=col_idx).number_format = "dd/mm/yyyy"

        max_len = max(
            [len(str(col_name))]
            + [len(str(v)) for v in df_export[col_name].astype(str).head(200)]
        )
        ws.column_dimensions[col_letter].width = min(max_len + 2, 40)

    # --- Ligne de total (somme des colonnes listées dans total_cols) ---
    if n_rows > 0 and total_labels:
        total_row = n_rows + 2
        ws.cell(row=total_row, column=1, value="TOTAL").font = TOTAL_POLICE

        for col_idx, col_name in enumerate(df_export.columns, start=1):
            cell = ws.cell(row=total_row, column=col_idx)
            cell.fill = TOTAL_FOND
            cell.font = TOTAL_POLICE
            if col_name in total_labels:
                col_letter = get_column_letter(col_idx)
                cell.value = f"=SUM({col_letter}2:{col_letter}{n_rows + 1})"
                cell.number_format = "#,##0.00"


def _nom_feuille_unique(nom: str, deja_utilises: set[str]) -> str:
    """
    Nettoie un nom de feuille pour respecter les contraintes Excel (31
    caractères max, caractères \\ / ? * [ ] : interdits) et garantit son
    unicité dans le classeur (suffixe numérique en cas de collision après
    troncature, ex. deux mutuelles dont le nom ne diffère qu'après le
    31e caractère — ou plusieurs morceaux d'un même résultat trop
    volumineux pour une seule feuille, voir `_write_chunked`).
    """
    nettoye = re.sub(r"[\\/?*\[\]:]", "-", str(nom)).strip() or "Feuille"
    nettoye = nettoye[:31]
    base = nettoye
    i = 2
    while nettoye in deja_utilises:
        suffixe = f" ({i})"
        nettoye = base[: 31 - len(suffixe)] + suffixe
        i += 1
    deja_utilises.add(nettoye)
    return nettoye


def _write_chunked(
    writer,
    df: pd.DataFrame,
    *,
    base_sheet_name: str,
    deja_utilises: set[str],
    column_labels: dict[str, str],
    montant_cols: set[str],
    date_cols: set[str],
    total_cols: set[str],
) -> None:
    """Écrit `df` sur une ou plusieurs feuilles nommées à partir de
    `base_sheet_name` (`_nom_feuille_unique` donnant `base_sheet_name`,
    puis `base_sheet_name (2)`, `(3)`... à chaque collision).

    Un classeur Excel ne peut pas contenir plus de 1 048 576 lignes par
    feuille (en-tête comprise) — `to_excel()` refuse silencieusement
    d'écrire au-delà, ce qui fait ensuite échouer l'enregistrement du
    classeur avec une erreur openpyxl trompeuse ("At least one sheet must
    be visible", faute de feuille créée). Un résultat trop volumineux est
    donc automatiquement réparti sur plusieurs feuilles plutôt que de
    faire planter l'export — chaque feuille garde sa propre ligne de
    total (si `total_cols` est fourni), il n'y a pas de total combiné
    entre les feuilles."""
    if len(df) <= _EXCEL_MAX_DATA_ROWS:
        sheet_name = _nom_feuille_unique(base_sheet_name, deja_utilises)
        _write_formatted_sheet(
            writer,
            df,
            sheet_name=sheet_name,
            column_labels=column_labels,
            montant_cols=montant_cols,
            date_cols=date_cols,
            total_cols=total_cols,
        )
        return

    for i in range(0, len(df), _EXCEL_MAX_DATA_ROWS):
        morceau = df.iloc[i : i + _EXCEL_MAX_DATA_ROWS]
        sheet_name = _nom_feuille_unique(base_sheet_name, deja_utilises)
        _write_formatted_sheet(
            writer,
            morceau,
            sheet_name=sheet_name,
            column_labels=column_labels,
            montant_cols=montant_cols,
            date_cols=date_cols,
            total_cols=total_cols,
        )


def build_csv(
    df: pd.DataFrame,
    *,
    column_labels: dict[str, str] | None = None,
) -> bytes:
    """
    Export CSV, beaucoup plus rapide que `build_excel` sur un gros volume
    (pas de mise en forme cellule par cellule — mesuré environ 40x plus
    rapide sur 1,3M lignes) : utile comme solution de secours "rapide"
    quand l'utilisateur veut juste les données vite, sans la mise en forme
    (en-têtes colorés, formats montant/date, feuilles par agence/mutuelle,
    ligne de total) de l'export Excel. Séparateur `;` et encodage
    `utf-8-sig` (BOM) choisis pour s'ouvrir directement par double-clic
    dans un Excel en locale française (virgule décimale), sans passer par
    l'assistant d'import.
    """
    df_export = df.rename(columns=column_labels or {})
    # `to_csv()` sans chemin renvoie une chaîne Python ; le paramètre
    # `encoding` n'a alors aucun effet (il ne s'applique qu'à un fichier),
    # donc l'encodage avec BOM est fait explicitement ici.
    return df_export.to_csv(index=False, sep=";").encode("utf-8-sig")


def build_excel(
    df: pd.DataFrame,
    *,
    column_labels: dict[str, str] | None = None,
    montant_cols: set[str] | None = None,
    date_cols: set[str] | None = None,
    total_cols: set[str] | None = None,
    sheet_name: str = "Extraction",
) -> BytesIO:
    """
    Retourne un buffer BytesIO contenant le classeur Excel prêt à télécharger.

    - column_labels : correspondance nom technique -> libellé affiché
      (ex. {"NO_COMPTE": "N° compte"}). Les colonnes non listées gardent
      leur nom technique.
    - montant_cols : colonnes (noms techniques) formatées en nombre "0.00".
    - date_cols : colonnes (noms techniques) formatées en date jj/mm/aaaa.
    - total_cols : sous-ensemble de montant_cols pour lesquelles une ligne
      de total (somme) est ajoutée en bas du tableau.
    - sheet_name : nom de l'onglet (max 31 caractères, contrainte Excel).
      Si `df` dépasse 1 048 575 lignes, le résultat est automatiquement
      réparti sur plusieurs feuilles (`sheet_name`, `sheet_name (2)`...).
    """
    buffer = BytesIO()
    deja_utilises: set[str] = set()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        _write_chunked(
            writer,
            df,
            base_sheet_name=(sheet_name or "Extraction")[:31],
            deja_utilises=deja_utilises,
            column_labels=column_labels or {},
            montant_cols=montant_cols or set(),
            date_cols=date_cols or set(),
            total_cols=total_cols or set(),
        )
    buffer.seek(0)
    return buffer


def build_excel_multi_sheet(
    sheets: dict[str, pd.DataFrame],
    *,
    column_labels: dict[str, str] | None = None,
    montant_cols: set[str] | None = None,
    date_cols: set[str] | None = None,
    total_cols: set[str] | None = None,
) -> BytesIO:
    """
    Comme `build_excel`, mais produit un classeur avec une feuille par
    entrée de `sheets` (ex. une feuille par mutuelle pour les classements
    en mode "Par mutuelle"), dans l'ordre d'itération du dict, chaque
    feuille recevant le même formatage (en-têtes, colonnes montant/date,
    ligne de total). Chaque entrée est elle-même répartie sur plusieurs
    feuilles si elle dépasse 1 048 575 lignes (voir `_write_chunked`).
    """
    column_labels = column_labels or {}
    montant_cols = montant_cols or set()
    date_cols = date_cols or set()
    total_cols = total_cols or set()

    buffer = BytesIO()
    deja_utilises: set[str] = set()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for nom, df in sheets.items():
            _write_chunked(
                writer,
                df,
                base_sheet_name=str(nom)[:31],
                deja_utilises=deja_utilises,
                column_labels=column_labels,
                montant_cols=montant_cols,
                date_cols=date_cols,
                total_cols=total_cols,
            )
    buffer.seek(0)
    return buffer

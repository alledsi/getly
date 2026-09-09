"""
Composants visuels partagés par les tableaux de bord : cartes KPI, graphique
héros (%), graphiques en barres horizontales (classement / répartition),
formatage des nombres.

Palette et règles de couleur : palette catégorielle fixe à 8 teintes
(jamais recyclée au hasard), une seule teinte par mesure sur les
graphiques à barres simples, couleurs "statut" (positif/négatif) réservées
au résultat. Polices système, chiffres avec espace comme séparateur de
milliers (convention déjà utilisée dans le reste de Getly / la balance
ACEP).
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
YELLOW = "#eda100"
MAGENTA = "#e87ba4"
GREEN = "#008300"
VIOLET = "#4a3aa7"
RED = "#e34948"

CATEGORICAL = [BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED]

STATUS_GOOD = "#0ca30c"
STATUS_CRITICAL = "#d03b3b"

INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
SURFACE = "#ffffff"
CARD_BG = "#fbfbfa"
CARD_BORDER = "rgba(11,11,11,0.08)"

FONT_FAMILY = "system-ui, -apple-system, 'Segoe UI', sans-serif"


# ---------------------------------------------------------------------------
# CSS des cartes KPI (injecté une fois par page)
# ---------------------------------------------------------------------------

_CSS = f"""
<style>
.kpi-card {{
    background: {CARD_BG};
    border: 1px solid {CARD_BORDER};
    border-radius: 12px;
    padding: 16px 18px;
    height: 100%;
}}
.kpi-label {{
    font-size: 0.78rem;
    color: {INK_SECONDARY};
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.02em;
    margin-bottom: 6px;
}}
.kpi-value {{
    font-size: 1.5rem;
    color: {INK_PRIMARY};
    font-weight: 700;
    line-height: 1.2;
}}
.kpi-value.small {{
    font-size: 1.15rem;
}}
.hero-card {{
    background: linear-gradient(135deg, {BLUE} 0%, #1c5cab 100%);
    border-radius: 16px;
    padding: 28px 32px;
    color: white;
}}
.hero-label {{
    font-size: 0.85rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    opacity: 0.85;
    margin-bottom: 8px;
}}
.hero-value {{
    font-size: 2.75rem;
    font-weight: 800;
    line-height: 1;
}}
.hero-sub {{
    font-size: 0.85rem;
    opacity: 0.85;
    margin-top: 10px;
}}
.hero-card.negative {{
    background: linear-gradient(135deg, {RED} 0%, #a83030 100%);
}}
.section-title {{
    font-size: 1.0rem;
    font-weight: 700;
    color: {INK_PRIMARY};
    margin: 28px 0 10px 0;
}}
.empty-note {{
    color: {INK_MUTED};
    font-size: 0.85rem;
    font-style: italic;
    padding: 10px 0;
}}
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Formatage
# ---------------------------------------------------------------------------


def fmt_montant(x: float | None, unite: str = "") -> str:
    if x is None:
        return "—"
    sign = "-" if x < 0 else ""
    s = f"{abs(x):,.0f}".replace(",", " ")
    return f"{sign}{s}{(' ' + unite) if unite else ''}"


def fmt_pct(x: float | None, decimales: int = 2) -> str:
    if x is None:
        return "—"
    s = f"{x * 100:,.{decimales}f}".replace(",", " ").replace(".", ",")
    return f"{s} %"


# ---------------------------------------------------------------------------
# Cartes KPI
# ---------------------------------------------------------------------------


def kpi_row(items: list[tuple[str, str]]) -> None:
    """Affiche une ligne de cartes KPI. `items` = liste de (label, valeur déjà formatée)."""
    if not items:
        return
    cols = st.columns(len(items))
    for col, (label, value) in zip(cols, items):
        with col:
            st.markdown(
                f'<div class="kpi-card"><div class="kpi-label">{label}</div>'
                f'<div class="kpi-value small">{value}</div></div>',
                unsafe_allow_html=True,
            )


def hero_metric(label: str, value: str, sub: str | None = None, negative: bool = False) -> None:
    """Grande carte "héros" pour le chiffre clé du tableau de bord (rendement,
    coût du risque, résultat...)."""
    cls = "hero-card negative" if negative else "hero-card"
    sub_html = f'<div class="hero-sub">{sub}</div>' if sub else ""
    st.markdown(
        f'<div class="{cls}"><div class="hero-label">{label}</div>'
        f'<div class="hero-value">{value}</div>{sub_html}</div>',
        unsafe_allow_html=True,
    )


def section_title(titre: str) -> None:
    st.markdown(f'<div class="section-title">{titre}</div>', unsafe_allow_html=True)


def empty_note(texte: str) -> None:
    st.markdown(f'<div class="empty-note">{texte}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Graphiques
# ---------------------------------------------------------------------------


def _base_layout(fig: go.Figure, height: int) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=30, t=10, b=10),
        plot_bgcolor=SURFACE,
        paper_bgcolor=SURFACE,
        font=dict(family=FONT_FAMILY, color=INK_SECONDARY, size=13),
        showlegend=False,
    )
    return fig


def bar_classement(
    df: pd.DataFrame,
    label_col: str,
    value_col: str,
    value_fmt=fmt_montant,
    color: str = BLUE,
    height: int | None = None,
) -> go.Figure:
    """Barres horizontales, une seule teinte, triées par magnitude décroissante,
    avec étiquette de valeur directe (pour un classement 'par mutuelle')."""
    d = df.sort_values(value_col, ascending=True)
    texte = [value_fmt(v) for v in d[value_col]]
    fig = go.Figure(
        go.Bar(
            x=d[value_col],
            y=d[label_col],
            orientation="h",
            marker=dict(color=color, line=dict(width=0)),
            text=texte,
            textposition="outside",
            cliponaxis=False,
        )
    )
    fig.update_xaxes(showgrid=True, gridcolor=GRID, zeroline=True, zerolinecolor=GRID, showticklabels=False)
    fig.update_yaxes(showgrid=False, color=INK_PRIMARY)
    h = height or max(140, 44 * len(d) + 40)
    return _base_layout(fig, h)


def bar_classement_signe(
    df: pd.DataFrame,
    label_col: str,
    value_col: str,
    value_fmt=fmt_montant,
    height: int | None = None,
) -> go.Figure:
    """Comme bar_classement, mais colore chaque barre selon le signe
    (positif = vert statut, négatif = rouge statut) — pour un résultat."""
    d = df.sort_values(value_col, ascending=True)
    couleurs = [STATUS_GOOD if v >= 0 else STATUS_CRITICAL for v in d[value_col]]
    texte = [value_fmt(v) for v in d[value_col]]
    fig = go.Figure(
        go.Bar(
            x=d[value_col],
            y=d[label_col],
            orientation="h",
            marker=dict(color=couleurs, line=dict(width=0)),
            text=texte,
            textposition="outside",
            cliponaxis=False,
        )
    )
    fig.update_xaxes(showgrid=True, gridcolor=GRID, zeroline=True, zerolinecolor=INK_MUTED, showticklabels=False)
    fig.update_yaxes(showgrid=False, color=INK_PRIMARY)
    h = height or max(140, 44 * len(d) + 40)
    return _base_layout(fig, h)


def bar_repartition(
    labels: list[str],
    values: list[float],
    value_fmt=fmt_montant,
    height: int | None = None,
) -> go.Figure:
    """Barres horizontales triées par magnitude décroissante — répartition
    d'un total par type (revenus, charges...). Une seule teinte : la
    grandeur se lit par la longueur de la barre, pas par la couleur."""
    d = pd.DataFrame({"label": labels, "value": values}).sort_values("value", ascending=True)
    texte = [value_fmt(v) for v in d["value"]]
    fig = go.Figure(
        go.Bar(
            x=d["value"],
            y=d["label"],
            orientation="h",
            marker=dict(color=BLUE, line=dict(width=0)),
            text=texte,
            textposition="outside",
            cliponaxis=False,
        )
    )
    fig.update_xaxes(showgrid=True, gridcolor=GRID, zeroline=True, zerolinecolor=GRID, showticklabels=False)
    fig.update_yaxes(showgrid=False, color=INK_PRIMARY)
    h = height or max(160, 40 * len(d) + 40)
    return _base_layout(fig, h)


def bar_produits_charges(df: pd.DataFrame, label_col: str) -> go.Figure:
    """Barres groupées Produits (bleu) / Charges (rouge) par mutuelle —
    seule paire de couleurs à contraster nettement (job = polarité)."""
    d = df.sort_values("PRODUITS", ascending=True)
    fig = go.Figure()
    fig.add_bar(
        x=d["PRODUITS"], y=d[label_col], orientation="h", name="Produits",
        marker=dict(color=BLUE),
        text=[fmt_montant(v) for v in d["PRODUITS"]], textposition="outside", cliponaxis=False,
    )
    fig.add_bar(
        x=d["CHARGES"], y=d[label_col], orientation="h", name="Charges",
        marker=dict(color=RED),
        text=[fmt_montant(v) for v in d["CHARGES"]], textposition="outside", cliponaxis=False,
    )
    fig.update_layout(barmode="group", legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    fig.update_xaxes(showgrid=True, gridcolor=GRID, zeroline=True, zerolinecolor=GRID, showticklabels=False)
    fig.update_yaxes(showgrid=False, color=INK_PRIMARY)
    fig.update_layout(
        height=max(180, 60 * len(d) + 60),
        margin=dict(l=10, r=40, t=40, b=10),
        plot_bgcolor=SURFACE,
        paper_bgcolor=SURFACE,
        font=dict(family=FONT_FAMILY, color=INK_SECONDARY, size=13),
    )
    return fig

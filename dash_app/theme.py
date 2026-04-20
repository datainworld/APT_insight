"""Design tokens mirrored from assets/colors_and_type.css for Plotly figures."""

from __future__ import annotations

import plotly.graph_objects as go

FONT_SANS = (
    "Pretendard, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "
    "'Helvetica Neue', Arial, sans-serif"
)
FONT_MONO = "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"

BG_1 = "#121212"
BG_2 = "#1e1e1e"
BG_3 = "#242424"
FG_1 = "#e0e0e0"
FG_2 = "#a0a0a0"
FG_3 = "#777777"
BORDER_1 = "#333333"

ACCENT_1 = "#4facfe"
ACCENT_2 = "#00f2fe"

POS = "#4CAF50"
NEG = "#ef5350"

PLOTLY_GRID = "#2a2a2c"
PLOTLY_AXIS = FG_2
PLOTLY_TICK = FG_3

CAT_COLORS = {
    "sale": ACCENT_1,   # --plotly-c1
    "lease": "#9C27B0", # --plotly-c5
    "rent": "#FF9800",  # --plotly-c4
}

# Dark red ramp for choropleth (from filtered_dashboard.html redScale)
RED_RAMP = [
    "#fde7e4", "#fbc9c0", "#f7a391", "#ef7f6d",
    "#d9584a", "#b0352c", "#81211d", "#651918",
]
CHOROPLETH_COLORSCALE = [[i / (len(RED_RAMP) - 1), c] for i, c in enumerate(RED_RAMP)]


def apply_dark_theme(fig: go.Figure, *, margin: dict | None = None) -> go.Figure:
    """Apply the dashboard's dark theme to a Plotly figure in-place."""
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT_SANS, color=PLOTLY_AXIS, size=12),
        margin=margin or dict(l=48, r=16, t=24, b=40),
        hoverlabel=dict(
            bgcolor=BG_3,
            bordercolor=ACCENT_1,
            font=dict(family=FONT_SANS, color=FG_1),
        ),
    )
    fig.update_xaxes(
        gridcolor=PLOTLY_GRID,
        tickcolor=PLOTLY_TICK,
        tickfont=dict(color=PLOTLY_TICK, size=10),
        zeroline=False,
    )
    fig.update_yaxes(
        gridcolor=PLOTLY_GRID,
        tickcolor=PLOTLY_TICK,
        tickfont=dict(color=PLOTLY_TICK, size=10),
        zeroline=False,
    )
    return fig

"""투자 지표 페이지 (/invest) — 스펙 3.5.

전세가율 choropleth + 갭 분포 히스토그램 + 매력도 점수 랭킹.
매력도 점수는 단순화된 공식 (스펙 5.1 glossary 참조). 호가 표준편차 항은 Phase 후속에서 추가.
"""

from __future__ import annotations

import dash
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, callback, dcc, html

from dash_app.components.choropleth_map import ChoroplethMap, build_hideout
from dash_app.components.formatters import format_percent, format_won
from dash_app.components.kpi_card import KpiCard
from dash_app.components.ranking_table import RankingTable
from dash_app.geo_names import collapse_db_sgg_to_geo
from dash_app.queries import invest_queries as iq
from dash_app.theme import ACCENT_2, apply_dark_theme

dash.register_page(
    __name__,
    path="/invest",
    name="투자 지표",
    order=5,
    title="APT Insight — 투자 지표",
)


_MAP_ID = "page-invest-map"
_TABLE_COLUMNS: list[dict] = [
    {"field": "apt_name", "headerName": "단지", "minWidth": 180,
     "cellRenderer": "markdown",
     "valueFormatter": {"function": "`[${params.value}](/complex?apt_id=${params.data.apt_id})`"}},
    {"field": "sgg", "headerName": "자치구", "minWidth": 100},
    {"field": "jeonse_ratio", "headerName": "전세가율", "minWidth": 110, "type": "numericColumn",
     "valueFormatter": {"function": "params.value == null ? '—' : (params.value * 100).toFixed(1) + '%'"}},
    {"field": "gap", "headerName": "갭(만원)", "minWidth": 120, "type": "numericColumn",
     "valueFormatter": {"function": "params.value == null ? '—' : d3.format(',.0f')(params.value)"}},
    {"field": "median_sale", "headerName": "매매 중위", "minWidth": 120, "type": "numericColumn",
     "valueFormatter": {"function": "params.value == null ? '—' : d3.format(',.0f')(params.value)"}},
    {"field": "median_jeonse", "headerName": "전세 중위", "minWidth": 120, "type": "numericColumn",
     "valueFormatter": {"function": "params.value == null ? '—' : d3.format(',.0f')(params.value)"}},
    {"field": "sale_count", "headerName": "거래 6M", "minWidth": 100, "type": "numericColumn"},
    {"field": "attractiveness_score", "headerName": "매력도 점수", "minWidth": 120,
     "type": "numericColumn",
     "valueFormatter": {"function": "params.value == null ? '—' : params.value.toFixed(1)"}},
]


def _page_head() -> html.Div:
    return html.Div(
        className="page-head",
        children=[
            html.H1("투자 지표"),
            html.Div(
                className="live",
                children=[
                    html.Span(className="dot-live"),
                    html.Span(id="page-invest-scope", children="—"),
                ],
            ),
        ],
    )


def _kpi_strip() -> html.Div:
    return html.Div(
        className="kpi-strip",
        children=[
            KpiCard("전세가율", value_id="kpi-invest-jeonse-v", term="전세가율"),
            KpiCard("중위 갭", value_id="kpi-invest-gap-v", term="갭"),
            KpiCard("전월세전환율", value_id="kpi-invest-conv-v", term="전월세전환율"),
            KpiCard("매력도 상위 10% 컷오프", value_id="kpi-invest-cutoff-v", term="갭투자_점수"),
        ],
    )


def _right_panel() -> html.Div:
    return html.Div(
        className="card",
        children=[
            html.Div(
                className="card-head",
                children=[
                    html.Div(className="ic", children=html.I(className="fa-solid fa-chart-column")),
                    html.Div(className="t", children="갭 분포"),
                    html.Div(className="s", children="히스토그램 · 만원"),
                ],
            ),
            dcc.Graph(
                id="page-invest-gap-hist",
                config={"displayModeBar": False, "responsive": True},
                style={"height": 440},
            ),
        ],
    )


def _ranking_card() -> html.Div:
    return html.Div(
        className="card",
        children=[
            html.Div(
                className="card-head",
                children=[
                    html.Div(className="ic", children=html.I(className="fa-solid fa-table")),
                    html.Div(className="t", children="매력도 점수 랭킹"),
                    html.Div(className="s", children="상위 500 단지"),
                ],
            ),
            RankingTable("page-invest-rank", _TABLE_COLUMNS, row_data=[], page_size=25, height=440),
        ],
    )


layout = html.Main(
    className="fd-main",
    children=[
        _page_head(),
        _kpi_strip(),
        html.Div(
            className="row2-28",
            children=[
                html.Div(
                    className="card",
                    style={"padding": 0, "overflow": "hidden"},
                    children=[ChoroplethMap(_MAP_ID, {}, color_scale="Greens", height=440)],
                ),
                _right_panel(),
            ],
        ),
        _ranking_card(),
    ],
)


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------


def _build_gap_hist(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if df.empty or df["gap"].isna().all():
        fig.add_annotation(
            text="데이터 없음", showarrow=False, font=dict(color="#777"),
            xref="paper", yref="paper", x=0.5, y=0.5,
        )
        return apply_dark_theme(fig, margin=dict(l=10, r=10, t=10, b=10))
    gaps = df["gap"].dropna()
    fig.add_trace(
        go.Histogram(
            x=gaps,
            nbinsx=40,
            marker=dict(color=ACCENT_2, line=dict(color="#0c2630", width=0.5)),
            hovertemplate="구간 %{x:,.0f}만원<br>%{y}개<extra></extra>",
        )
    )
    apply_dark_theme(fig, margin=dict(l=48, r=16, t=10, b=40))
    fig.update_xaxes(title=dict(text="갭 (만원)", font=dict(size=10)))
    fig.update_yaxes(title=dict(text="단지 수", font=dict(size=10)))
    fig.update_layout(showlegend=False)
    return fig


@callback(
    Output("page-invest-scope", "children"),
    Output("kpi-invest-jeonse-v", "children"),
    Output("kpi-invest-gap-v", "children"),
    Output("kpi-invest-conv-v", "children"),
    Output("kpi-invest-cutoff-v", "children"),
    Output(f"{_MAP_ID}-geojson", "hideout"),
    Output("page-invest-gap-hist", "figure"),
    Output("page-invest-rank-grid", "rowData"),
    Input("f-sido", "value"),
    Input("f-sgg", "value"),
)
def _refresh_invest(sido, sgg):
    sido = sido or "서울특별시"
    scope_label = (
        f"{sido} · {sgg}"
        if sgg and sgg != "전체"
        else sido
    )

    # ---- sgg-level aggregate ----
    try:
        sgg_df = iq.invest_by_sgg(sido)
    except Exception:
        sgg_df = pd.DataFrame(columns=[
            "sido", "sgg", "complex_count", "jeonse_ratio", "median_gap", "conversion_rate",
        ])

    if sgg and sgg != "전체":
        row = sgg_df.loc[sgg_df["sgg"] == sgg]
        if not row.empty:
            jeonse_v = format_percent(row["jeonse_ratio"].iloc[0])
            gap_v = format_won(row["median_gap"].iloc[0])
            conv_v = format_percent(row["conversion_rate"].iloc[0])
        else:
            jeonse_v = gap_v = conv_v = "—"
    elif sgg_df.empty:
        jeonse_v = gap_v = conv_v = "—"
    else:
        jeonse_v = format_percent(sgg_df["jeonse_ratio"].mean())
        gap_v = format_won(sgg_df["median_gap"].median())
        conv_v = format_percent(sgg_df["conversion_rate"].mean())

    # ---- map (전세가율 choropleth) ----
    db_values = (
        dict(zip(sgg_df["sgg"], (sgg_df["jeonse_ratio"].fillna(0) * 100)))
        if not sgg_df.empty
        else {}
    )
    values_by_sgg = collapse_db_sgg_to_geo(db_values, aggregator="mean")
    map_hideout = build_hideout(
        values_by_sgg,
        color_scale="Greens",
        selected_sgg=sgg if sgg and sgg != "전체" else None,
        sido=sido,
    )

    # ---- per-complex: histogram + ranking ----
    try:
        cplx_df = iq.invest_by_complex(
            sido=sido,
            sgg=sgg if sgg and sgg != "전체" else None,
            limit=500,
        )
    except Exception:
        cplx_df = pd.DataFrame(columns=[
            "apt_id", "apt_name", "sido", "sgg", "median_sale", "median_jeonse",
            "sale_count", "jeonse_count", "gap", "jeonse_ratio", "attractiveness_score",
        ])

    if cplx_df.empty or cplx_df["attractiveness_score"].isna().all():
        cutoff_v = "—"
    else:
        cutoff_v = f"{cplx_df['attractiveness_score'].quantile(0.9):.1f}"

    hist_fig = _build_gap_hist(cplx_df)
    row_data = cplx_df.to_dict("records")

    return (
        scope_label,
        jeonse_v, gap_v, conv_v, cutoff_v,
        map_hideout,
        hist_fig,
        row_data,
    )

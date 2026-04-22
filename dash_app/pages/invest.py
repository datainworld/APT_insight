"""투자 지표 페이지 (/invest) — 스펙 3.5.

전세가율 choropleth + 갭 분포 히스토그램 + 매력도 점수 랭킹.
매력도 점수는 단순화된 공식 (스펙 5.1 glossary 참조). 호가 표준편차 항은 Phase 후속에서 추가.
"""

from __future__ import annotations

import dash
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, callback, clientside_callback, dcc, html
from dash.exceptions import PreventUpdate

from dash_app.components.choropleth_map import ChoroplethMap, build_hideout
from dash_app.components.formatters import format_percent, format_ppm2
from dash_app.components.kpi_card import KpiCard
from dash_app.components.ranking_table import RankingTable
from dash_app.geo_names import collapse_db_sgg_to_geo
from dash_app.queries import invest_queries as iq
from dash_app.theme import ACCENT_1, ACCENT_2, apply_dark_theme

dash.register_page(
    __name__,
    path="/invest",
    name="투자 지표",
    order=5,
    title="APT Insight — 투자 지표",
)


_MAP_ID = "page-invest-map"
# 주의: 단지 내 다면적 혼재로 "단지 평균가" 는 왜곡됨 → 전부 단위면적가(만원/㎡) 기준.
_TABLE_COLUMNS: list[dict] = [
    {"field": "apt_name", "headerName": "단지", "minWidth": 180,
     "cellStyle": {"cursor": "pointer", "color": "#4facfe"}},
    {"field": "sgg", "headerName": "자치구", "minWidth": 100},
    {"field": "jeonse_ratio", "headerName": "전세가율", "minWidth": 110, "type": "numericColumn",
     "valueFormatter": {"function": "params.value == null ? '—' : (params.value * 100).toFixed(1) + '%'"}},
    {"field": "gap_ppm2", "headerName": "갭 (만원/㎡)", "minWidth": 120, "type": "numericColumn",
     "valueFormatter": {"function": "params.value == null ? '—' : d3.format(',.0f')(params.value)"}},
    {"field": "median_sale_ppm2", "headerName": "매매 단위면적가 (만원/㎡)", "minWidth": 180, "type": "numericColumn",
     "valueFormatter": {"function": "params.value == null ? '—' : d3.format(',.0f')(params.value)"}},
    {"field": "median_jeonse_ppm2", "headerName": "전세 보증금 (만원/㎡)", "minWidth": 170, "type": "numericColumn",
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


def _intent_caption() -> html.Div:
    return html.Div(
        style={
            "color": "var(--fg-1)",
            "fontSize": 12,
            "padding": "10px 12px",
            "lineHeight": 1.6,
            "background": "rgba(79,172,254,.08)",
            "borderLeft": "3px solid var(--accent-1)",
            "borderRadius": "4px",
        },
        children=(
            "이 페이지는 갭투자(매매가에서 전세 보증금을 뺀 차액만 부담하고 매수) 관점에서 "
            "자치구·단지를 평가합니다. 전세가율이 높고 갭이 작을수록 자기자본 부담이 적은 단지입니다."
        ),
    )


def _kpi_strip() -> html.Div:
    return html.Div(
        className="kpi-strip",
        children=[
            KpiCard("현재 전세가율 (최근 월)", value_id="kpi-invest-jeonse-v", term="전세가율"),
            KpiCard(
                "중위 갭 (단위면적)",
                value_id="kpi-invest-gap-v",
                detail_id="kpi-invest-gap-d",
                term="갭",
            ),
            KpiCard("전월세전환율", value_id="kpi-invest-conv-v", term="전월세전환율"),
            KpiCard(
                "전세가율 70%↑ 단지 수",
                value_id="kpi-invest-cutoff-v",
                term="전세가율",
            ),
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
                    html.Div(className="t", children="갭 분포 (단위면적)"),
                    html.Div(
                        className="s",
                        children="단위면적가 기준 (만원/㎡) · 단지 수",
                        style={
                            "color": "var(--fg-1)",
                            "background": "rgba(79,172,254,.10)",
                            "padding": "4px 10px",
                            "borderRadius": "999px",
                            "border": "1px solid rgba(79,172,254,.25)",
                        },
                    ),
                ],
            ),
            dcc.Graph(
                id="page-invest-gap-hist",
                config={"displayModeBar": False, "responsive": True},
                style={"height": 440},
            ),
        ],
    )


def _trend_card() -> html.Div:
    return html.Div(
        className="card",
        children=[
            html.Div(
                className="card-head",
                children=[
                    html.Div(className="ic", children=html.I(className="fa-solid fa-chart-line")),
                    html.Div(
                        className="t",
                        id="page-invest-trend-title",
                        children="36개월 전세가율 추이",
                    ),
                    html.Div(
                        className="s",
                        children="월별 전세 보증금 중위 ÷ 매매 중위 (단위면적가 기준)",
                        style={
                            "color": "var(--fg-1)",
                            "background": "rgba(79,172,254,.10)",
                            "padding": "4px 10px",
                            "borderRadius": "999px",
                            "border": "1px solid rgba(79,172,254,.25)",
                        },
                    ),
                ],
            ),
            html.Div(
                style={
                    "color": "var(--fg-1)",
                    "fontSize": 12,
                    "padding": "10px 12px",
                    "marginTop": 8,
                    "lineHeight": 1.6,
                    "background": "rgba(79,172,254,.08)",
                    "borderLeft": "3px solid var(--accent-1)",
                    "borderRadius": "4px",
                },
                children=(
                    "전세가율이 70% 이상으로 올라갈수록 갭(자기자본 부담)이 작아져 갭투자에 유리해집니다. "
                    "라인이 우상향이면 매매가 대비 전세가가 따라오는 시기, 우하향이면 매매가가 더 빠르게 오르는 시기입니다."
                ),
            ),
            dcc.Graph(
                id="page-invest-trend",
                config={"displayModeBar": False, "responsive": True},
                style={"height": 320, "marginTop": 4},
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
                    html.Div(
                        className="s",
                        children="상위 500 단지",
                        style={
                            "color": "var(--fg-1)",
                            "background": "rgba(79,172,254,.10)",
                            "padding": "4px 10px",
                            "borderRadius": "999px",
                            "border": "1px solid rgba(79,172,254,.25)",
                        },
                    ),
                ],
            ),
            html.Div(
                style={
                    "color": "var(--fg-1)",
                    "fontSize": 12,
                    "padding": "10px 12px",
                    "marginTop": 8,
                    "marginBottom": 8,
                    "lineHeight": 1.6,
                    "background": "rgba(79,172,254,.08)",
                    "borderLeft": "3px solid var(--accent-1)",
                    "borderRadius": "4px",
                },
                children=[
                    html.B("매력도 점수 산출 (70점 만점, 자체 합성 참고 지표)"),
                    html.Br(),
                    "전세가율 점수 (40점) + 거래 활성도 점수 (30점). ",
                    "전세가율 100%면 40점 만점, 6개월 거래 30건↑이면 30점 만점입니다. ",
                    "호가 안정성 항(30점)은 후속 추가 예정으로 현재 70점 만점이며, 투자 결정의 참고 지표로만 사용해 주세요.",
                ],
            ),
            RankingTable(
                "page-invest-rank",
                _TABLE_COLUMNS,
                row_data=[],
                page_size=25,
                height=440,
                row_selection="single",
                get_row_id="params.data.apt_id",
            ),
        ],
    )


layout = html.Main(
    className="fd-main",
    children=[
        _page_head(),
        _intent_caption(),
        _kpi_strip(),
        _trend_card(),
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
        # clientside navigate callback dummy output
        html.Div(id="page-invest-nav-dummy", style={"display": "none"}),
    ],
)


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------


def _build_trend(df: pd.DataFrame) -> go.Figure:
    """월별 전세가율 라인 + 70% 임계 horizontal 가이드."""
    fig = go.Figure()
    if df.empty or df["jeonse_ratio"].isna().all():
        fig.add_annotation(
            text="데이터 없음", showarrow=False, font=dict(color="#777"),
            xref="paper", yref="paper", x=0.5, y=0.5,
        )
        return apply_dark_theme(fig, margin=dict(l=10, r=10, t=10, b=10))

    pct = df["jeonse_ratio"] * 100
    fig.add_trace(
        go.Scatter(
            x=df["ym"], y=pct,
            mode="lines+markers",
            name="전세가율",
            line=dict(color=ACCENT_1, width=2, shape="spline"),
            marker=dict(size=5),
            customdata=df[["sale_count", "jeonse_count"]].fillna(0),
            hovertemplate=(
                "%{x|%Y-%m}<br>전세가율 %{y:.1f}%<br>"
                "매매 %{customdata[0]:.0f}건 · 전세 %{customdata[1]:.0f}건<extra></extra>"
            ),
        )
    )
    fig.add_hline(
        y=70, line=dict(color="rgba(255,255,255,.35)", width=1, dash="dot"),
        annotation_text="70% 임계", annotation_position="top right",
        annotation_font=dict(size=10, color="#aaa"),
    )

    apply_dark_theme(fig, margin=dict(l=56, r=16, t=10, b=40))
    fig.update_xaxes(type="date", tickformat="%Y-%m")
    fig.update_yaxes(title=dict(text="전세가율 (%)", font=dict(size=10)))
    return fig


def _build_gap_hist(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if df.empty or df["gap_ppm2"].isna().all():
        fig.add_annotation(
            text="데이터 없음", showarrow=False, font=dict(color="#777"),
            xref="paper", yref="paper", x=0.5, y=0.5,
        )
        return apply_dark_theme(fig, margin=dict(l=10, r=10, t=10, b=10))
    gaps = df["gap_ppm2"].dropna()
    fig.add_trace(
        go.Histogram(
            x=gaps,
            nbinsx=40,
            marker=dict(color=ACCENT_2, line=dict(color="#0c2630", width=0.5)),
            hovertemplate="구간 %{x:,.0f}만원/㎡<br>%{y}개<extra></extra>",
        )
    )
    apply_dark_theme(fig, margin=dict(l=48, r=16, t=10, b=40))
    fig.update_xaxes(title=dict(text="갭 (만원/㎡)", font=dict(size=10)))
    fig.update_yaxes(title=dict(text="단지 수", font=dict(size=10)))
    fig.update_layout(showlegend=False)
    return fig


@callback(
    Output("page-invest-scope", "children"),
    Output("kpi-invest-jeonse-v", "children"),
    Output("kpi-invest-gap-v", "children"),
    Output("kpi-invest-gap-d", "children"),
    Output("kpi-invest-conv-v", "children"),
    Output("kpi-invest-cutoff-v", "children"),
    Output(f"{_MAP_ID}-geojson", "hideout"),
    Output("page-invest-trend", "figure"),
    Output("page-invest-trend-title", "children"),
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

    # ---- 시계열 (KPI 1 + 차트 공용) ----
    try:
        trend_df = iq.jeonse_ratio_monthly(
            sido=sido,
            sgg=sgg if sgg and sgg != "전체" else None,
        )
    except Exception:
        trend_df = pd.DataFrame(columns=[
            "ym", "median_sale_ppm2", "median_jeonse_ppm2", "jeonse_ratio",
            "sale_count", "jeonse_count",
        ])

    # KPI 1: 시계열 마지막 월의 시장 전체 전세가율 — 차트 마지막 점과 동일
    if not trend_df.empty and not trend_df["jeonse_ratio"].isna().all():
        jeonse_v = format_percent(trend_df["jeonse_ratio"].dropna().iloc[-1])
    else:
        jeonse_v = "—"

    # ---- sgg-level aggregate (KPI 2,3 + choropleth) ----
    try:
        sgg_df = iq.invest_by_sgg(sido)
    except Exception:
        sgg_df = pd.DataFrame(columns=[
            "sido", "sgg", "complex_count", "jeonse_ratio", "median_gap_ppm2", "conversion_rate",
        ])

    gap_raw: float | None = None
    if sgg and sgg != "전체":
        row = sgg_df.loc[sgg_df["sgg"] == sgg]
        if not row.empty:
            gap_raw = row["median_gap_ppm2"].iloc[0]
            gap_v = format_ppm2(gap_raw)
            conv_v = format_percent(row["conversion_rate"].iloc[0])
        else:
            gap_v = conv_v = "—"
    elif sgg_df.empty:
        gap_v = conv_v = "—"
    else:
        gap_raw = sgg_df["median_gap_ppm2"].median()
        gap_v = format_ppm2(gap_raw)
        conv_v = format_percent(sgg_df["conversion_rate"].mean())

    # 84㎡ 환산 보조 표시 (참고용)
    if gap_raw is not None and not pd.isna(gap_raw) and gap_raw > 0:
        gap_d = f"84㎡ 환산 ≈ {float(gap_raw) * 84 / 10000:.1f}억"
    else:
        gap_d = " "

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
        metric="jeonse",
        metric_label="전세가율",
        value_format="percent",
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
            "apt_id", "apt_name", "sido", "sgg", "median_sale_ppm2", "median_jeonse_ppm2",
            "sale_count", "jeonse_count", "gap_ppm2", "jeonse_ratio", "attractiveness_score",
        ])

    # 갭투자 후보 단지 수 — 전세가율 70% 이상 (글로서리 정의 기준)
    if cplx_df.empty or cplx_df["jeonse_ratio"].isna().all():
        cutoff_v = "—"
    else:
        n = int((cplx_df["jeonse_ratio"] >= 0.70).sum())
        cutoff_v = f"{n}개"

    hist_fig = _build_gap_hist(cplx_df)
    row_data = cplx_df.to_dict("records")

    trend_fig = _build_trend(trend_df)
    scope = sgg if sgg and sgg != "전체" else sido
    trend_title = [
        "36개월 전세가율 추이 · ",
        html.Span(scope, style={"color": "var(--accent-1)", "fontWeight": 600}),
    ]

    return (
        scope_label,
        jeonse_v, gap_v, gap_d, conv_v, cutoff_v,
        map_hideout,
        trend_fig, trend_title,
        hist_fig,
        row_data,
    )


@callback(
    Output("f-sgg", "value", allow_duplicate=True),
    Input(f"{_MAP_ID}-geojson", "clickData"),
    State("_url", "pathname"),
    prevent_initial_call=True,
)
def _map_click_to_sgg(click, pathname):
    """choropleth 자치구 클릭 → 사이드바 f-sgg 필터 set."""
    if pathname != "/invest" or not click:
        raise PreventUpdate
    name = (click.get("properties") or {}).get("name")
    if not name:
        raise PreventUpdate
    return name


# 랭킹 row 클릭 → /complex?apt_id=... navigate (clientside)
clientside_callback(
    """
    function(selected) {
        if (!selected || !selected.length) {
            return window.dash_clientside.no_update;
        }
        const apt_id = (selected[0] || {}).apt_id;
        if (!apt_id) return window.dash_clientside.no_update;
        window.location.assign('/complex?apt_id=' + encodeURIComponent(apt_id));
        return window.dash_clientside.no_update;
    }
    """,
    Output("page-invest-nav-dummy", "children"),
    Input("page-invest-rank-grid", "selectedRows"),
    prevent_initial_call=True,
)

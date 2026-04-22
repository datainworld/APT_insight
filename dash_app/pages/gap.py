"""실거래가 vs 호가 페이지 (/gap) — 스펙 3.4.

복합 매핑이 된 단지만 대상으로 집계한다 (매핑 없는 단지는 제외).
페이지 상단 '분석 가능 …' 배지로 이 한계를 사용자에게 노출한다.
"""

from __future__ import annotations

import dash
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, callback, clientside_callback, dcc, html
from dash.exceptions import PreventUpdate

from dash_app.components.choropleth_map import ChoroplethMap, build_hideout
from dash_app.components.formatters import format_count, format_percent
from dash_app.components.kpi_card import KpiCard
from dash_app.geo_names import collapse_db_sgg_to_geo
from dash_app.queries import gap_queries as gapq
from dash_app.queries import mapping_queries as mapq
from dash_app.theme import ACCENT_1, NEG, apply_dark_theme

dash.register_page(
    __name__,
    path="/gap",
    name="실거래가 vs 호가",
    order=3,
    title="APT Insight — 실거래가 vs 호가",
)


_MAP_ID = "page-gap-map"


def _page_head() -> html.Div:
    return html.Div(
        className="page-head",
        children=[
            html.H1("실거래가 vs 호가"),
            html.Div(
                className="live",
                children=[
                    html.Span(className="dot-live"),
                    html.Span(id="page-gap-cover", children="분석 가능 —"),
                ],
            ),
        ],
    )


def _kpi_strip() -> html.Div:
    return html.Div(
        className="kpi-strip",
        children=[
            KpiCard("평균 괴리율", value_id="kpi-gap-avg-v", term="호가_괴리율"),
            KpiCard("호가 과열 의심 단지 (>10%)", value_id="kpi-gap-suspect-v"),
            KpiCard("매물 평균 노출일", value_id="kpi-gap-days-v"),
        ],
    )


def _right_panel() -> html.Div:
    return html.Div(
        className="card",
        children=[
            html.Div(
                className="card-head",
                children=[
                    html.Div(className="ic", children=html.I(className="fa-solid fa-ranking-star")),
                    html.Div(className="t", id="page-gap-top-title", children="호가 거품 TOP 10"),
                    dcc.RadioItems(
                        id="page-gap-top-mode",
                        options=[
                            {"label": "호가 거품", "value": "bubble"},
                            {"label": "저평가", "value": "under"},
                        ],
                        value="bubble",
                        inline=True,
                        labelStyle={
                            "marginRight": 14,
                            "cursor": "pointer",
                            "fontSize": 13,
                            "color": "var(--fg-1)",
                            "fontWeight": 500,
                            "display": "inline-flex",
                            "alignItems": "center",
                            "gap": 6,
                        },
                        inputStyle={"accentColor": "var(--accent-1)", "cursor": "pointer"},
                        style={"marginLeft": "auto", "flexShrink": 0},
                        persistence=True,
                        persistence_type="session",
                    ),
                ],
            ),
            dcc.Graph(
                id="page-gap-top",
                config={"displayModeBar": False, "responsive": True},
                style={"height": 420},
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
                        id="page-gap-trend-title",
                        children="36개월 호가 vs 실거래 추이",
                    ),
                    html.Div(
                        className="s",
                        id="page-gap-trend-sub",
                        children="월별 신규 등록 매물 호가 평균 vs 같은 월 실거래 중위",
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
                    "두 라인의 격차가 시장 심리입니다. 호가가 실거래보다 크게 위에 있으면 매도자 강세, "
                    "격차가 좁아지거나 호가가 내려오면 시장이 식는 신호입니다."
                ),
            ),
            dcc.Graph(
                id="page-gap-trend",
                config={"displayModeBar": False, "responsive": True},
                style={"height": 320, "marginTop": 4},
            ),
        ],
    )


def _bottom_scatter() -> html.Div:
    return html.Div(
        className="card",
        children=[
            html.Div(
                className="card-head",
                children=[
                    html.Div(className="ic", children=html.I(className="fa-solid fa-chart-scatter")),
                    html.Div(className="t", children="실거래 vs 호가 비교"),
                    html.Div(
                        className="s",
                        children="x = 실거래 단위면적가 · y = 호가 단위면적가 · 점 크기 = 6개월 거래 건수 · 점 색 = 매물 평균 노출일",
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
                    "회색 점선(y=x) 위쪽 단지일수록 호가가 실거래보다 높습니다 (호가 거품 가능성). "
                    "아래쪽 단지는 호가가 실거래보다 낮은 저평가 가능성입니다. "
                    "점이 클수록 거래가 활발해 신뢰도가 높고, 점 색이 진할수록 매물이 시장에 오래 노출됨(거래 침체 신호)을 의미합니다. "
                    "단지 점을 클릭하면 단지 상세 페이지로 이동합니다."
                ),
            ),
            dcc.Graph(
                id="page-gap-scatter",
                config={
                    "displayModeBar": True,
                    "displaylogo": False,
                    "scrollZoom": True,
                    "modeBarButtonsToRemove": [
                        "lasso2d", "select2d", "autoScale2d", "toggleSpikelines",
                    ],
                    "responsive": True,
                },
                style={"height": 420, "marginTop": 4},
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
            "현재 활성 매물의 호가가 최근 6개월 실거래가보다 얼마나 높거나 낮은지 비교합니다. "
            "호가가 실거래보다 크면 호가 거품, 작으면 저평가 가능성. "
            "TOP 10 단지나 분포 차트의 점을 클릭하면 단지 상세 페이지로 이동합니다."
        ),
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
                    children=[ChoroplethMap(_MAP_ID, {}, color_scale="Reds", height=440)],
                ),
                _right_panel(),
            ],
        ),
        _bottom_scatter(),
        # clientside navigate callback 의 dummy output
        html.Div(id="page-gap-nav-dummy", style={"display": "none"}),
    ],
)


# ---------------------------------------------------------------------------
# Charts (page-local helpers — 기존 charts 모듈에 이 페이지 전용 차트를 섞지 않는다)
# ---------------------------------------------------------------------------


def _build_trend(df: pd.DataFrame) -> go.Figure:
    """월별 호가 평균 / 실거래 중위 두 라인."""
    fig = go.Figure()
    if df.empty:
        fig.add_annotation(
            text="데이터 없음", showarrow=False, font=dict(color="#777"),
            xref="paper", yref="paper", x=0.5, y=0.5,
        )
        return apply_dark_theme(fig, margin=dict(l=10, r=10, t=10, b=10))

    fig.add_trace(
        go.Scatter(
            x=df["ym"], y=df["median_trade_ppm2"],
            mode="lines+markers",
            name="실거래 중위",
            line=dict(color=ACCENT_1, width=2, shape="spline"),
            marker=dict(size=5),
            customdata=df[["trade_count"]].fillna(0),
            hovertemplate="%{x|%Y-%m}<br>실거래 중위 %{y:,.0f}만원/㎡ (%{customdata[0]:.0f}건)<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df["ym"], y=df["avg_ask_ppm2"],
            mode="lines+markers",
            name="호가 평균 (신규 등록)",
            line=dict(color=NEG, width=2, shape="spline", dash="dot"),
            marker=dict(size=5),
            customdata=df[["listing_count"]].fillna(0),
            hovertemplate="%{x|%Y-%m}<br>호가 평균 %{y:,.0f}만원/㎡ (%{customdata[0]:.0f}건)<extra></extra>",
        )
    )

    apply_dark_theme(fig, margin=dict(l=56, r=16, t=10, b=40))
    fig.update_yaxes(title=dict(text="단위면적가 (만원/㎡)", font=dict(size=10)))
    fig.update_xaxes(type="date", tickformat="%Y-%m")
    fig.update_layout(legend=dict(orientation="h", x=0, y=1.10, font=dict(size=11)))
    return fig


def _build_top_bar(df: pd.DataFrame, mode: str = "bubble") -> go.Figure:
    """mode='bubble' → 양수 괴리 큰 순(빨강). mode='under' → 음수 괴리 큰 순(파랑)."""
    fig = go.Figure()
    if df.empty:
        fig.add_annotation(
            text="데이터 없음", showarrow=False, font=dict(color="#777"),
            xref="paper", yref="paper", x=0.5, y=0.5,
        )
        return apply_dark_theme(fig, margin=dict(l=10, r=10, t=10, b=10))

    if mode == "under":
        sub = df[df["gap_ratio"] < 0].nsmallest(10, "gap_ratio").iloc[::-1]
        colorscale = "Blues"  # 절댓값↑ → 짙음 (거품 모드 Reds 와 일관)
    else:
        sub = df.nlargest(10, "gap_ratio").iloc[::-1]
        colorscale = "Reds"

    if sub.empty:
        msg = "저평가 단지 없음" if mode == "under" else "데이터 없음"
        fig.add_annotation(
            text=msg, showarrow=False, font=dict(color="#777"),
            xref="paper", yref="paper", x=0.5, y=0.5,
        )
        return apply_dark_theme(fig, margin=dict(l=10, r=10, t=10, b=10))

    pct = (sub["gap_ratio"] * 100).round(2)
    labels = pct.map(lambda v: f"{v:+.2f}%")
    fig.add_trace(
        go.Bar(
            x=pct,
            y=sub["apt_name"],
            orientation="h",
            marker=dict(color=sub["gap_ratio"].abs(), colorscale=colorscale),
            text=labels,
            textposition="inside",
            insidetextanchor="end",
            textfont=dict(size=14),
            customdata=sub[["sgg", "apt_id"]],
            hovertemplate=(
                "<b>%{y}</b> · %{customdata[0]}<br>"
                "괴리율 %{x:.2f}%<br><i>클릭 시 단지 상세로 이동</i><extra></extra>"
            ),
        )
    )
    apply_dark_theme(fig, margin=dict(l=160, r=16, t=8, b=32))
    fig.update_xaxes(title=dict(text="괴리율 (%)", font=dict(size=12)))
    fig.update_yaxes(tickfont=dict(size=14))
    return fig


def _build_scatter(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="데이터 없음", showarrow=False, font=dict(color="#777"),
            xref="paper", yref="paper", x=0.5, y=0.5,
        )
        return apply_dark_theme(fig, margin=dict(l=10, r=10, t=10, b=10))
    sizes = (df["trade_count"].fillna(1).clip(lower=1) ** 0.5) * 3 + 5
    days = df["avg_days_listed"].fillna(0).clip(lower=0)
    fig = go.Figure(
        go.Scatter(
            x=df["median_trade_ppm2"],
            y=df["avg_ask_ppm2"],
            mode="markers",
            marker=dict(
                size=sizes,
                color=days,
                colorscale="Oranges",
                colorbar=dict(title=dict(text="매물<br>평균<br>노출일", font=dict(size=10)), thickness=10),
                line=dict(color="rgba(255,255,255,.2)", width=0.5),
                opacity=0.75,
            ),
            customdata=df[["apt_name", "sgg", "trade_count", "apt_id", "gap_ratio"]],
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "%{customdata[1]} · 거래 %{customdata[2]}건 · 노출 %{marker.color:.0f}일<br>"
                "실거래 단위면적 중위 %{x:,.0f}만원/㎡ · "
                "호가 단위면적 평균 %{y:,.0f}만원/㎡<br>"
                "괴리 %{customdata[4]:.1%}<br>"
                "<i>클릭 시 단지 상세로 이동</i><extra></extra>"
            ),
        )
    )
    # y=x 대각선 보조 (호가=실거래 단위면적가일 때)
    lo = float(min(df["median_trade_ppm2"].min(), df["avg_ask_ppm2"].min()))
    hi = float(max(df["median_trade_ppm2"].max(), df["avg_ask_ppm2"].max()))
    fig.add_shape(
        type="line", x0=lo, y0=lo, x1=hi, y1=hi,
        line=dict(color="rgba(255,255,255,.25)", width=1, dash="dot"),
    )
    apply_dark_theme(fig, margin=dict(l=56, r=16, t=10, b=40))
    fig.update_xaxes(title=dict(text="실거래 단위면적 중위 (만원/㎡)", font=dict(size=10)))
    fig.update_yaxes(title=dict(text="호가 단위면적 평균 (만원/㎡)", font=dict(size=10)))
    return fig


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------


@callback(
    Output("page-gap-cover", "children"),
    Output("kpi-gap-avg-v", "children"),
    Output("kpi-gap-suspect-v", "children"),
    Output("kpi-gap-days-v", "children"),
    Output(f"{_MAP_ID}-geojson", "hideout"),
    Output("page-gap-trend", "figure"),
    Output("page-gap-trend-title", "children"),
    Output("page-gap-top", "figure"),
    Output("page-gap-top-title", "children"),
    Output("page-gap-scatter", "figure"),
    Input("f-sido", "value"),
    Input("f-sgg", "value"),
    Input("page-gap-top-mode", "value"),
)
def _refresh_gap(sido, sgg, top_mode):
    sido = sido or "서울특별시"

    # ---- cover badge ----
    try:
        cover = mapq.get_mapping_cover_rate()
        cover_txt = (
            f"분석 가능 {cover['cover_rate']:.0%} "
            f"({cover['mapped']:,}/{cover['total']:,} 단지)"
        )
    except Exception:
        cover_txt = "분석 가능 —"

    # ---- sgg-level aggregate (for KPI + map) ----
    try:
        sgg_df = gapq.gap_ratio_by_sgg(sido)
    except Exception:
        sgg_df = pd.DataFrame(
            columns=["sido", "sgg", "mapped_count", "avg_gap_ratio", "suspect_count", "avg_days_listed"],
        )

    if sgg and sgg != "전체":
        row = sgg_df.loc[sgg_df["sgg"] == sgg]
        if not row.empty:
            avg_v = format_percent(row["avg_gap_ratio"].iloc[0])
            suspect_v = format_count(row["suspect_count"].iloc[0])
            days_v = format_count(int(row["avg_days_listed"].iloc[0] or 0))
        else:
            avg_v = suspect_v = days_v = "—"
    else:
        if sgg_df.empty:
            avg_v = suspect_v = days_v = "—"
        else:
            avg_v = format_percent(sgg_df["avg_gap_ratio"].mean())
            suspect_v = format_count(int(sgg_df["suspect_count"].sum()))
            days_v = format_count(int(sgg_df["avg_days_listed"].mean() or 0))

    # ---- map ----
    db_values = (
        dict(zip(sgg_df["sgg"], (sgg_df["avg_gap_ratio"].fillna(0) * 100).clip(lower=0)))
        if not sgg_df.empty
        else {}
    )
    values_by_sgg = collapse_db_sgg_to_geo(db_values, aggregator="mean")
    map_hideout = build_hideout(
        values_by_sgg,
        color_scale="Reds",
        selected_sgg=sgg if sgg and sgg != "전체" else None,
        sido=sido,
        metric="gap",
        metric_label="평균 괴리율",
        value_format="percent",
    )

    # ---- per-complex (TOP + scatter) ----
    try:
        cplx_df = gapq.gap_ratio_by_complex(
            sido=sido,
            sgg=sgg if sgg and sgg != "전체" else None,
            limit=500,
        )
    except Exception:
        cplx_df = pd.DataFrame(
            columns=[
                "apt_id", "apt_name", "sido", "sgg", "latitude", "longitude", "build_year",
                "median_trade_ppm2", "avg_ask_ppm2", "trade_count", "active_count",
                "avg_days_listed", "gap_ratio",
            ]
        )

    mode = top_mode or "bubble"
    if mode == "under":
        # 저평가는 별도 쿼리 (기본 쿼리는 거품 우선 정렬이라 음수 단지가 거의 안 들어옴)
        try:
            top_df = gapq.gap_ratio_by_complex(
                sido=sido,
                sgg=sgg if sgg and sgg != "전체" else None,
                limit=20,
                ascending=True,
            )
        except Exception:
            top_df = pd.DataFrame(columns=cplx_df.columns)
    else:
        top_df = cplx_df
    top_fig = _build_top_bar(top_df, mode=mode)
    top_title = "저평가 TOP 10" if mode == "under" else "호가 거품 TOP 10"
    scatter_fig = _build_scatter(cplx_df)

    # ---- 시계열 ----
    try:
        trend_df = gapq.gap_ratio_monthly(
            sido=sido,
            sgg=sgg if sgg and sgg != "전체" else None,
        )
    except Exception:
        trend_df = pd.DataFrame(columns=["ym", "avg_ask_ppm2", "median_trade_ppm2", "listing_count", "trade_count"])
    trend_fig = _build_trend(trend_df)
    scope = sgg if sgg and sgg != "전체" else sido
    trend_title = [
        "36개월 호가 vs 실거래 추이 · ",
        html.Span(
            scope,
            style={"color": "var(--accent-1)", "fontWeight": 600},
        ),
    ]

    return (
        cover_txt, avg_v, suspect_v, days_v, map_hideout,
        trend_fig, trend_title,
        top_fig, top_title, scatter_fig,
    )


@callback(
    Output("f-sgg", "value", allow_duplicate=True),
    Input(f"{_MAP_ID}-geojson", "clickData"),
    State("_url", "pathname"),
    prevent_initial_call=True,
)
def _map_click_to_sgg(click, pathname):
    """choropleth 자치구 클릭 → 사이드바 f-sgg 필터에 반영."""
    if pathname != "/gap" or not click:
        raise PreventUpdate
    name = (click.get("properties") or {}).get("name")
    if not name:
        raise PreventUpdate
    return name


# TOP/scatter 클릭 → /complex?apt_id=... 로 페이지 이동.
# server-side 에서 _url.href set 시 dash router 가 잘 트리거되지 않는 케이스가 있어
# clientside 에서 window.location.assign 으로 직접 navigate.
clientside_callback(
    """
    function(top_click, scatter_click) {
        const ctx = window.dash_clientside.callback_context;
        if (!ctx.triggered.length) return window.dash_clientside.no_update;
        const trig = ctx.triggered[0];
        const click = trig.value;
        if (!click || !click.points || !click.points.length) {
            return window.dash_clientside.no_update;
        }
        const cd = click.points[0].customdata || [];
        const isTop = trig.prop_id.startsWith('page-gap-top');
        const apt_id = isTop ? cd[1] : cd[3];
        if (!apt_id) return window.dash_clientside.no_update;
        window.location.assign('/complex?apt_id=' + encodeURIComponent(apt_id));
        return window.dash_clientside.no_update;
    }
    """,
    Output("page-gap-nav-dummy", "children"),
    Input("page-gap-top", "clickData"),
    Input("page-gap-scatter", "clickData"),
    prevent_initial_call=True,
)

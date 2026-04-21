"""호가 괴리 페이지 (/gap) — 스펙 3.4.

복잡 매핑이 된 단지만 대상으로 집계한다 (매핑 없는 단지는 제외).
페이지 상단 `cover 81%` 배지로 이 한계를 사용자에게 노출한다.
"""

from __future__ import annotations

import dash
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, callback, dcc, html

from dash_app.components.choropleth_map import ChoroplethMap, build_hideout
from dash_app.components.formatters import format_count, format_percent
from dash_app.components.kpi_card import KpiCard
from dash_app.geo_names import collapse_db_sgg_to_geo
from dash_app.queries import gap_queries as gapq
from dash_app.queries import mapping_queries as mapq
from dash_app.theme import apply_dark_theme

dash.register_page(
    __name__,
    path="/gap",
    name="호가 괴리",
    order=4,
    title="APT Insight — 호가 괴리",
)


_MAP_ID = "page-gap-map"


def _page_head() -> html.Div:
    return html.Div(
        className="page-head",
        children=[
            html.H1("호가 괴리"),
            html.Div(
                className="live",
                children=[
                    html.Span(className="dot-live"),
                    html.Span(id="page-gap-cover", children="cover —"),
                ],
            ),
        ],
    )


def _kpi_strip() -> html.Div:
    return html.Div(
        className="kpi-strip",
        children=[
            KpiCard("평균 괴리율", value_id="kpi-gap-avg-v", term="호가_괴리율"),
            KpiCard("의심 단지 수 (>10%)", value_id="kpi-gap-suspect-v"),
            KpiCard("평균 노출 기간 (일)", value_id="kpi-gap-days-v"),
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
                    html.Div(className="t", children="괴리율 TOP 20"),
                    html.Div(className="s", children="양수 큰 순"),
                ],
            ),
            dcc.Graph(
                id="page-gap-top",
                config={"displayModeBar": False, "responsive": True},
                style={"height": 440},
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
                    html.Div(className="t", children="실거래 중위값 vs 호가 평균"),
                    html.Div(
                        className="s",
                        children="x = 실거래 중위 · y = 호가 평균 · 점 크기 = 거래 6M · 색 = 괴리율",
                    ),
                ],
            ),
            dcc.Graph(
                id="page-gap-scatter",
                config={"displayModeBar": False, "responsive": True},
                style={"height": 420},
            ),
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
                    children=[ChoroplethMap(_MAP_ID, {}, color_scale="Reds", height=440)],
                ),
                _right_panel(),
            ],
        ),
        _bottom_scatter(),
    ],
)


# ---------------------------------------------------------------------------
# Charts (page-local helpers — 기존 charts 모듈에 이 페이지 전용 차트를 섞지 않는다)
# ---------------------------------------------------------------------------


def _build_top_bar(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="데이터 없음", showarrow=False, font=dict(color="#777"),
            xref="paper", yref="paper", x=0.5, y=0.5,
        )
        return apply_dark_theme(fig, margin=dict(l=10, r=10, t=10, b=10))
    top = df.head(20).iloc[::-1]  # 가로 bar — 큰 값을 위로
    fig = go.Figure(
        go.Bar(
            x=top["gap_ratio"] * 100,
            y=top["apt_name"],
            orientation="h",
            marker=dict(color=top["gap_ratio"], colorscale="Reds"),
            hovertemplate="<b>%{y}</b><br>괴리율 %{x:.1f}%<extra></extra>",
        )
    )
    apply_dark_theme(fig, margin=dict(l=120, r=16, t=8, b=32))
    fig.update_xaxes(title=dict(text="괴리율 (%)", font=dict(size=10)))
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
    fig = go.Figure(
        go.Scatter(
            x=df["median_deal"],
            y=df["avg_ask"],
            mode="markers",
            marker=dict(
                size=sizes,
                color=df["gap_ratio"] * 100,
                colorscale="Reds",
                colorbar=dict(title=dict(text="괴리 %", font=dict(size=10)), thickness=10),
                line=dict(color="rgba(255,255,255,.2)", width=0.5),
                opacity=0.75,
            ),
            customdata=df[["apt_name", "sgg", "trade_count"]],
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "%{customdata[1]} · 거래 %{customdata[2]}건<br>"
                "중위 실거래 %{x:,.0f}만원 · 호가 평균 %{y:,.0f}만원<br>"
                "괴리 %{marker.color:.1f}%<extra></extra>"
            ),
        )
    )
    # y=x 대각선 보조
    lo = float(min(df["median_deal"].min(), df["avg_ask"].min()))
    hi = float(max(df["median_deal"].max(), df["avg_ask"].max()))
    fig.add_shape(
        type="line", x0=lo, y0=lo, x1=hi, y1=hi,
        line=dict(color="rgba(255,255,255,.25)", width=1, dash="dot"),
    )
    apply_dark_theme(fig, margin=dict(l=56, r=16, t=10, b=40))
    fig.update_xaxes(title=dict(text="실거래 중위 (만원)", font=dict(size=10)))
    fig.update_yaxes(title=dict(text="호가 평균 (만원)", font=dict(size=10)))
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
    Output("page-gap-top", "figure"),
    Output("page-gap-scatter", "figure"),
    Input("f-sido", "value"),
    Input("f-sgg", "value"),
)
def _refresh_gap(sido, sgg):
    sido = sido or "서울특별시"

    # ---- cover badge ----
    try:
        cover = mapq.get_mapping_cover_rate()
        cover_txt = f"cover {cover['cover_rate']:.0%} · {cover['mapped']:,}/{cover['total']:,}"
    except Exception:
        cover_txt = "cover —"

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
                "median_deal", "avg_ask", "trade_count", "active_count", "avg_days_listed",
                "gap_ratio",
            ]
        )

    top_fig = _build_top_bar(cplx_df)
    scatter_fig = _build_scatter(cplx_df)

    return cover_txt, avg_v, suspect_v, days_v, map_hideout, top_fig, scatter_fig

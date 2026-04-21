"""지역 심층 페이지 (/region) — 스펙 3.2.

URL 동기화 (one-way): `?sgg=강남구&size=전체` 진입 시 f-sgg / f-area 스토어를 세팅.
KPI 5개 (거래량·평당가·전세가율·활성 매물·호가 괴리), choropleth, 단지 랭킹 테이블.
"""

from __future__ import annotations

from urllib.parse import parse_qs

import dash
from dash import Input, Output, State, callback, dcc, html
from dash.exceptions import PreventUpdate

from dash_app import charts
from dash_app.components.choropleth_map import ChoroplethMap, build_hideout
from dash_app.components.formatters import (
    format_count,
    format_percent,
    format_ppm2,
)
from dash_app.components.kpi_card import KpiCard
from dash_app.components.ranking_table import RankingTable
from dash_app.geo_names import collapse_db_sgg_to_geo
from dash_app.queries import gap_queries as gapq
from dash_app.queries import metrics_queries as mq
from dash_app.queries import nv_queries as nvq
from dash_app.queries import rt_queries as rtq

dash.register_page(
    __name__,
    path="/region",
    name="지역 심층",
    order=2,
    title="APT Insight — 지역 심층",
)


_MAP_ID = "page-region-map"
_TABLE_COLUMNS: list[dict] = [
    {"field": "apt_name", "headerName": "단지", "minWidth": 180,
     "cellRenderer": "markdown",
     "valueFormatter": {"function": "`[${params.value}](/complex?apt_id=${params.data.apt_id})`"}},
    {"field": "sgg", "headerName": "자치구", "minWidth": 100},
    {"field": "admin_dong", "headerName": "행정동", "minWidth": 110},
    {"field": "build_year", "headerName": "건축년도", "minWidth": 100, "type": "numericColumn"},
    {"field": "trade_count_6m", "headerName": "거래 6M", "minWidth": 100, "type": "numericColumn"},
    {"field": "trade_count_36m", "headerName": "거래 36M", "minWidth": 110, "type": "numericColumn"},
    # 단지 평균가는 다면적 혼재로 의미 없어 제거. 평당가(만원/㎡)로 면적 정규화 비교.
    {"field": "median_ppm2_6m", "headerName": "평당가(만원/㎡)", "minWidth": 140,
     "type": "numericColumn",
     "valueFormatter": {"function": "params.value == null ? '—' : d3.format(',.0f')(params.value)"}},
    {"field": "last_deal_date", "headerName": "최근거래", "minWidth": 120},
]


def _page_head() -> html.Div:
    return html.Div(
        className="page-head",
        children=[
            html.H1("지역 심층"),
            html.Div(
                className="live",
                children=[
                    html.Span(className="dot-live"),
                    html.Span(id="page-region-scope", children="—"),
                ],
            ),
        ],
    )


def _kpi_strip() -> html.Div:
    return html.Div(
        className="kpi-strip",
        children=[
            KpiCard("거래량 (6M)", value_id="kpi-region-trade-v"),
            KpiCard("평당가", value_id="kpi-region-ppm2-v", term="평당가"),
            KpiCard("전세가율", value_id="kpi-region-jeonse-v", term="전세가율"),
            KpiCard("활성 매물", value_id="kpi-region-active-v", term="활성_매물"),
            KpiCard("호가 괴리율", value_id="kpi-region-gap-v", term="호가_괴리율"),
        ],
    )


def _right_panel() -> html.Div:
    return html.Div(
        className="card",
        children=[
            html.Div(
                className="card-head",
                children=[
                    html.Div(className="ic", children=html.I(className="fa-solid fa-chart-line")),
                    html.Div(className="t", children="평당가 추이 (36M)"),
                    html.Div(className="s", children="월별 중앙값"),
                ],
            ),
            dcc.Graph(
                id="page-region-price-trend",
                config={"displayModeBar": False, "responsive": True},
                style={"height": 320},
            ),
        ],
    )


def _ranking_table_card() -> html.Div:
    return html.Div(
        className="card",
        children=[
            html.Div(
                className="card-head",
                children=[
                    html.Div(className="ic", children=html.I(className="fa-solid fa-table")),
                    html.Div(className="t", children="단지 랭킹"),
                    html.Div(
                        className="s",
                        children="컬럼 클릭 정렬 · 페이지 25 · 기본 정렬: 거래 6M ↓",
                    ),
                ],
            ),
            RankingTable("page-region-rank", _TABLE_COLUMNS, row_data=[], page_size=25, height=440),
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
                    children=[ChoroplethMap(_MAP_ID, {}, color_scale="Blues", height=440)],
                ),
                _right_panel(),
            ],
        ),
        _ranking_table_card(),
    ],
)


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------


@callback(
    Output("f-sgg", "value", allow_duplicate=True),
    Output("f-area", "value", allow_duplicate=True),
    Input("_url", "search"),
    State("_url", "pathname"),
    prevent_initial_call="initial_duplicate",
)
def _sync_from_url(search: str | None, pathname: str | None):
    """/region 진입 시 ?sgg=... &size=... 값을 필터에 반영."""
    if pathname != "/region" or not search:
        raise PreventUpdate
    qs = parse_qs(search.lstrip("?"))
    sgg = qs.get("sgg", [None])[0]
    area = qs.get("size", [None])[0]
    if not sgg and not area:
        raise PreventUpdate
    return (sgg or dash.no_update, area or dash.no_update)


@callback(
    Output("page-region-scope", "children"),
    Output("kpi-region-trade-v", "children"),
    Output("kpi-region-ppm2-v", "children"),
    Output("kpi-region-jeonse-v", "children"),
    Output("kpi-region-active-v", "children"),
    Output("kpi-region-gap-v", "children"),
    Output(f"{_MAP_ID}-geojson", "hideout"),
    Output("page-region-price-trend", "figure"),
    Output("page-region-rank-grid", "rowData"),
    Input("f-sido", "value"),
    Input("f-sgg", "value"),
    Input("f-area", "value"),
    Input("f-deal", "data"),
    Input("f-period", "value"),
)
def _refresh_region(sido, sgg, area, deal, period):
    dong = None  # 읍면동 필터 제거됨 — 시군구 단위까지만 필터링
    sido = sido or "서울특별시"

    # ---- KPI / scope ----
    if sgg and sgg != "전체":
        summary = mq.get_sgg_summary(sido, sgg) or {}
        trade_v = format_count(summary.get("trade_count_6m"))
        ppm2_v = format_ppm2(summary.get("median_ppm2_6m"))
        jeonse_v = format_percent(summary.get("jeonse_ratio_6m"))

        nv_df = nvq.active_listing_counts_by_sgg(sido)
        active = int(
            nv_df.loc[nv_df["sgg"] == sgg, "active_listings"].sum()
            if not nv_df.empty
            else 0
        )
        active_v = format_count(active)

        try:
            gap_df = gapq.gap_ratio_by_sgg(sido)
            row = gap_df.loc[gap_df["sgg"] == sgg]
            gap_v = format_percent(row["avg_gap_ratio"].iloc[0]) if not row.empty else "—"
        except Exception:
            gap_v = "—"

        scope_label = f"{sido} · {sgg}"
    else:
        trade_v = ppm2_v = jeonse_v = active_v = gap_v = "—"
        scope_label = f"{sido} · 시군구를 선택하세요"

    # ---- Map ----
    try:
        sgg_df = mq.get_sgg_metrics(sido)
        db_values = (
            dict(zip(sgg_df["sgg"], sgg_df["median_ppm2_6m"].fillna(0)))
            if not sgg_df.empty
            else {}
        )
    except Exception:
        db_values = {}
    values_by_sgg = collapse_db_sgg_to_geo(db_values, aggregator="mean")
    map_hideout = build_hideout(
        values_by_sgg,
        color_scale="Blues",
        selected_sgg=sgg if sgg and sgg != "전체" else None,
        sido=sido,
    )

    # ---- Price trend (월별 중앙값) ----
    try:
        f = rtq.build_filter(sido, sgg, dong, area, deal, period)
        price_df = rtq.price_change(f)
    except Exception:
        price_df = None

    if price_df is None or price_df.empty:
        price_fig = charts.empty_fig("데이터 없음")
    else:
        price_fig = charts.build_price_change(price_df)

    # ---- Ranking table ----
    try:
        rank_df = mq.get_complex_ranking(
            sido=sido,
            sgg=sgg if sgg and sgg != "전체" else None,
            order_by="trade_count_6m",
            limit=500,
        )
        rank_df["last_deal_date"] = rank_df["last_deal_date"].astype(str).replace("NaT", "")
        row_data = rank_df.to_dict("records")
    except Exception:
        row_data = []

    return (
        scope_label,
        trade_v, ppm2_v, jeonse_v, active_v, gap_v,
        map_hideout,
        price_fig,
        row_data,
    )


@callback(
    Output("f-sgg", "value", allow_duplicate=True),
    Input(f"{_MAP_ID}-geojson", "clickData"),
    State("_url", "pathname"),
    prevent_initial_call=True,
)
def _region_map_click(click, pathname):
    """Region 페이지의 map 클릭 시 f-sgg 갱신."""
    if pathname != "/region" or not click:
        raise PreventUpdate
    name = (click.get("properties") or {}).get("name")
    if not name:
        raise PreventUpdate
    return name

"""시장 개요 페이지 (/) — 스펙 3.1 + 사용자 피드백 반영.

구성:
- KPI 4개 (각각 고유 색상, 클릭 시 맵 지표 전환):
    · 거래량 (직전 완료월 + MoM)
    · 평당가 (최근 6M 중위 + 이전 6M 대비)
    · 전세가율 (최근 6M 평균 + 이전 6M 대비)
    · 활성 매물 (선행 지표, 매매/전세/월세 분해)
- 메인 choropleth — 선택된 KPI 지표를 색상으로 반영
  · 시군구 클릭 → 페이지 내 필터 (KPI/trend 모두 그 시군구로 narrowing)
- 36개월 거래량 · 평당가 dual-axis 라인 (맵 우측)

설계 원칙:
- 단지 내 다면적 혼재로 단지 평균가는 의미 없음 → 모든 가격 지표는 평당(만원/㎡) 기준.
- 월 거래량 비교는 신고 유예(30일) 고려해 직전 완료월(2개월 전) vs 그 전월.
- 6M 윈도우 지표는 최근 6M vs 이전 6M 비교.
- 활성 매물은 스냅샷이라 시간 비교가 어려움 → 분해 표시로 대체.
"""

from __future__ import annotations

import dash
import pandas as pd
import plotly.graph_objects as go
from dash import ALL, Input, Output, State, callback, ctx, dcc, html
from dash.exceptions import PreventUpdate
from sqlalchemy import text

from dash_app.components.choropleth_map import ChoroplethMap, build_hideout
from dash_app.components.formatters import format_count, format_percent, format_ppm2
from dash_app.components.kpi_card import KpiCard
from dash_app.db import get_engine
from dash_app.geo_names import collapse_db_sgg_to_geo
from dash_app.queries import metrics_queries as mq
from dash_app.queries import nv_queries as nvq
from dash_app.theme import ACCENT_2, apply_dark_theme

dash.register_page(
    __name__,
    path="/",
    name="시장 개요",
    order=1,
    title="APT Insight — 시장 개요",
)


_MAP_ID = "page-home-map"
_METRIC_LABELS = {
    "trade_count": "거래량",
    "ppm2": "평당가",
    "jeonse": "전세가율",
    "active": "활성 매물",
}
_METRIC_SCALE = {
    "trade_count": "Blues",
    "ppm2": "Purples",
    "jeonse": "Greens",
    "active": "Oranges",
}
_METRIC_COLOR = {
    "trade_count": "blue",
    "ppm2": "purple",
    "jeonse": "green",
    "active": "orange",
}
# 툴팁 값 포맷 타입 (JS 가 사용). 라벨은 각 KPI 의 실제 기간에 맞춰 콜백에서 구성.
_METRIC_VALUE_FORMAT = {
    "trade_count": "count",
    "ppm2": "ppm2",
    "jeonse": "percent",
    "active": "count",
}


def _tile_id(metric: str) -> dict:
    return {"role": "home-kpi", "metric": metric}


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


def _page_head() -> html.Div:
    return html.Div(
        className="page-head",
        children=[
            html.H1("부동산 거래 분석 대시보드"),
            html.Div(
                className="live",
                children=[
                    html.Span(className="dot-live"),
                    html.Span(id="page-home-scope", children="—"),
                ],
            ),
        ],
    )


def _kpi_strip() -> html.Div:
    return html.Div(
        className="kpi-strip",
        children=[
            KpiCard(
                "거래량",
                value_id="kpi-home-trade-v",
                period_id="kpi-home-trade-p",
                detail_id="kpi-home-trade-d",
                tile_id=_tile_id("trade_count"),
                color="blue",
                clickable=True,
                selected=True,
            ),
            KpiCard(
                "평당가",
                value_id="kpi-home-ppm2-v",
                period_id="kpi-home-ppm2-p",
                term="평당가",
                tile_id=_tile_id("ppm2"),
                color="purple",
                clickable=True,
            ),
            KpiCard(
                "전세가율",
                value_id="kpi-home-jeonse-v",
                period_id="kpi-home-jeonse-p",
                term="전세가율",
                tile_id=_tile_id("jeonse"),
                color="green",
                clickable=True,
            ),
            KpiCard(
                "활성 매물",
                value_id="kpi-home-active-v",
                period_id="kpi-home-active-p",
                detail_id="kpi-home-active-d",
                term="활성_매물",
                tile_id=_tile_id("active"),
                color="orange",
                kind="leading",
                clickable=True,
            ),
            dcc.Store(id="home-metric", data="trade_count"),
            dcc.Store(id="home-selected-sgg", data=None),
        ],
    )


def _map_card() -> html.Div:
    return html.Div(
        className="card",
        style={"padding": 0, "overflow": "hidden"},
        children=[
            html.Div(
                className="card-head",
                style={"padding": "14px 16px 8px"},
                children=[
                    html.Div(className="ic", children=html.I(className="fa-solid fa-map")),
                    html.Div(className="t", id="page-home-map-title", children="수도권 시군구 지표"),
                    html.Div(
                        className="s",
                        children=[
                            html.Span("KPI 클릭으로 지표 전환 · 시군구 클릭으로 필터링"),
                            html.Span(id="page-home-selected-chip"),
                        ],
                    ),
                ],
            ),
            ChoroplethMap(_MAP_ID, {}, color_scale="Blues", height=520),
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
                        id="page-home-trend-title",
                        children="36개월 거래량 · 평당가 추이",
                    ),
                    html.Div(className="s", children="좌축 거래건수 · 우축 평당 중위 (만원/㎡)"),
                ],
            ),
            dcc.Graph(
                id="page-home-trend",
                config={"displayModeBar": False, "responsive": True},
                style={"height": 520},
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
            children=[_map_card(), _trend_card()],
        ),
    ],
)


# ---------------------------------------------------------------------------
# Query helpers (home-local) — period-over-period comparisons
# ---------------------------------------------------------------------------


def _trade_volume_breakdown(sido: str, sgg: str | None) -> tuple[str, dict]:
    """직전 완료월(2M 전) 매매/전세/월세 거래량 분해.

    Returns: (ym_label, {"sale": n, "jeonse": n, "rent": n, "total": n})
    신고 유예(30일) 때문에 최근 1개월은 신뢰 불가 → 2개월 전(= 직전 완료월)을 사용.
    """
    where_c = ["c.sido_name = :sido"]
    params: dict = {"sido": sido}
    if sgg:
        where_c.append("c.sgg_name = :sgg")
        params["sgg"] = sgg
    common = " AND ".join(where_c)

    sql = text(f"""
        WITH win AS (
            SELECT date_trunc('month', CURRENT_DATE - INTERVAL '2 months') AS start_d,
                   date_trunc('month', CURRENT_DATE - INTERVAL '1 month')  AS end_d
        ),
        sale AS (
            SELECT COUNT(*) AS n
            FROM rt_trade t JOIN rt_complex c ON t.apt_id = c.apt_id, win w
            WHERE {common}
              AND deal_date >= w.start_d AND deal_date < w.end_d
        ),
        rent AS (
            SELECT
                COUNT(*) FILTER (WHERE r.monthly_rent = 0) AS jeonse_n,
                COUNT(*) FILTER (WHERE r.monthly_rent > 0) AS rent_n
            FROM rt_rent r JOIN rt_complex c ON r.apt_id = c.apt_id, win w
            WHERE {common}
              AND r.deal_date >= w.start_d AND r.deal_date < w.end_d
        )
        SELECT
            (SELECT n FROM sale)        AS sale_n,
            (SELECT jeonse_n FROM rent) AS jeonse_n,
            (SELECT rent_n FROM rent)   AS rent_n,
            to_char((SELECT start_d FROM win), 'YYYY-MM') AS ym
    """)
    with get_engine().connect() as conn:
        row = dict(conn.execute(sql, params).mappings().fetchone() or {})
    sale = int(row.get("sale_n") or 0)
    jeonse = int(row.get("jeonse_n") or 0)
    rent = int(row.get("rent_n") or 0)
    return row.get("ym", "—"), {
        "sale": sale,
        "jeonse": jeonse,
        "rent": rent,
        "total": sale + jeonse + rent,
    }


def _ppm2_median_6m(sido: str, sgg: str | None) -> tuple[float | None, str]:
    """최근 6M 평당 중위 + 윈도우 라벨 문자열."""
    wheres = ["c.sido_name = :sido", "exclusive_area > 0"]
    params: dict = {"sido": sido}
    if sgg:
        wheres.append("c.sgg_name = :sgg")
        params["sgg"] = sgg
    sql = text(f"""
        SELECT
            PERCENTILE_CONT(0.5) WITHIN GROUP (
                ORDER BY deal_amount / NULLIF(exclusive_area, 0)
            ) AS cur,
            to_char(MIN(deal_date), 'YYYY-MM') AS start_ym,
            to_char(MAX(deal_date), 'YYYY-MM') AS end_ym
        FROM rt_trade t JOIN rt_complex c ON t.apt_id = c.apt_id
        WHERE {' AND '.join(wheres)}
          AND deal_date >= CURRENT_DATE - INTERVAL '6 months'
    """)
    with get_engine().connect() as conn:
        row = dict(conn.execute(sql, params).mappings().fetchone() or {})
    cur = float(row["cur"]) if row.get("cur") is not None else None
    label = (
        f"{row.get('start_ym')} ~ {row.get('end_ym')}"
        if row.get("start_ym") and row.get("end_ym")
        else "—"
    )
    return cur, label


def _jeonse_ratio_1m(sido: str, sgg: str | None) -> tuple[float | None, str]:
    """직전 완료월(2M 전) 전세가율. 평당 중위 기반."""
    wheres_common = ["c.sido_name = :sido", "exclusive_area > 0"]
    params: dict = {"sido": sido}
    if sgg:
        wheres_common.append("c.sgg_name = :sgg")
        params["sgg"] = sgg
    common = " AND ".join(wheres_common)

    sql = text(f"""
        WITH win AS (
            SELECT
                date_trunc('month', CURRENT_DATE - INTERVAL '2 months') AS start_d,
                date_trunc('month', CURRENT_DATE - INTERVAL '1 month')  AS end_d
        ),
        sale AS (
            SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (
                       ORDER BY deal_amount / NULLIF(exclusive_area, 0)
                   ) AS v
            FROM rt_trade t JOIN rt_complex c ON t.apt_id = c.apt_id, win w
            WHERE {common} AND deal_date >= w.start_d AND deal_date < w.end_d
        ),
        jeonse AS (
            SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (
                       ORDER BY deposit / NULLIF(exclusive_area, 0)
                   ) AS v
            FROM rt_rent r JOIN rt_complex c ON r.apt_id = c.apt_id, win w
            WHERE {common} AND r.deal_date >= w.start_d AND r.deal_date < w.end_d
              AND r.monthly_rent = 0
        )
        SELECT
            (SELECT v FROM jeonse) / NULLIF((SELECT v FROM sale), 0) AS ratio,
            to_char((SELECT start_d FROM win), 'YYYY-MM') AS ym
    """)
    with get_engine().connect() as conn:
        row = dict(conn.execute(sql, params).mappings().fetchone() or {})
    ratio = float(row["ratio"]) if row.get("ratio") is not None else None
    return ratio, row.get("ym", "—")


def _active_listing_snapshot(sido: str, sgg: str | None) -> dict:
    """현재 활성 매물 — 거래유형 분해. 스냅샷이라 시간 비교 없음."""
    wheres = ["c.sido_name = :sido"]
    params: dict = {"sido": sido}
    if sgg:
        wheres.append("c.sgg_name = :sgg")
        params["sgg"] = sgg
    common = " AND ".join(wheres)

    sql = text(f"""
        SELECT
            COUNT(*)                                                        AS total,
            COUNT(*) FILTER (WHERE l.trade_type = 'A1')                     AS sale,
            COUNT(*) FILTER (WHERE l.trade_type = 'B1')                     AS jeonse,
            COUNT(*) FILTER (WHERE l.trade_type = 'B2')                     AS rent
        FROM nv_listing l
        JOIN nv_complex c ON l.complex_no = c.complex_no
        WHERE {common} AND c.sgg_name IS NOT NULL AND l.is_active = TRUE
    """)
    with get_engine().connect() as conn:
        row = dict(conn.execute(sql, params).mappings().fetchone() or {})
    return {
        "total": int(row.get("total") or 0),
        "sale": int(row.get("sale") or 0),
        "jeonse": int(row.get("jeonse") or 0),
        "rent": int(row.get("rent") or 0),
    }


def _sgg_trade_1m(sido: str) -> dict[str, float]:
    """시군구별 직전 완료월 거래량 (KPI 기간과 동일하게 1M 정렬)."""
    sql = text("""
        WITH win AS (
            SELECT date_trunc('month', CURRENT_DATE - INTERVAL '2 months') AS start_d,
                   date_trunc('month', CURRENT_DATE - INTERVAL '1 month')  AS end_d
        )
        SELECT c.sgg_name AS sgg, COUNT(*) AS n
        FROM rt_trade t JOIN rt_complex c ON t.apt_id = c.apt_id, win w
        WHERE c.sido_name = :sido AND c.sgg_name IS NOT NULL
          AND t.deal_date >= w.start_d AND t.deal_date < w.end_d
        GROUP BY c.sgg_name
    """)
    with get_engine().connect() as conn:
        rows = conn.execute(sql, {"sido": sido}).fetchall()
    return {r[0]: float(r[1] or 0) for r in rows}


def _sgg_jeonse_1m(sido: str) -> dict[str, float]:
    """시군구별 직전 완료월 전세가율(%). 평당 기준."""
    sql = text("""
        WITH win AS (
            SELECT date_trunc('month', CURRENT_DATE - INTERVAL '2 months') AS start_d,
                   date_trunc('month', CURRENT_DATE - INTERVAL '1 month')  AS end_d
        ),
        sale AS (
            SELECT c.sgg_name AS sgg,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (
                       ORDER BY deal_amount / NULLIF(exclusive_area, 0)
                   ) AS v
            FROM rt_trade t JOIN rt_complex c ON t.apt_id = c.apt_id, win w
            WHERE c.sido_name = :sido AND c.sgg_name IS NOT NULL
              AND t.deal_date >= w.start_d AND t.deal_date < w.end_d
              AND exclusive_area > 0
            GROUP BY c.sgg_name
        ),
        jeonse AS (
            SELECT c.sgg_name AS sgg,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (
                       ORDER BY deposit / NULLIF(exclusive_area, 0)
                   ) AS v
            FROM rt_rent r JOIN rt_complex c ON r.apt_id = c.apt_id, win w
            WHERE c.sido_name = :sido AND c.sgg_name IS NOT NULL
              AND r.deal_date >= w.start_d AND r.deal_date < w.end_d
              AND r.monthly_rent = 0 AND exclusive_area > 0
            GROUP BY c.sgg_name
        )
        SELECT s.sgg, (j.v / NULLIF(s.v, 0)) * 100 AS ratio_pct
        FROM sale s JOIN jeonse j ON s.sgg = j.sgg
        WHERE s.v IS NOT NULL AND j.v IS NOT NULL
    """)
    with get_engine().connect() as conn:
        rows = conn.execute(sql, {"sido": sido}).fetchall()
    return {r[0]: float(r[1]) for r in rows if r[1] is not None}


def _metric_values(sido: str, metric: str) -> dict[str, float]:
    """sgg별 지표 값 — 맵 color + 툴팁 원본값. KPI 와 기간을 맞춤."""
    try:
        if metric == "trade_count":
            return _sgg_trade_1m(sido)
        if metric == "ppm2":
            df = mq.get_sgg_metrics(sido)
            return dict(zip(df["sgg"], df["median_ppm2_6m"].fillna(0))) if not df.empty else {}
        if metric == "jeonse":
            return _sgg_jeonse_1m(sido)
        if metric == "active":
            df = nvq.active_listing_counts_by_sgg(sido)
            return dict(zip(df["sgg"], df["active_listings"].fillna(0))) if not df.empty else {}
    except Exception:
        pass
    return {}


def _build_trend_chart(sido: str, sgg: str | None) -> go.Figure:
    wheres = ["c.sido_name = :sido", "exclusive_area > 0"]
    params: dict = {"sido": sido}
    if sgg:
        wheres.append("c.sgg_name = :sgg")
        params["sgg"] = sgg
    sql = text(f"""
        SELECT to_char(deal_date, 'YYYY-MM') AS ym,
               COUNT(*) AS trade_count,
               PERCENTILE_CONT(0.5) WITHIN GROUP (
                   ORDER BY deal_amount / NULLIF(exclusive_area, 0)
               ) AS median_ppm2
        FROM rt_trade t JOIN rt_complex c ON t.apt_id = c.apt_id
        WHERE {' AND '.join(wheres)}
          AND deal_date >= CURRENT_DATE - INTERVAL '36 months'
        GROUP BY ym ORDER BY ym
    """)
    with get_engine().connect() as conn:
        df = pd.read_sql(sql, conn, params=params)

    fig = go.Figure()
    if df.empty:
        fig.add_annotation(
            text="데이터 없음", showarrow=False, font=dict(color="#777"),
            xref="paper", yref="paper", x=0.5, y=0.5,
        )
        return apply_dark_theme(fig, margin=dict(l=10, r=10, t=10, b=10))

    fig.add_trace(
        go.Bar(
            x=df["ym"], y=df["trade_count"], name="거래량",
            marker=dict(color="rgba(79, 172, 254, .35)"),
            hovertemplate="%{x}<br>거래량 %{y:,}건<extra></extra>",
            yaxis="y",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df["ym"], y=df["median_ppm2"], name="평당 중위",
            mode="lines+markers",
            line=dict(color=ACCENT_2, width=2, shape="spline"),
            marker=dict(size=4),
            hovertemplate="%{x}<br>평당 중위 %{y:,.0f}만원/㎡<extra></extra>",
            yaxis="y2",
        )
    )
    apply_dark_theme(fig, margin=dict(l=56, r=56, t=24, b=40))
    fig.update_layout(
        yaxis=dict(title=dict(text="거래건수", font=dict(size=10))),
        yaxis2=dict(
            title=dict(text="평당 중위 (만원/㎡)", font=dict(size=10)),
            overlaying="y", side="right", showgrid=False,
        ),
        legend=dict(orientation="h", x=0, y=1.08, font=dict(size=11)),
    )
    return fig


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------


@callback(
    Output("home-metric", "data"),
    Input({"role": "home-kpi", "metric": ALL}, "n_clicks"),
    State("home-metric", "data"),
)
def _kpi_click_to_metric(n_clicks, current):
    trig = ctx.triggered_id
    if not trig or not any(n_clicks or []):
        raise PreventUpdate
    return trig.get("metric", current or "trade_count")


@callback(
    Output({"role": "home-kpi", "metric": ALL}, "className"),
    Input("home-metric", "data"),
    State({"role": "home-kpi", "metric": ALL}, "id"),
)
def _kpi_highlight(metric, ids):
    metric = metric or "trade_count"
    out = []
    for i in ids:
        classes = [
            "kpi-tile",
            f"kpi-tile--color-{_METRIC_COLOR[i['metric']]}",
            "kpi-tile--clickable",
        ]
        if i["metric"] == "active":
            classes.append("kpi-tile--leading")
        if i["metric"] == metric:
            classes.append("kpi-tile--selected")
        out.append(" ".join(classes))
    return out


@callback(
    Output("home-selected-sgg", "data", allow_duplicate=True),
    Input(f"{_MAP_ID}-geojson", "clickData"),
    State("_url", "pathname"),
    prevent_initial_call=True,
)
def _map_click_to_selection(click, pathname):
    """홈에서 시군구 클릭 → 페이지 내 필터 스토어 갱신."""
    if pathname != "/" or not click:
        raise PreventUpdate
    name = (click.get("properties") or {}).get("name")
    if not name:
        raise PreventUpdate
    return name


@callback(
    Output("home-selected-sgg", "data", allow_duplicate=True),
    Input("page-home-clear-sgg", "n_clicks"),
    prevent_initial_call=True,
)
def _clear_selected_sgg(n):
    if not n:
        raise PreventUpdate
    return None


@callback(
    Output("page-home-scope", "children"),
    Output("kpi-home-trade-v", "children"),
    Output("kpi-home-trade-p", "children"),
    Output("kpi-home-trade-d", "children"),
    Output("kpi-home-ppm2-v", "children"),
    Output("kpi-home-ppm2-p", "children"),
    Output("kpi-home-jeonse-v", "children"),
    Output("kpi-home-jeonse-p", "children"),
    Output("kpi-home-active-v", "children"),
    Output("kpi-home-active-p", "children"),
    Output("kpi-home-active-d", "children"),
    Output(f"{_MAP_ID}-geojson", "hideout"),
    Output("page-home-map-title", "children"),
    Output("page-home-selected-chip", "children"),
    Output("page-home-trend-title", "children"),
    Output("page-home-trend", "figure"),
    Input("f-sido", "value"),
    Input("home-metric", "data"),
    Input("home-selected-sgg", "data"),
)
def _refresh_home(sido, metric, selected_sgg):
    sido = sido or "서울특별시"
    metric = metric or "trade_count"
    sgg = selected_sgg or None

    scope_label = f"실시간 · {sido}" + (f" · {sgg}" if sgg else "")

    # ---- KPI 1: 거래량 (직전 완료월, 매매/전세/월세 분해) ----
    trade_ym, trade = _trade_volume_breakdown(sido, sgg)
    trade_v = format_count(trade["total"])
    trade_p = f"{trade_ym} (직전 완료월)"
    trade_d = (
        f"매매 {trade['sale']:,} · 전세 {trade['jeonse']:,} · 월세 {trade['rent']:,}"
    )

    # ---- KPI 2: 평당가 (최근 6M 중위) ----
    ppm2_cur, ppm2_window = _ppm2_median_6m(sido, sgg)
    ppm2_v = format_ppm2(ppm2_cur) if ppm2_cur is not None else "—"
    ppm2_p = f"{ppm2_window} · 6M 중위"

    # ---- KPI 3: 전세가율 (직전 완료월, 평당 기준) ----
    j_cur, j_ym = _jeonse_ratio_1m(sido, sgg)
    jeonse_v = format_percent(j_cur) if j_cur is not None else "—"
    jeonse_p = f"{j_ym} (직전 완료월)"

    # ---- KPI 4: 활성 매물 (현재 스냅샷 + 매매/전세/월세 분해) ----
    snap = _active_listing_snapshot(sido, sgg)
    if snap["total"] == 0:
        active_v, active_d = "—", "—"
    else:
        active_v = format_count(snap["total"])
        active_d = (
            f"매매 {snap['sale']:,} · 전세 {snap['jeonse']:,} · 월세 {snap['rent']:,}"
        )
    active_p = "현재 스냅샷"

    # ---- Map (KPI 와 동일한 기간/지표로 동기) ----
    values = _metric_values(sido, metric)
    values = collapse_db_sgg_to_geo(values, aggregator="mean")
    tooltip_label = {
        "trade_count": f"거래량 · {trade_ym}",
        "ppm2": f"평당 중위 · {ppm2_window}",
        "jeonse": f"전세가율 · {j_ym}",
        "active": "활성 매물 · 현재",
    }[metric]
    map_hideout = build_hideout(
        values,
        color_scale=_METRIC_SCALE[metric],
        selected_sgg=sgg,
        sido=sido,
        metric=metric,
        metric_label=tooltip_label,
        value_format=_METRIC_VALUE_FORMAT[metric],
    )
    map_title = f"수도권 시군구 — {_METRIC_LABELS[metric]}"

    # ---- Selected chip ----
    if sgg:
        chip = html.Span(
            className="filter-chip",
            children=[
                html.B(sgg),
                " 필터 활성",
                html.Button("×", id="page-home-clear-sgg", n_clicks=0, title="선택 해제"),
            ],
        )
    else:
        chip = None

    # ---- Trend ----
    trend_title = "36개월 거래량 · 평당가 추이" + (f" · {sgg}" if sgg else "")
    trend_fig = _build_trend_chart(sido, sgg)

    return (
        scope_label,
        trade_v, trade_p, trade_d,
        ppm2_v, ppm2_p,
        jeonse_v, jeonse_p,
        active_v, active_p, active_d,
        map_hideout, map_title, chip,
        trend_title, trend_fig,
    )

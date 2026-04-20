"""시장 개요 페이지 (/). 기존 단일 페이지 대시보드를 그대로 이관."""

from __future__ import annotations

import math
import traceback

import dash
from dash import ALL, Input, Output, State, callback, ctx, dcc, html
from dash.exceptions import PreventUpdate

from dash_app import charts
from dash_app.config import DEAL_LABELS
from dash_app.queries import rt_queries as q

dash.register_page(
    __name__,
    path="/",
    name="시장 개요",
    order=1,
    title="APT Insight — 시장 개요",
)


# ---------------------------------------------------------------------------
# Layout pieces (home-local)
# ---------------------------------------------------------------------------


def _fa(icon: str) -> html.I:
    return html.I(className=f"fa-solid fa-{icon}")


def _page_head() -> html.Div:
    return html.Div(
        className="page-head",
        children=[
            html.H1("부동산 거래 분석 대시보드"),
            html.Div(
                className="live",
                id="page-live-stamp",
                children=[
                    html.Span(className="dot-live"),
                    "실시간 · rt_trade / nv_listing",
                ],
            ),
        ],
    )


def _kpi_strip() -> html.Div:
    return html.Div(
        className="kpi-strip",
        children=[
            html.Div(
                className="kpi-tile",
                children=[
                    html.Div("조회 범위", className="l"),
                    html.Div(
                        id="kpi-scope-v",
                        className="v",
                        style={
                            "fontSize": 16,
                            "fontFamily": "var(--font-sans)",
                            "color": "var(--accent-1)",
                        },
                        children="—",
                    ),
                    html.Div(id="kpi-scope-d", className="d", children="—"),
                ],
            ),
            html.Div(
                className="kpi-tile",
                children=[
                    html.Div("총 거래건수", className="l"),
                    html.Div(id="kpi-total-v", className="v", children="—"),
                    html.Div(id="kpi-total-d", className="d", children=" "),
                ],
            ),
            html.Div(
                className="kpi-tile",
                children=[
                    html.Div("집계 단지 수", className="l"),
                    html.Div(id="kpi-uniq-v", className="v", children="—"),
                    html.Div(id="kpi-uniq-d", className="d", children=" "),
                ],
            ),
            html.Div(
                className="kpi-tile",
                children=[
                    html.Div("최다 단지 거래", className="l"),
                    html.Div(id="kpi-max-v", className="v", children="—"),
                    html.Div(id="kpi-max-d", className="d", children=" "),
                ],
            ),
        ],
    )


def _tab_strip() -> html.Div:
    return html.Div(
        children=[
            html.Div(
                className="tab-strip",
                id="tab-strip",
                children=[
                    html.Button(
                        "인트로",
                        id={"role": "tab", "value": "intro"},
                        className="on",
                        n_clicks=0,
                    ),
                    html.Button(
                        "거래건수",
                        id={"role": "tab", "value": "volume"},
                        n_clicks=0,
                    ),
                    html.Button(
                        "가격변화",
                        id={"role": "tab", "value": "price"},
                        n_clicks=0,
                    ),
                ],
            ),
            dcc.Store(id="active-tab", data="intro"),
            html.Div(
                className="card",
                style={"borderTopLeftRadius": 0, "borderTopRightRadius": 8},
                children=[
                    html.Div(
                        className="card-head",
                        children=[
                            html.Div(id="chart-card-ic", className="ic", children=_fa("chart-line")),
                            html.Div(id="chart-card-title", className="t", children="거래추이"),
                            html.Div(id="chart-card-sub", className="s", children=""),
                        ],
                    ),
                    dcc.Graph(
                        id="main-chart",
                        config={"displayModeBar": False, "responsive": True},
                        style={"width": "100%", "height": 320},
                    ),
                ],
            ),
        ],
    )


def _map_row() -> html.Div:
    return html.Div(
        className="row2-28",
        children=[
            html.Div(
                className="card",
                children=[
                    html.Div(
                        className="card-head",
                        children=[
                            html.Div(
                                className="ic",
                                style={
                                    "background": "rgba(217, 88, 74, .15)",
                                    "color": "#e56b5d",
                                },
                                children=_fa("map"),
                            ),
                            html.Div(className="t", children="행정구역(시군구)별 거래 건수"),
                            html.Div(className="s", children="클릭 시 필터 반영"),
                        ],
                    ),
                    html.Div(
                        className="map-wrap",
                        children=[
                            dcc.Graph(
                                id="choropleth",
                                config={
                                    "displayModeBar": False,
                                    "responsive": True,
                                    "scrollZoom": False,
                                },
                                style={"width": "100%", "height": "100%"},
                            ),
                        ],
                    ),
                ],
            ),
            html.Div(
                className="card",
                children=[
                    html.Div(
                        className="card-head",
                        children=[
                            html.Div(
                                className="ic",
                                style={
                                    "background": "rgba(229, 57, 53, .18)",
                                    "color": "#e53935",
                                },
                                children=_fa("location-dot"),
                            ),
                            html.Div(className="t", children="아파트별 매매 건수 (지도)"),
                            html.Div(className="s", children="원 크기 = 거래 건수"),
                        ],
                    ),
                    html.Div(
                        className="dot-map-note",
                        children=[
                            html.B("●"),
                            " 붉은 원은 아파트 위치이며, 크기는 거래 건수입니다.",
                        ],
                    ),
                    html.Div(
                        className="dot-map-wrap",
                        children=[
                            dcc.Graph(
                                id="dot-map",
                                config={
                                    "displayModeBar": False,
                                    "responsive": True,
                                    "scrollZoom": True,
                                },
                                style={"width": "100%", "height": "100%"},
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


def _apt_table_card() -> html.Div:
    return html.Div(
        className="card",
        children=[
            html.Div(
                className="card-head",
                children=[
                    html.Div(className="ic", children=_fa("table")),
                    html.Div(className="t", children="아파트별 매매 건수 (테이블)"),
                    html.Div(className="s", children="컬럼 헤더 클릭 시 정렬 · 페이지 10개"),
                ],
            ),
            html.Div(id="apt-table-sub", className="sub", children="—"),
            html.Div(
                id="apt-table-host",
                className="apt-table-wrap",
                children=[
                    html.Div(
                        "데이터 준비 중…",
                        style={"padding": "20px", "color": "var(--fg-3)"},
                    )
                ],
            ),
            html.Div(
                className="pager",
                children=[
                    html.Button(_fa("angles-left"), id="tb-first", n_clicks=0),
                    html.Button(_fa("angle-left"), id="tb-prev", n_clicks=0),
                    html.Span("1", id="tb-cur", className="cur"),
                    html.Span(id="tb-total", children="/ 1"),
                    html.Button(_fa("angle-right"), id="tb-next", n_clicks=0),
                    html.Button(_fa("angles-right"), id="tb-last", n_clicks=0),
                ],
            ),
            dcc.Store(id="tb-page", data=1),
            dcc.Store(id="tb-sort", data={"key": "count", "dir": -1}),
        ],
    )


layout = html.Main(
    className="fd-main",
    children=[
        _page_head(),
        _kpi_strip(),
        _tab_strip(),
        _map_row(),
        _apt_table_card(),
    ],
)


# ---------------------------------------------------------------------------
# Callbacks (page-local). Registered at import time via @callback.
# ---------------------------------------------------------------------------


def _filter_from_state(sido, sgg, dong, area, deal, period) -> q.Filter:
    return q.Filter(
        sido=sido or "서울특별시",
        sgg=sgg or "전체",
        dong=dong or "전체",
        area=area or "전체",
        deal=deal or "sale",
        period_months=int(period or 36),
    )


def _format_period(months: int) -> list:
    if months >= 120:
        return ["전체", html.Span("", className="unit")]
    if months >= 12:
        years = months / 12
        txt = f"{years:.0f}" if months % 12 == 0 else f"{years:.1f}"
        return [txt, html.Span("년", className="unit")]
    return [str(months), html.Span("개월", className="unit")]


def _scope_text(f: q.Filter) -> str:
    if f.dong and f.dong != "전체":
        return f"{f.sido} · {f.sgg} · {f.dong}"
    if f.sgg and f.sgg != "전체":
        return f"{f.sido} · {f.sgg}"
    return f.sido


def _render_apt_table(df, sort_key: str, sort_dir: int, page: int, per_page: int = 10):
    if df is None or df.empty:
        return (
            html.Div(
                "해당 조건의 거래가 없습니다.",
                style={"padding": "20px", "color": "var(--fg-3)"},
            ),
            1,
            1,
        )

    if sort_key in df.columns:
        df = df.sort_values(sort_key, ascending=(sort_dir > 0), na_position="last")
    total_pages = max(1, math.ceil(len(df) / per_page))
    page = min(max(1, page), total_pages)
    start = (page - 1) * per_page
    sub = df.iloc[start : start + per_page]

    def th(label: str, col: str, align_right: bool = False) -> html.Th:
        sorted_now = sort_key == col
        ord_txt = ("▼" if sort_dir < 0 else "▲") if sorted_now else "▴"
        return html.Th(
            [label, " ", html.Span(ord_txt, className="ord")],
            id={"role": "th", "col": col},
            className="sort" if sorted_now else "",
            style={"textAlign": "right"} if align_right else None,
            n_clicks=0,
        )

    head = html.Thead(
        html.Tr(
            [
                th("자치구", "sgg"),
                th("행정동", "admin_dong"),
                th("아파트", "apt_name"),
                th("건축년도", "build_year", align_right=True),
                th("거래건수", "count", align_right=True),
            ]
        )
    )

    rows = []
    for _, r in sub.iterrows():
        rows.append(
            html.Tr(
                [
                    html.Td(r.get("sgg") or "—"),
                    html.Td(r.get("admin_dong") or "—"),
                    html.Td(r.get("apt_name") or "—", className="apt-name"),
                    html.Td(
                        "—" if r.get("build_year") is None else f"{int(r['build_year'])}",
                        className="num",
                    ),
                    html.Td(f"{int(r['count']):,}", className="num"),
                ]
            )
        )

    return html.Table(className="apt-table", children=[head, html.Tbody(rows)]), total_pages, page


# --- Sido → sgg options/value ---
@callback(
    Output("f-sgg", "options"),
    Output("f-sgg", "value"),
    Input("f-sido", "value"),
)
def _cascade_sgg(sido):
    sggs = q.list_sgg(sido) if sido else ()
    opts = [{"label": "전체", "value": "전체"}] + [
        {"label": s, "value": s} for s in sggs
    ]
    return opts, "전체"


# --- Sgg → dong options/value ---
@callback(
    Output("f-dong", "options"),
    Output("f-dong", "value"),
    Input("f-sido", "value"),
    Input("f-sgg", "value"),
)
def _cascade_dong(sido, sgg):
    if not sido or not sgg or sgg == "전체":
        return [{"label": "전체", "value": "전체"}], "전체"
    dongs = q.list_dong(sido, sgg)
    opts = [{"label": "전체", "value": "전체"}] + [{"label": d, "value": d} for d in dongs]
    return opts, "전체"


# --- Period slider → label ---
@callback(Output("f-period-label", "children"), Input("f-period", "value"))
def _period_label(v):
    return _format_period(int(v or 36))


# --- Deal segment buttons → f-deal store + on class ---
@callback(
    Output("f-deal", "data"),
    Output({"role": "seg-deal", "value": ALL}, "className"),
    Input({"role": "seg-deal", "value": ALL}, "n_clicks"),
    State({"role": "seg-deal", "value": ALL}, "id"),
    State("f-deal", "data"),
)
def _deal_seg(n_clicks, ids, current):
    trig = ctx.triggered_id
    if not trig or not any(n_clicks):
        picked = current or "sale"
    else:
        picked = trig["value"]
    return picked, ["on" if i["value"] == picked else "" for i in ids]


# --- Tab buttons → active-tab store + on class ---
@callback(
    Output("active-tab", "data"),
    Output({"role": "tab", "value": ALL}, "className"),
    Input({"role": "tab", "value": ALL}, "n_clicks"),
    State({"role": "tab", "value": ALL}, "id"),
    State("active-tab", "data"),
)
def _tab_switch(n_clicks, ids, current):
    trig = ctx.triggered_id
    if not trig or not any(n_clicks):
        picked = current or "intro"
    else:
        picked = trig["value"]
    return picked, ["on" if i["value"] == picked else "" for i in ids]


# --- Reset button ---
@callback(
    Output("f-sido", "value"),
    Output("f-sgg", "value", allow_duplicate=True),
    Output("f-dong", "value", allow_duplicate=True),
    Output("f-area", "value"),
    Output("f-deal", "data", allow_duplicate=True),
    Output("f-period", "value"),
    Input("btn-reset", "n_clicks"),
    prevent_initial_call=True,
)
def _reset(_n):
    return "서울특별시", "전체", "전체", "전체", "sale", 36


# --- Choropleth click → set sgg ---
@callback(
    Output("f-sgg", "value", allow_duplicate=True),
    Input("choropleth", "clickData"),
    prevent_initial_call=True,
)
def _choro_click(click):
    if not click or not click.get("points"):
        raise PreventUpdate
    pt = click["points"][0]
    name = pt.get("location") or pt.get("customdata")
    if not name:
        raise PreventUpdate
    return name


# --- Main refresh: KPIs + charts + table on apply/change ---
@callback(
    Output("kpi-scope-v", "children"),
    Output("kpi-scope-d", "children"),
    Output("kpi-total-v", "children"),
    Output("kpi-uniq-v", "children"),
    Output("kpi-uniq-d", "children"),
    Output("kpi-max-v", "children"),
    Output("main-chart", "figure"),
    Output("chart-card-title", "children"),
    Output("chart-card-sub", "children"),
    Output("chart-card-ic", "children"),
    Output("dot-map", "figure"),
    Output("apt-table-host", "children"),
    Output("apt-table-sub", "children"),
    Output("tb-total", "children"),
    Output("tb-cur", "children"),
    Output("tb-page", "data"),
    Input("btn-apply", "n_clicks"),
    Input("f-deal", "data"),
    Input("active-tab", "data"),
    Input("f-sido", "value"),
    Input("f-sgg", "value"),
    Input("f-dong", "value"),
    Input("f-area", "value"),
    Input("tb-sort", "data"),
    Input("tb-first", "n_clicks"),
    Input("tb-prev", "n_clicks"),
    Input("tb-next", "n_clicks"),
    Input("tb-last", "n_clicks"),
    State("f-period", "value"),
    State("tb-page", "data"),
)
def _refresh(
    _apply, deal, tab, sido, sgg, dong, area, sort_state,
    _first, _prev, _next, _last, period, page,
):
    import time

    t0 = time.time()
    f = _filter_from_state(sido, sgg, dong, area, deal, period)
    print(f"[refresh] trigger={ctx.triggered_id} filter={f}", flush=True)

    try:
        t = time.time()
        kpi = q.kpi_summary(f)
        print(f"  kpi {time.time() - t:.2f}s", flush=True)
        t = time.time()
        complexes = q.top_complexes(f, limit=200)
        print(f"  top_complexes {time.time() - t:.2f}s rows={len(complexes)}", flush=True)
        t = time.time()
        trend_df = q.trade_trend(f)
        print(f"  trade_trend {time.time() - t:.2f}s rows={len(trend_df)}", flush=True)
        t = time.time()
        price_df = q.price_change(f) if tab == "price" else None
        print(f"  price_change {time.time() - t:.2f}s", flush=True)
    except Exception as e:
        traceback.print_exc()
        msg = f"DB 오류: {e}"
        empty = charts.empty_fig(msg)
        return (
            _scope_text(f), "—",
            "—", "—", "—", "—",
            empty, "거래추이", "", _fa("chart-line"),
            empty,
            html.Div(msg, style={"padding": "20px", "color": "var(--neg)"}),
            "—", "/ 1", "1", 1,
        )

    scope = _scope_text(f)
    deal_label = DEAL_LABELS.get(f.deal, f.deal)
    if f.period_months >= 120:
        period_txt_flat = "전체"
    elif f.period_months >= 12:
        yrs = f.period_months / 12
        period_txt_flat = (
            f"{yrs:.0f}" if f.period_months % 12 == 0 else f"{yrs:.1f}"
        ) + "년"
    else:
        period_txt_flat = f"{f.period_months}개월"

    if tab == "price":
        fig = charts.build_price_change(price_df if price_df is not None else trend_df)
        title = "가격 변화"
        sub = f"{scope} · 평균 vs 중앙값 · 월별"
        ic = _fa("won-sign")
    else:
        fig = charts.build_trade_trend(trend_df, f.deal)
        title = "거래추이"
        sub = f"{scope} · {deal_label} · {f.area} · 일별"
        ic = _fa("chart-line")

    t = time.time()
    dot_fig = charts.build_dot_map(complexes, f.sido)
    print(f"  dot_map {time.time()-t:.2f}s | total {time.time()-t0:.2f}s", flush=True)

    sort_state = sort_state or {"key": "count", "dir": -1}
    sort_key = sort_state["key"]
    sort_dir = sort_state["dir"]

    current_page = int(page or 1)
    trig_id = ctx.triggered_id
    if trig_id == "tb-first":
        current_page = 1
    elif trig_id == "tb-prev":
        current_page = max(1, current_page - 1)
    elif trig_id == "tb-next":
        current_page += 1
    elif trig_id == "tb-last":
        current_page = 10_000

    if trig_id in (
        "btn-apply", "f-deal", "active-tab",
        "f-sido", "f-sgg", "f-dong", "f-area", "tb-sort",
    ):
        current_page = 1

    table, total_pages, current_page = _render_apt_table(
        complexes, sort_key, sort_dir, current_page
    )

    sub_line = ["총 ", html.B(f"{len(complexes):,}"), " 건 · ", scope]
    scope_d = f"{deal_label} · {f.area} · {period_txt_flat}"

    return (
        scope, scope_d,
        f"{kpi['total']:,}",
        f"{kpi['uniq']:,}",
        f"면적: {f.area}",
        f"{kpi['max']:,}",
        fig, title, sub, ic,
        dot_fig,
        table,
        sub_line,
        f"/ {total_pages}",
        str(current_page),
        current_page,
    )


# --- Choropleth is its own callback so the 700KB GeoJSON doesn't
#     re-serialize on every filter change ---
@callback(
    Output("choropleth", "figure"),
    Input("f-sido", "value"),
    Input("f-sgg", "value"),
    Input("f-deal", "data"),
    Input("f-area", "value"),
    Input("btn-apply", "n_clicks"),
    State("f-period", "value"),
)
def _refresh_choropleth(sido, sgg, deal, area, _apply, period):
    import time

    t0 = time.time()
    f = q.Filter(
        sido=sido or "서울특별시",
        sgg="전체",
        dong="전체",
        area=area or "전체",
        deal=deal or "sale",
        period_months=int(period or 36),
    )
    try:
        sgg_df = q.sgg_counts(f)
    except Exception:
        traceback.print_exc()
        return charts.empty_fig("DB 오류")
    fig = charts.build_choropleth(
        sgg_df, f.sido, selected_sgg=sgg if sgg and sgg != "전체" else None
    )
    print(f"[choropleth] {time.time()-t0:.2f}s sgg_rows={len(sgg_df)}", flush=True)
    return fig


# --- Sort header click → update sort store + reset page ---
@callback(
    Output("tb-sort", "data"),
    Input({"role": "th", "col": ALL}, "n_clicks"),
    State("tb-sort", "data"),
    State({"role": "th", "col": ALL}, "id"),
    prevent_initial_call=True,
)
def _sort_click(n_clicks, sort_state, ids):
    if not ctx.triggered_id or not any(n_clicks or []):
        raise PreventUpdate
    col = ctx.triggered_id["col"]
    sort_state = sort_state or {"key": "count", "dir": -1}
    if sort_state["key"] == col:
        sort_state = {"key": col, "dir": -sort_state["dir"]}
    else:
        sort_state = {"key": col, "dir": -1}
    return sort_state

"""단지 상세 페이지 (/complex) — 스펙 3.3.

단지 검색 Dropdown (서버사이드 부분일치, debounce 300ms) + 4탭:
  1. 실거래 추이 — 면적대별 라인 + 개별 거래 scatter
  2. 호가 추이 — nv_listing current_price 시계열 (매핑된 경우)
  3. 전월세 — 전세/월세 분리, 환산보증금 파생
  4. 층×면적 매트릭스 — 층(y) × 면적대(x) heatmap
"""

from __future__ import annotations

from urllib.parse import parse_qs

import dash
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, callback, dcc, html
from dash.exceptions import PreventUpdate

from dash_app.components.empty_state import EmptyState
from dash_app.components.formatters import format_count, format_ppm2, format_won
from dash_app.components.kpi_card import KpiCard
from dash_app.components.ranking_table import RankingTable
from dash_app.queries import metrics_queries as mq
from dash_app.queries import nv_queries as nvq
from dash_app.queries import rt_queries as rtq
from dash_app.theme import ACCENT_1, POS, apply_dark_theme

dash.register_page(
    __name__,
    path="/complex",
    name="단지 상세",
    order=3,
    title="APT Insight — 단지 상세",
)


_AREA_BUCKETS = [
    (None, 60.0, "~60㎡"),
    (60.0, 85.0, "60-85㎡"),
    (85.0, 102.0, "85-102㎡"),
    (102.0, None, "102㎡~"),
]


# ag-grid 탐색 테이블 컬럼 정의 — 단지 평균가는 다면적 혼재로 의미 없어 평당가로 교체.
_PICKER_COLUMNS: list[dict] = [
    {"field": "apt_name", "headerName": "단지", "minWidth": 180},
    {"field": "sgg", "headerName": "자치구", "minWidth": 110},
    {"field": "admin_dong", "headerName": "행정동", "minWidth": 110},
    {"field": "build_year", "headerName": "건축년도", "minWidth": 100, "type": "numericColumn"},
    {"field": "trade_count_6m", "headerName": "거래 6M", "minWidth": 100, "type": "numericColumn"},
    {"field": "trade_count_36m", "headerName": "거래 36M", "minWidth": 110, "type": "numericColumn"},
    {"field": "median_ppm2_6m", "headerName": "평당가(만원/㎡)", "minWidth": 140,
     "type": "numericColumn",
     "valueFormatter": {"function": "params.value == null ? '—' : d3.format(',.0f')(params.value)"}},
]


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


def _page_head() -> html.Div:
    return html.Div(
        className="page-head",
        children=[
            html.H1("단지 상세"),
            html.Div(
                className="live",
                children=[
                    html.Span(className="dot-live"),
                    html.Span(id="page-complex-sub", children="단지를 검색하세요"),
                ],
            ),
        ],
    )


def _search_bar() -> html.Div:
    return html.Div(
        className="card",
        style={"padding": "12px 16px", "display": "flex", "gap": 12, "alignItems": "center"},
        children=[
            html.Div(
                style={"flex": 1},
                children=[
                    dcc.Dropdown(
                        id="page-complex-search",
                        placeholder="단지명을 입력하세요 (예: 래미안)",
                        options=[],
                        search_value="",
                        value=None,
                        persistence=True,
                        persistence_type="session",
                        optionHeight=48,
                        style={"fontSize": 14},
                    ),
                ],
            ),
            html.Div(
                id="page-complex-recent",
                className="recent-chips",
                style={"display": "flex", "gap": 6},
            ),
        ],
    )


def _picker_card() -> html.Div:
    """사이드바 필터에 연동되는 단지 탐색 테이블 (행 클릭 → Dropdown 에 반영)."""
    return html.Div(
        className="card",
        children=[
            html.Div(
                className="card-head",
                children=[
                    html.Div(className="ic", children=html.I(className="fa-solid fa-table-cells")),
                    html.Div(className="t", children="단지 탐색"),
                    html.Div(
                        className="s",
                        id="page-complex-picker-sub",
                        children="사이드바 시도/자치구 기준 · 행 클릭 시 선택",
                    ),
                ],
            ),
            RankingTable(
                "page-complex-picker",
                _PICKER_COLUMNS,
                row_data=[],
                page_size=10,
                height=320,
                row_selection="single",
                get_row_id="params.data.apt_id",
            ),
        ],
    )


def _kpi_strip() -> html.Div:
    return html.Div(
        className="kpi-strip",
        children=[
            KpiCard("거래량 (6M)", value_id="kpi-complex-trade-v"),
            # 단지 평균 매매가는 다면적 혼재로 오해 소지 → 주력 면적 (거래 최다 전용면적) 로 교체
            KpiCard("주력 면적", value_id="kpi-complex-primary-v", term="전용면적"),
            KpiCard("평당가 (6M)", value_id="kpi-complex-ppm2-v", term="평당가"),
            KpiCard("최근 거래일", value_id="kpi-complex-recent-v"),
        ],
    )


def _tabs() -> html.Div:
    return html.Div(
        className="card",
        children=[
            dcc.Tabs(
                id="page-complex-tabs",
                value="trades",
                persistence=True,
                persistence_type="session",
                children=[
                    dcc.Tab(label="실거래 추이", value="trades"),
                    dcc.Tab(label="호가 추이", value="listings"),
                    dcc.Tab(label="전월세", value="rents"),
                    dcc.Tab(label="층 × 면적", value="matrix"),
                ],
            ),
            dcc.Graph(
                id="page-complex-chart",
                config={"displayModeBar": False, "responsive": True},
                style={"height": 420, "marginTop": 10},
            ),
        ],
    )


def _right_panel() -> html.Div:
    return html.Div(
        id="page-complex-info",
        className="card",
        style={"padding": "14px 18px"},
        children=[
            EmptyState(
                "단지를 선택하세요",
                description="좌측 검색창에서 단지명을 입력하면 상세 정보가 표시됩니다.",
                icon="magnifying-glass",
            ),
        ],
    )


layout = html.Main(
    className="fd-main",
    children=[
        _page_head(),
        _search_bar(),
        _picker_card(),
        _kpi_strip(),
        html.Div(
            className="row2-28",
            children=[_tabs(), _right_panel()],
        ),
    ],
)


# ---------------------------------------------------------------------------
# Chart builders (page-local)
# ---------------------------------------------------------------------------


def _build_trades_chart(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if df.empty:
        fig.add_annotation(
            text="거래 데이터 없음", showarrow=False, font=dict(color="#777"),
            xref="paper", yref="paper", x=0.5, y=0.5,
        )
        return apply_dark_theme(fig, margin=dict(l=10, r=10, t=10, b=10))

    # 면적대 분류
    def bucket(area: float) -> str:
        for lo, hi, label in _AREA_BUCKETS:
            if (lo is None or area > lo) and (hi is None or area <= hi):
                return label
        return "기타"

    df = df.copy()
    df["area_bucket"] = df["exclusive_area"].apply(bucket)
    df["amount_eok"] = df["deal_amount"] / 10000.0  # 만원 → 억

    # 개별 거래 scatter
    fig.add_trace(
        go.Scatter(
            x=df["deal_date"], y=df["amount_eok"],
            mode="markers",
            marker=dict(size=6, color=ACCENT_1, opacity=0.35,
                        line=dict(color="rgba(255,255,255,.3)", width=0.3)),
            customdata=df[["exclusive_area", "floor", "area_bucket"]],
            hovertemplate=(
                "%{x|%Y-%m-%d}<br>%{y:.2f}억<br>"
                "%{customdata[0]}㎡ · %{customdata[1]}층 · %{customdata[2]}<extra></extra>"
            ),
            name="개별 거래",
        )
    )

    # 면적대별 월별 중앙값 라인
    df["ym"] = pd.to_datetime(df["deal_date"]).dt.to_period("M").dt.to_timestamp()
    colors = ["#4facfe", "#00f2fe", "#9C27B0", "#FF9800"]
    for (_, _, label), color in zip(_AREA_BUCKETS, colors):
        sub = df[df["area_bucket"] == label]
        if sub.empty:
            continue
        monthly = sub.groupby("ym")["amount_eok"].median().reset_index()
        fig.add_trace(
            go.Scatter(
                x=monthly["ym"], y=monthly["amount_eok"],
                mode="lines+markers",
                line=dict(color=color, width=2),
                marker=dict(size=5),
                name=label,
                hovertemplate=f"%{{x|%Y-%m}}<br>{label} 중위 %{{y:.2f}}억<extra></extra>",
            )
        )

    apply_dark_theme(fig, margin=dict(l=56, r=16, t=32, b=40))
    fig.update_yaxes(title=dict(text="매매가 (억)", font=dict(size=10)))
    fig.update_layout(legend=dict(orientation="h", x=0, y=1.08, font=dict(size=11)))
    return fig


def _build_listings_chart(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if df.empty:
        fig.add_annotation(
            text="매핑된 매물 데이터 없음 — complex_mapping 을 먼저 갱신하세요",
            showarrow=False, font=dict(color="#777"),
            xref="paper", yref="paper", x=0.5, y=0.5,
        )
        return apply_dark_theme(fig, margin=dict(l=10, r=10, t=10, b=10))

    sale = df[df["trade_type"] == "A1"].copy()
    if sale.empty:
        fig.add_annotation(
            text="매매 매물 없음", showarrow=False, font=dict(color="#777"),
            xref="paper", yref="paper", x=0.5, y=0.5,
        )
        return apply_dark_theme(fig, margin=dict(l=10, r=10, t=10, b=10))

    sale["current_eok"] = sale["current_price"].fillna(0) / 10000.0
    sale["initial_eok"] = sale["initial_price"].fillna(0) / 10000.0

    # first_seen_date 기준 산포 + 활성/비활성 구분
    for is_active, color, name in [(True, POS, "활성"), (False, "#777", "비활성")]:
        sub = sale[sale["is_active"] == is_active]
        if sub.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=sub["first_seen_date"], y=sub["current_eok"],
                mode="markers",
                marker=dict(size=7, color=color, opacity=0.6),
                customdata=sub[["exclusive_area", "initial_eok"]],
                hovertemplate=(
                    "%{x|%Y-%m-%d}<br>호가 %{y:.2f}억 (최초 %{customdata[1]:.2f}억)<br>"
                    "%{customdata[0]}㎡<extra></extra>"
                ),
                name=name,
            )
        )
    apply_dark_theme(fig, margin=dict(l=56, r=16, t=32, b=40))
    fig.update_yaxes(title=dict(text="호가 (억)", font=dict(size=10)))
    fig.update_xaxes(title=dict(text="등록일", font=dict(size=10)))
    fig.update_layout(legend=dict(orientation="h", x=0, y=1.08, font=dict(size=11)))
    return fig


def _build_rents_chart(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if df.empty:
        fig.add_annotation(
            text="전월세 데이터 없음", showarrow=False, font=dict(color="#777"),
            xref="paper", yref="paper", x=0.5, y=0.5,
        )
        return apply_dark_theme(fig, margin=dict(l=10, r=10, t=10, b=10))

    df = df.copy()
    df["equiv_deposit_eok"] = (df["deposit"] + df["monthly_rent"] * 100) / 10000.0

    for rent_type, color, name in [
        ("jeonse", ACCENT_1, "전세 (보증금)"),
        ("rent", "#FF9800", "월세 (환산보증금)"),
    ]:
        sub = df[df["rent_type"] == rent_type]
        if sub.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=sub["deal_date"], y=sub["equiv_deposit_eok"],
                mode="markers",
                marker=dict(size=6, color=color, opacity=0.5),
                customdata=sub[["exclusive_area", "monthly_rent"]],
                hovertemplate=(
                    "%{x|%Y-%m-%d}<br>"
                    "%{y:.2f}억 (월세 %{customdata[1]:,.0f}만원)<br>"
                    "%{customdata[0]}㎡<extra></extra>"
                ),
                name=name,
            )
        )
    apply_dark_theme(fig, margin=dict(l=56, r=16, t=32, b=40))
    fig.update_yaxes(title=dict(text="환산보증금 (억)", font=dict(size=10)))
    fig.update_layout(legend=dict(orientation="h", x=0, y=1.08, font=dict(size=11)))
    return fig


def _build_matrix_chart(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if df.empty:
        fig.add_annotation(
            text="거래 데이터 없음", showarrow=False, font=dict(color="#777"),
            xref="paper", yref="paper", x=0.5, y=0.5,
        )
        return apply_dark_theme(fig, margin=dict(l=10, r=10, t=10, b=10))

    def bucket(area: float) -> str:
        for lo, hi, label in _AREA_BUCKETS:
            if (lo is None or area > lo) and (hi is None or area <= hi):
                return label
        return "기타"

    df = df.copy()
    df["area_bucket"] = df["exclusive_area"].apply(bucket)
    df["floor"] = df["floor"].fillna(0).astype(int)

    pivot = (
        df.groupby(["floor", "area_bucket"]).size().unstack(fill_value=0).sort_index(ascending=False)
    )
    area_order = [b[2] for b in _AREA_BUCKETS if b[2] in pivot.columns]
    pivot = pivot.reindex(columns=area_order)

    fig.add_trace(
        go.Heatmap(
            z=pivot.values,
            x=pivot.columns,
            y=pivot.index,
            colorscale="Blues",
            colorbar=dict(title=dict(text="거래수", font=dict(size=10)), thickness=10),
            hovertemplate="%{y}층 · %{x}<br>%{z}건<extra></extra>",
        )
    )
    apply_dark_theme(fig, margin=dict(l=56, r=16, t=16, b=40))
    fig.update_xaxes(title=dict(text="면적대", font=dict(size=10)))
    fig.update_yaxes(title=dict(text="층", font=dict(size=10)))
    return fig


def _build_info_card(master: dict | None, recent_df: pd.DataFrame) -> list:
    if not master:
        return [
            EmptyState(
                "단지를 선택하세요",
                description="좌측 검색창에서 단지명을 입력하면 상세 정보가 표시됩니다.",
                icon="magnifying-glass",
            )
        ]

    def field(label: str, value: str) -> html.Div:
        return html.Div(
            style={"display": "flex", "justifyContent": "space-between", "padding": "4px 0"},
            children=[
                html.Span(label, style={"color": "var(--fg-3)", "fontSize": 12}),
                html.Span(value, style={"color": "var(--fg-1)", "fontWeight": 500, "fontSize": 13}),
            ],
        )

    meta = html.Div(
        style={"borderBottom": "1px solid var(--border-1)", "paddingBottom": 10, "marginBottom": 10},
        children=[
            html.H3(master.get("apt_name") or "—", style={"margin": "0 0 6px"}),
            html.Div(
                " · ".join(
                    filter(
                        None,
                        [
                            master.get("sido_name"),
                            master.get("sgg_name"),
                            master.get("admin_dong"),
                        ],
                    )
                ),
                style={"color": "var(--fg-3)", "fontSize": 12},
            ),
        ],
    )

    info_fields = [
        field("건축년도", f"{int(master['build_year'])}년" if master.get("build_year") else "—"),
        field("도로명", master.get("road_address") or "—"),
        field("지번", master.get("jibun_address") or "—"),
        field(
            "좌표",
            f"{master.get('latitude'):.4f}, {master.get('longitude'):.4f}"
            if master.get("latitude") and master.get("longitude")
            else "—",
        ),
    ]

    recent_rows: list = []
    if not recent_df.empty:
        for _, r in recent_df.iterrows():
            recent_rows.append(
                html.Div(
                    style={
                        "display": "flex",
                        "justifyContent": "space-between",
                        "padding": "3px 0",
                        "fontSize": 12,
                    },
                    children=[
                        html.Span(str(r["deal_date"]), style={"color": "var(--fg-2)"}),
                        html.Span(
                            f"{format_won(r['deal_amount'])}  ({r['exclusive_area']:.0f}㎡·{int(r['floor'])}층)",
                            style={"color": "var(--fg-1)"},
                        ),
                    ],
                )
            )
    if not recent_rows:
        recent_rows = [
            html.Div("최근 거래 없음", style={"color": "var(--fg-3)", "fontSize": 12})
        ]
    recent_block = [
        html.Div(
            "최근 거래",
            style={"color": "var(--fg-3)", "fontSize": 12, "marginTop": 12, "marginBottom": 6},
        ),
        *recent_rows,
    ]

    return [meta, *info_fields, *recent_block]


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------


@callback(
    Output("page-complex-picker-grid", "rowData"),
    Output("page-complex-picker-sub", "children"),
    Input("f-sido", "value"),
    Input("f-sgg", "value"),
)
def _load_picker(sido, sgg):
    sido = sido or "서울특별시"
    try:
        df = mq.get_complex_ranking(
            sido=sido,
            sgg=sgg if sgg and sgg != "전체" else None,
            order_by="trade_count_6m",
            limit=200,
        )
        df["last_deal_date"] = df["last_deal_date"].astype(str).replace("NaT", "")
        rows = df.to_dict("records")
    except Exception:
        rows = []
    scope = f"{sido}" + (f" · {sgg}" if sgg and sgg != "전체" else "")
    sub = f"{scope} · 상위 {len(rows):,} 단지 · 행 클릭 시 선택"
    return rows, sub


@callback(
    Output("page-complex-search", "value", allow_duplicate=True),
    Input("page-complex-picker-grid", "selectedRows"),
    prevent_initial_call=True,
)
def _picker_to_dropdown(selected):
    if not selected:
        raise PreventUpdate
    apt_id = (selected[0] or {}).get("apt_id")
    if not apt_id:
        raise PreventUpdate
    return apt_id


@callback(
    Output("page-complex-search", "options"),
    Input("page-complex-search", "search_value"),
    State("page-complex-search", "value"),
)
def _search_options(search_value, current_value):
    q = (search_value or "").strip()
    if len(q) < 1:
        raise PreventUpdate
    rows = rtq.search_complexes(q, limit=30)
    options = [
        {
            "label": f"{r['apt_name']} · {r.get('sgg_name') or ''} {r.get('admin_dong') or ''}".strip(),
            "value": r["apt_id"],
        }
        for r in rows
    ]
    # 현재 선택된 값이 options 에 없으면 추가 (persistence 로 유지되도록)
    if current_value and not any(o["value"] == current_value for o in options):
        options.insert(0, {"label": current_value, "value": current_value})
    return options


@callback(
    Output("page-complex-search", "value", allow_duplicate=True),
    Input("_url", "search"),
    State("_url", "pathname"),
    prevent_initial_call="initial_duplicate",
)
def _url_to_apt_id(search: str | None, pathname: str | None):
    """/complex?apt_id=... 진입 시 검색창에 주입."""
    if pathname != "/complex" or not search:
        raise PreventUpdate
    apt_id = parse_qs(search.lstrip("?")).get("apt_id", [None])[0]
    if not apt_id:
        raise PreventUpdate
    return apt_id


@callback(
    Output("user-prefs", "data", allow_duplicate=True),
    Input("page-complex-search", "value"),
    State("user-prefs", "data"),
    prevent_initial_call=True,
)
def _push_recent(apt_id, prefs):
    if not apt_id:
        raise PreventUpdate
    prefs = dict(prefs or {})
    recent: list = list(prefs.get("complex_recent") or [])
    recent = [apt_id, *[x for x in recent if x != apt_id]][:5]
    prefs["complex_recent"] = recent
    return prefs


@callback(
    Output("page-complex-sub", "children"),
    Output("kpi-complex-trade-v", "children"),
    Output("kpi-complex-primary-v", "children"),
    Output("kpi-complex-ppm2-v", "children"),
    Output("kpi-complex-recent-v", "children"),
    Output("page-complex-chart", "figure"),
    Output("page-complex-info", "children"),
    Input("page-complex-search", "value"),
    Input("page-complex-tabs", "value"),
)
def _refresh_complex(apt_id, tab):
    if not apt_id:
        empty_fig = go.Figure()
        empty_fig.add_annotation(
            text="단지를 선택하세요", showarrow=False, font=dict(color="#777"),
            xref="paper", yref="paper", x=0.5, y=0.5,
        )
        apply_dark_theme(empty_fig, margin=dict(l=10, r=10, t=10, b=10))
        return (
            "단지를 검색하세요",
            "—", "—", "—", "—",
            empty_fig,
            [
                EmptyState(
                    "단지를 선택하세요",
                    description="좌측 검색창에서 단지명을 입력하면 상세 정보가 표시됩니다.",
                    icon="magnifying-glass",
                )
            ],
        )

    master = rtq.get_rt_complex_master(apt_id)
    recent_df = rtq.recent_trades(apt_id, limit=5)

    # Sub / KPIs
    if master:
        sub = " · ".join(filter(None, [master.get("apt_name"), master.get("sgg_name")]))
        trade_v = format_count(master.get("trade_count_6m"))
        primary = master.get("primary_area_m2")
        primary_v = f"{float(primary):.0f}㎡" if primary else "—"
        ppm2_v = format_ppm2(master.get("median_ppm2_6m"))
        recent_v = str(master.get("last_deal_date") or "—")
    else:
        sub = apt_id
        trade_v = primary_v = ppm2_v = recent_v = "—"

    # Chart per tab
    try:
        if tab == "listings":
            fig = _build_listings_chart(nvq.listings_by_apt_id(apt_id))
        elif tab == "rents":
            fig = _build_rents_chart(rtq.rents_by_complex(apt_id))
        elif tab == "matrix":
            fig = _build_matrix_chart(rtq.trades_by_complex(apt_id))
        else:
            fig = _build_trades_chart(rtq.trades_by_complex(apt_id))
    except Exception:
        fig = go.Figure()
        fig.add_annotation(
            text="쿼리 오류", showarrow=False, font=dict(color="var(--neg)"),
            xref="paper", yref="paper", x=0.5, y=0.5,
        )
        apply_dark_theme(fig, margin=dict(l=10, r=10, t=10, b=10))

    return (
        sub, trade_v, primary_v, ppm2_v, recent_v,
        fig,
        _build_info_card(master, recent_df),
    )

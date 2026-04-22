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
import dash_leaflet as dl
import pandas as pd
import plotly.graph_objects as go
from dash import ALL, Input, Output, State, callback, ctx, dcc, html
from dash.exceptions import PreventUpdate

from dash_app.components.empty_state import EmptyState
from dash_app.components.formatters import format_percent, format_ppm2, format_won
from dash_app.components.kpi_card import KpiCard
from dash_app.components.ranking_table import RankingTable
from dash_app.queries import metrics_queries as mq
from dash_app.queries import nv_queries as nvq
from dash_app.queries import rt_queries as rtq
from dash_app.theme import ACCENT_1, NEG, POS, apply_dark_theme

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


_PICKER_COLUMNS: list[dict] = [
    {"field": "apt_name", "headerName": "단지", "minWidth": 160},
    {"field": "sgg", "headerName": "자치구", "minWidth": 90},
    {"field": "admin_dong", "headerName": "행정동", "minWidth": 90},
    {"field": "road_address", "headerName": "도로명", "minWidth": 180, "flex": 1},
    {"field": "build_year", "headerName": "건축년도", "width": 100, "minWidth": 90,
     "type": "numericColumn"},
    {"field": "primary_area_m2", "headerName": "주력면적", "width": 100, "minWidth": 90,
     "type": "numericColumn",
     "valueFormatter": {"function": "params.value == null ? '—' : d3.format(',.0f')(params.value) + '㎡'"}},
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
            KpiCard("단지명", value_id="kpi-complex-name-v"),
            KpiCard("단위면적가 (6M)", value_id="kpi-complex-ppm2-v", term="단위면적가"),
            # 갭 / 전세가율은 주력 면적 기준 6M 중위값. 표본 부족 시 "—".
            KpiCard("갭 (6M)", value_id="kpi-complex-gap-v", term="갭"),
            KpiCard("전세가율 (6M)", value_id="kpi-complex-jr-v", term="전세가율"),
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
                    dcc.Tab(label="매매(실거래가) 추이", value="trades"),
                    dcc.Tab(label="매매 호가 분포", value="listings"),
                    dcc.Tab(label="전월세(실거래가) 추이", value="rents"),
                ],
            ),
            html.Div(
                id="page-complex-chart-caption",
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
            ),
            dcc.Graph(
                id="page-complex-chart",
                config={"displayModeBar": False, "responsive": True},
                style={"height": 420, "marginTop": 4},
            ),
        ],
    )


_TAB_CAPTIONS: dict[str, str] = {
    "trades": "면적대별 월 중위 매매가 라인. 회색 점은 개별 거래.",
    "listings": (
        "면적대별 활성 매물 호가 분포(바이올린). 빨간 가로선은 같은 면적대의 6개월 실거래 중위가입니다. "
        "빨간 선이 분포의 가운데 박스 안쪽이면 호가가 실거래와 비슷, "
        "박스 아래쪽이면 호가가 실거래보다 높게 형성된 '호가 거품' 신호, "
        "박스 위쪽이면 매물이 실거래보다 낮게 나온 '저평가' 신호입니다."
    ),
    "rents": "면적대별 월 중위. 위=전세 보증금(억), 아래=월세료(만원). 회색 점은 개별 거래.",
}


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
            "선택한 아파트 단지의 실거래가 추이, 호가 분포, 전월세 추이를 한 화면에서 확인합니다. "
            "검색창에 단지명을 입력하거나 단지 탐색 테이블에서 행을 클릭하면, "
            "KPI · 차트 · 우측 정보 카드가 모두 그 단지로 갱신됩니다."
        ),
    )


layout = html.Main(
    className="fd-main",
    children=[
        _page_head(),
        _intent_caption(),
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
    fig.update_xaxes(type="date", tickformat="%Y-%m")
    fig.update_layout(legend=dict(orientation="h", x=0, y=1.08, font=dict(size=11)))
    return fig


def _build_listings_chart(listings: pd.DataFrame, trades: pd.DataFrame) -> go.Figure:
    """면적대별 활성 매물 호가 분포 박스플롯 + 같은 면적대 6M 실거래 중위가 overlay.

    호가는 시계열보다 '현재 시장 분포 vs 실거래' 비교가 핵심 인사이트.
    """
    fig = go.Figure()
    if listings.empty:
        fig.add_annotation(
            text="이 단지는 네이버 매물 정보가 연결되지 않았습니다",
            showarrow=False, font=dict(color="#777"),
            xref="paper", yref="paper", x=0.5, y=0.5,
        )
        return apply_dark_theme(fig, margin=dict(l=10, r=10, t=10, b=10))

    sale = listings[(listings["trade_type"] == "A1") & (listings["is_active"] == True)].copy()  # noqa: E712
    if sale.empty:
        fig.add_annotation(
            text="활성 매매 매물 없음", showarrow=False, font=dict(color="#777"),
            xref="paper", yref="paper", x=0.5, y=0.5,
        )
        return apply_dark_theme(fig, margin=dict(l=10, r=10, t=10, b=10))

    def bucket(area: float) -> str:
        for lo, hi, label in _AREA_BUCKETS:
            if (lo is None or area > lo) and (hi is None or area <= hi):
                return label
        return "기타"

    sale["current_eok"] = sale["current_price"].fillna(0) / 10000.0
    sale["area_bucket"] = sale["exclusive_area"].apply(bucket)

    area_order = [b[2] for b in _AREA_BUCKETS]
    colors = ["#4facfe", "#00f2fe", "#9C27B0", "#FF9800"]

    for label, color in zip(area_order, colors):
        sub = sale[sale["area_bucket"] == label]
        if sub.empty:
            continue
        fig.add_trace(
            go.Violin(
                y=sub["current_eok"],
                x=[label] * len(sub),
                name=label,
                marker=dict(color=color, opacity=0.55, size=5),
                line=dict(color=color),
                fillcolor=f"rgba{(*_hex_to_rgb(color), 0.18)}",
                box_visible=True,
                meanline_visible=True,
                points="all",
                jitter=0.4,
                pointpos=0,
                hovertemplate=f"{label}<br>호가 %{{y:.2f}}억<extra></extra>",
                showlegend=False,
                spanmode="hard",
            )
        )

    # 6M 실거래 중위 overlay
    if not trades.empty:
        recent = trades.copy()
        recent["deal_date"] = pd.to_datetime(recent["deal_date"])
        cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=180)
        recent = recent[recent["deal_date"] >= cutoff]
        if not recent.empty:
            recent["area_bucket"] = recent["exclusive_area"].apply(bucket)
            recent["amount_eok"] = recent["deal_amount"] / 10000.0
            med = recent.groupby("area_bucket")["amount_eok"].agg(["median", "size"])
            x_med = [b for b in area_order if b in med.index]
            if x_med:
                fig.add_trace(
                    go.Scatter(
                        x=x_med,
                        y=[float(med.loc[b, "median"]) for b in x_med],
                        customdata=[int(med.loc[b, "size"]) for b in x_med],
                        mode="markers",
                        marker=dict(symbol="line-ew", size=42,
                                    line=dict(color=NEG, width=3)),
                        name="실거래 중위 (6M)",
                        hovertemplate="%{x}<br>실거래 중위 %{y:.2f}억 (%{customdata}건)<extra></extra>",
                    )
                )

    apply_dark_theme(fig, margin=dict(l=56, r=16, t=32, b=40))
    fig.update_yaxes(title=dict(text="가격 (억)", font=dict(size=10)))
    fig.update_xaxes(title=dict(text="면적대", font=dict(size=10)),
                     categoryorder="array", categoryarray=area_order)
    fig.update_layout(legend=dict(orientation="h", x=0, y=1.08, font=dict(size=11)),
                      violinmode="group")
    return fig


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _build_rents_chart(df: pd.DataFrame) -> go.Figure:
    """전세(상)·월세(하) 분리 + 각 서브플롯에 면적대별 월 중위 라인."""
    from plotly.subplots import make_subplots

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.12,
        subplot_titles=("전세 (보증금)", "월세 (월세료)"),
    )
    if df.empty:
        fig.add_annotation(
            text="전월세 데이터 없음", showarrow=False, font=dict(color="#777"),
            xref="paper", yref="paper", x=0.5, y=0.5,
        )
        return apply_dark_theme(fig, margin=dict(l=10, r=10, t=10, b=10))

    def bucket(area: float) -> str:
        for lo, hi, label in _AREA_BUCKETS:
            if (lo is None or area > lo) and (hi is None or area <= hi):
                return label
        return "기타"

    df = df.copy()
    df["deposit_eok"] = df["deposit"] / 10000.0
    df["area_bucket"] = df["exclusive_area"].apply(bucket)
    df["ym"] = pd.to_datetime(df["deal_date"]).dt.to_period("M").dt.to_timestamp()

    colors = ["#4facfe", "#00f2fe", "#9C27B0", "#FF9800"]

    jeonse = df[df["rent_type"] == "jeonse"]
    if not jeonse.empty:
        fig.add_trace(
            go.Scatter(
                x=jeonse["deal_date"], y=jeonse["deposit_eok"],
                mode="markers",
                marker=dict(size=5, color="#777", opacity=0.3),
                customdata=jeonse[["exclusive_area", "floor", "area_bucket"]],
                hovertemplate=(
                    "%{x|%Y-%m-%d}<br>보증금 %{y:.2f}억<br>"
                    "%{customdata[0]}㎡ · %{customdata[1]}층 · %{customdata[2]}<extra></extra>"
                ),
                name="개별 거래",
                legendgroup="raw",
                showlegend=True,
            ),
            row=1, col=1,
        )
        for (_, _, label), color in zip(_AREA_BUCKETS, colors):
            sub = jeonse[jeonse["area_bucket"] == label]
            if sub.empty:
                continue
            monthly = sub.groupby("ym")["deposit_eok"].median().reset_index()
            fig.add_trace(
                go.Scatter(
                    x=monthly["ym"], y=monthly["deposit_eok"],
                    mode="lines+markers",
                    line=dict(color=color, width=2),
                    marker=dict(size=4),
                    name=label,
                    legendgroup=label,
                    hovertemplate=f"%{{x|%Y-%m}}<br>{label} 전세 중위 %{{y:.2f}}억<extra></extra>",
                ),
                row=1, col=1,
            )

    wolse = df[df["rent_type"] == "rent"]
    if not wolse.empty:
        fig.add_trace(
            go.Scatter(
                x=wolse["deal_date"], y=wolse["monthly_rent"],
                mode="markers",
                marker=dict(size=5, color="#777", opacity=0.3),
                customdata=wolse[["exclusive_area", "floor", "deposit_eok", "area_bucket"]],
                hovertemplate=(
                    "%{x|%Y-%m-%d}<br>월세 %{y:,.0f}만원 (보증금 %{customdata[2]:.2f}억)<br>"
                    "%{customdata[0]}㎡ · %{customdata[1]}층 · %{customdata[3]}<extra></extra>"
                ),
                name="개별 거래",
                legendgroup="raw",
                showlegend=False,  # 전세 쪽과 묶임
            ),
            row=2, col=1,
        )
        for (_, _, label), color in zip(_AREA_BUCKETS, colors):
            sub = wolse[wolse["area_bucket"] == label]
            if sub.empty:
                continue
            monthly = sub.groupby("ym")["monthly_rent"].median().reset_index()
            fig.add_trace(
                go.Scatter(
                    x=monthly["ym"], y=monthly["monthly_rent"],
                    mode="lines+markers",
                    line=dict(color=color, width=2),
                    marker=dict(size=4),
                    name=label,
                    legendgroup=label,
                    showlegend=False,  # 전세 라인과 같은 그룹 — 한 번만 노출
                    hovertemplate=f"%{{x|%Y-%m}}<br>{label} 월세 중위 %{{y:,.0f}}만원<extra></extra>",
                ),
                row=2, col=1,
            )

    apply_dark_theme(fig, margin=dict(l=56, r=16, t=36, b=40))
    fig.update_yaxes(title=dict(text="보증금 (억)", font=dict(size=10)), row=1, col=1)
    fig.update_yaxes(title=dict(text="월세 (만원)", font=dict(size=10)), row=2, col=1)
    fig.update_xaxes(type="date", tickformat="%Y-%m")
    fig.update_layout(legend=dict(orientation="h", x=0, y=1.10, font=dict(size=11)))
    return fig


def _build_mini_map(master: dict) -> html.Div | None:
    """단지 좌표 강조 marker (halo + dot). 좌표 없으면 None."""
    lat, lon = master.get("latitude"), master.get("longitude")
    if not lat or not lon:
        return None
    lat, lon = float(lat), float(lon)
    name = master.get("apt_name") or "단지"
    return html.Div(
        style={"height": "180px", "marginBottom": 10, "borderRadius": 8, "overflow": "hidden"},
        children=dl.Map(
            center=[lat, lon],
            zoom=16,
            scrollWheelZoom=False,
            zoomControl=False,
            attributionControl=False,
            style={"height": "100%", "width": "100%"},
            children=[
                dl.TileLayer(
                    url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
                    attribution="© OpenStreetMap contributors",
                ),
                # halo — 시인성 강화 (반투명 큰 원)
                dl.CircleMarker(
                    center=[lat, lon],
                    radius=22,
                    color=NEG,
                    fillColor=NEG,
                    fillOpacity=0.18,
                    weight=0,
                ),
                # dot — 흰 테두리 + 진한 빨강 채움
                dl.CircleMarker(
                    center=[lat, lon],
                    radius=9,
                    color="#ffffff",
                    fillColor=NEG,
                    fillOpacity=1.0,
                    weight=3,
                    children=[dl.Tooltip(name, permanent=False, direction="top")],
                ),
            ],
        ),
    )


def _build_info_card(master: dict | None, recent_df: pd.DataFrame) -> list:
    if not master:
        return [
            EmptyState(
                "단지를 선택하세요",
                description="좌측 검색창에서 단지명을 입력하면 상세 정보가 표시됩니다.",
                icon="magnifying-glass",
            )
        ]

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

    mini_map = _build_mini_map(master)
    head = [mini_map, meta] if mini_map else [meta]
    return [*head, *recent_block]


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
    Output("kpi-complex-name-v", "children"),
    Output("kpi-complex-ppm2-v", "children"),
    Output("kpi-complex-gap-v", "children"),
    Output("kpi-complex-jr-v", "children"),
    Output("page-complex-chart", "figure"),
    Output("page-complex-info", "children"),
    Input("page-complex-search", "value"),
    Input("page-complex-tabs", "value"),
    Input("_url", "search"),
    State("_url", "pathname"),
)
def _refresh_complex(apt_id, tab, url_search, pathname):
    # dropdown 에 set 이 안 된 채 페이지 진입했을 때 (e.g. 다른 페이지 → window.location.assign 으로 이동)
    # URL search 에서 apt_id fallback 추출.
    if not apt_id and pathname == "/complex" and url_search:
        apt_id = parse_qs(url_search.lstrip("?")).get("apt_id", [None])[0]
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
    recent_df = rtq.recent_trades(apt_id, limit=10)

    # Sub / KPIs
    if master:
        sub = " · ".join(filter(None, [master.get("apt_name"), master.get("sgg_name")]))
        name_v = master.get("apt_name") or "—"
        primary = master.get("primary_area_m2")
        ppm2_v = format_ppm2(master.get("median_ppm2_6m"))
        gap_metrics = rtq.gap_metrics_by_complex(apt_id, primary)
        gap_v = format_won(gap_metrics["gap"]) if gap_metrics else "—"
        jr_v = format_percent(gap_metrics["jeonse_ratio"]) if gap_metrics else "—"
    else:
        sub = apt_id
        name_v = ppm2_v = gap_v = jr_v = "—"

    # Chart per tab
    try:
        if tab == "listings":
            fig = _build_listings_chart(
                nvq.listings_by_apt_id(apt_id),
                rtq.trades_by_complex(apt_id),
            )
        elif tab == "rents":
            fig = _build_rents_chart(rtq.rents_by_complex(apt_id))
        else:
            fig = _build_trades_chart(rtq.trades_by_complex(apt_id))
    except Exception:
        fig = go.Figure()
        fig.add_annotation(
            text="데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.",
            showarrow=False, font=dict(color="var(--neg)"),
            xref="paper", yref="paper", x=0.5, y=0.5,
        )
        apply_dark_theme(fig, margin=dict(l=10, r=10, t=10, b=10))

    return (
        sub, name_v, ppm2_v, gap_v, jr_v,
        fig,
        _build_info_card(master, recent_df),
    )


@callback(
    Output("page-complex-chart-caption", "children"),
    Input("page-complex-tabs", "value"),
)
def _update_chart_caption(tab):
    return _TAB_CAPTIONS.get(tab or "trades", "")


@callback(
    Output("page-complex-recent", "children"),
    Input("user-prefs", "data"),
)
def _render_recent_chips(prefs):
    recent: list = list((prefs or {}).get("complex_recent") or [])
    if not recent:
        return []
    name_map = rtq.get_complex_names(recent)
    return [
        html.Button(
            name_map.get(apt_id) or apt_id,
            id={"role": "complex-recent-chip", "value": apt_id},
            className="c-chip",
            n_clicks=0,
            title=name_map.get(apt_id) or apt_id,
        )
        for apt_id in recent
        if apt_id in name_map
    ]


@callback(
    Output("page-complex-search", "value", allow_duplicate=True),
    Input({"role": "complex-recent-chip", "value": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _recent_chip_to_dropdown(clicks):
    if not any(clicks or []):
        raise PreventUpdate
    trig = ctx.triggered_id
    if not isinstance(trig, dict) or trig.get("role") != "complex-recent-chip":
        raise PreventUpdate
    apt_id = trig.get("value")
    if not apt_id:
        raise PreventUpdate
    return apt_id


@callback(
    Output("page-complex-picker-grid", "selectedRows"),
    Output("page-complex-picker-grid", "scrollTo"),
    Input("page-complex-search", "value"),
    State("page-complex-picker-grid", "rowData"),
    State("page-complex-picker-grid", "selectedRows"),
    prevent_initial_call=True,
)
def _sync_grid_to_search(apt_id, rows, current_selected):
    """검색창(드롭다운/칩/URL/grid 클릭)에서 단지가 정해지면 grid 행도 그 단지로 동기화 + 페이지 점프."""
    if not apt_id or not rows:
        raise PreventUpdate
    # 이미 같은 단지가 선택되어 있으면 no-op (grid → dropdown → grid 루프 방지)
    if current_selected and (current_selected[0] or {}).get("apt_id") == apt_id:
        raise PreventUpdate
    matched = [r for r in rows if r.get("apt_id") == apt_id]
    if not matched:
        raise PreventUpdate
    return matched, {"rowId": apt_id, "rowPosition": "middle"}

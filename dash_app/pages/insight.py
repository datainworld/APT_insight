"""뉴스 & RAG 페이지 (/insight) — 스펙 3.6.

구성:
- 상단 status banner (지역/전국/정책 뉴스 수)
- 좌: 최근 뉴스 타임라인
- 중: 뉴스 viz — regional 집중도에 따른 3단계 fallback
    * regional ≥ 3: 시군구 heatmap
    * 0 < regional < 3: 축소 heatmap + 카테고리 스트립
    * regional == 0: 카테고리 × 날짜 heatmap
- 우: RAG 검색 (업로드된 PDF 문서 top-k snippets)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import dash
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, callback, dcc, html

from dash_app.components.empty_state import EmptyState
from dash_app.components.status_banner import StatusBanner
from dash_app.queries import news_queries as nq
from dash_app.theme import ACCENT_1, apply_dark_theme

dash.register_page(
    __name__,
    path="/insight",
    name="뉴스 & RAG",
    order=6,
    title="APT Insight — 뉴스 & RAG",
)


_KST = timezone(timedelta(hours=9))
_SCOPE_LOOKBACK_DAYS = 14
_CATEGORIES = ("market", "policy", "rates", "other")


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


def _page_head() -> html.Div:
    return html.Div(
        className="page-head",
        children=[
            html.H1("뉴스 & RAG"),
            html.Div(
                className="live",
                children=[
                    html.Span(className="dot-live"),
                    html.Span(f"최근 {_SCOPE_LOOKBACK_DAYS}일"),
                ],
            ),
        ],
    )


def _status_slot() -> html.Div:
    return html.Div(id="page-insight-status", children=[])


def _news_timeline() -> html.Div:
    return html.Div(
        className="card",
        children=[
            html.Div(
                className="card-head",
                children=[
                    html.Div(className="ic", children=html.I(className="fa-solid fa-newspaper")),
                    html.Div(className="t", children="뉴스 타임라인"),
                    html.Div(className="s", children=f"최근 {_SCOPE_LOOKBACK_DAYS}일 · 광고 제외"),
                ],
            ),
            html.Div(
                id="page-insight-timeline",
                className="news-list",
                style={
                    "maxHeight": 540,
                    "overflowY": "auto",
                    "padding": "4px 2px",
                },
            ),
        ],
    )


def _viz_card() -> html.Div:
    return html.Div(
        className="card",
        children=[
            html.Div(
                className="card-head",
                children=[
                    html.Div(className="ic", children=html.I(className="fa-solid fa-fire")),
                    html.Div(className="t", children="뉴스 히트맵"),
                    html.Div(
                        className="s",
                        id="page-insight-viz-sub",
                        children="지역 집중도에 따라 자동 전환",
                    ),
                ],
            ),
            dcc.Graph(
                id="page-insight-viz",
                config={"displayModeBar": False, "responsive": True},
                style={"height": 480},
            ),
        ],
    )


def _rag_panel() -> html.Div:
    return html.Div(
        className="card",
        children=[
            html.Div(
                className="card-head",
                children=[
                    html.Div(className="ic", children=html.I(className="fa-solid fa-file-pdf")),
                    html.Div(className="t", children="PDF RAG 검색"),
                    html.Div(className="s", children="업로드 문서에서 유사 청크 Top 3"),
                ],
            ),
            html.Div(
                style={"display": "flex", "gap": 8, "padding": "10px 12px"},
                children=[
                    dcc.Input(
                        id="page-insight-rag-input",
                        type="text",
                        placeholder="문서에서 검색할 질의어",
                        debounce=True,
                        style={"flex": 1},
                    ),
                    html.Button(
                        html.I(className="fa-solid fa-magnifying-glass"),
                        id="page-insight-rag-btn",
                        className="btn-apply",
                        style={"width": 40},
                    ),
                ],
            ),
            html.Div(
                id="page-insight-rag-results",
                style={"maxHeight": 420, "overflowY": "auto", "padding": "0 12px 12px"},
            ),
        ],
    )


layout = html.Main(
    className="fd-main",
    children=[
        _page_head(),
        _status_slot(),
        html.Div(
            className="row3-insight",
            style={
                "display": "grid",
                "gridTemplateColumns": "300px 1fr 340px",
                "gap": "16px",
            },
            children=[_news_timeline(), _viz_card(), _rag_panel()],
        ),
    ],
)


# ---------------------------------------------------------------------------
# Chart / render helpers
# ---------------------------------------------------------------------------


def _empty_fig(msg: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=msg, showarrow=False, font=dict(color="#777", size=13),
        xref="paper", yref="paper", x=0.5, y=0.5,
    )
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return apply_dark_theme(fig, margin=dict(l=10, r=10, t=10, b=10))


def _build_regional_heatmap(df: pd.DataFrame) -> go.Figure:
    """scope=regional 인 뉴스의 시군구 × 날짜 heatmap."""
    if df.empty:
        return _empty_fig("지역 뉴스 없음")
    df = df.copy()
    df["date"] = pd.to_datetime(df["published_at"]).dt.date.astype(str)
    pivot = (
        df.groupby(["sgg_name", "date"]).size().unstack(fill_value=0)
    )
    fig = go.Figure(
        go.Heatmap(
            z=pivot.values,
            x=pivot.columns,
            y=pivot.index,
            colorscale="Oranges",
            hovertemplate="%{y} · %{x}<br>%{z}건<extra></extra>",
            colorbar=dict(title=dict(text="건수", font=dict(size=10)), thickness=10),
        )
    )
    apply_dark_theme(fig, margin=dict(l=100, r=16, t=10, b=40))
    fig.update_xaxes(title=dict(text="발행일", font=dict(size=10)))
    fig.update_yaxes(title=dict(text="시군구", font=dict(size=10)))
    return fig


def _build_category_heatmap(df: pd.DataFrame) -> go.Figure:
    """카테고리 × 날짜 heatmap (regional 뉴스 없을 때 fallback)."""
    if df.empty:
        return _empty_fig("뉴스 없음")
    df = df.copy()
    df["date"] = pd.to_datetime(df["published_at"]).dt.date.astype(str)
    df["category"] = df["category"].fillna("other")
    pivot = (
        df.groupby(["category", "date"]).size().unstack(fill_value=0)
    )
    # 카테고리 순서 고정
    pivot = pivot.reindex(index=[c for c in _CATEGORIES if c in pivot.index])
    fig = go.Figure(
        go.Heatmap(
            z=pivot.values,
            x=pivot.columns,
            y=pivot.index,
            colorscale="Blues",
            hovertemplate="%{y} · %{x}<br>%{z}건<extra></extra>",
            colorbar=dict(title=dict(text="건수", font=dict(size=10)), thickness=10),
        )
    )
    apply_dark_theme(fig, margin=dict(l=90, r=16, t=10, b=40))
    fig.update_xaxes(title=dict(text="발행일", font=dict(size=10)))
    fig.update_yaxes(title=dict(text="카테고리", font=dict(size=10)))
    return fig


def _render_news_item(row: dict) -> html.A:
    scope = row.get("scope", "unknown")
    scope_color = {
        "regional": "#4facfe",
        "national": "#9C27B0",
        "policy": "#FF9800",
        "unknown": "#777",
    }.get(scope, "#777")
    return html.A(
        href=row.get("url", "#"),
        target="_blank",
        style={"textDecoration": "none", "color": "inherit"},
        children=html.Div(
            style={
                "padding": "8px 10px",
                "borderBottom": "1px solid var(--border-1)",
                "cursor": "pointer",
            },
            children=[
                html.Div(
                    style={"display": "flex", "gap": 6, "alignItems": "center",
                           "marginBottom": 4, "fontSize": 11},
                    children=[
                        html.Span(
                            scope,
                            style={
                                "color": scope_color, "fontWeight": 600,
                                "textTransform": "uppercase", "letterSpacing": ".6px",
                            },
                        ),
                        html.Span("·", style={"color": "var(--fg-3)"}),
                        html.Span(row.get("publisher") or "—", style={"color": "var(--fg-3)"}),
                        html.Span("·", style={"color": "var(--fg-3)"}),
                        html.Span(
                            _format_relative_time(row.get("published_at")),
                            style={"color": "var(--fg-3)"},
                        ),
                    ],
                ),
                html.Div(
                    row.get("title", ""),
                    style={"fontSize": 13, "color": "var(--fg-1)", "lineHeight": 1.4},
                ),
                html.Div(
                    row.get("sgg_name") or "",
                    style={"fontSize": 11, "color": "var(--fg-3)", "marginTop": 2},
                ),
            ],
        ),
    )


def _format_relative_time(dt: Any) -> str:
    if dt is None or pd.isna(dt):
        return "—"
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return str(dt)
    if isinstance(dt, pd.Timestamp):
        dt = dt.to_pydatetime()
    now = datetime.now(_KST)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_KST)
    delta = now - dt
    if delta.days >= 7:
        return dt.strftime("%m-%d")
    if delta.days >= 1:
        return f"{delta.days}일 전"
    hours = delta.seconds // 3600
    if hours >= 1:
        return f"{hours}시간 전"
    minutes = (delta.seconds // 60) or 1
    return f"{minutes}분 전"


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------


@callback(
    Output("page-insight-status", "children"),
    Output("page-insight-timeline", "children"),
    Output("page-insight-viz", "figure"),
    Output("page-insight-viz-sub", "children"),
    Input("_url", "pathname"),
)
def _refresh_insight(pathname: str | None):
    if pathname != "/insight":
        raise dash.exceptions.PreventUpdate

    counts = nq.get_status_counts(scope_days=_SCOPE_LOOKBACK_DAYS)
    banner = StatusBanner(
        items=[
            {"label": "지역 뉴스", "value": counts.get("regional", 0)},
            {"label": "전국", "value": counts.get("national", 0)},
            {"label": "정책", "value": counts.get("policy", 0)},
            {"label": "기타", "value": counts.get("unknown", 0)},
        ],
        kind="info" if counts.get("regional", 0) >= 3 else "warning",
    )

    # timeline
    timeline_df = nq.fetch(scope_days=_SCOPE_LOOKBACK_DAYS, limit=50)
    if timeline_df.empty:
        timeline_children: list = [
            EmptyState("뉴스 없음", description="collect_news 를 한 번 실행해 주세요.")
        ]
    else:
        timeline_children = [_render_news_item(r) for r in timeline_df.to_dict("records")]

    # viz (3-stage fallback)
    regional = counts.get("regional", 0)
    if regional >= 3:
        rdf = nq.fetch(scope_days=_SCOPE_LOOKBACK_DAYS, scope="regional", limit=500)
        fig = _build_regional_heatmap(rdf)
        sub = f"지역 뉴스 {regional}건 — 시군구 × 날짜"
    elif regional > 0:
        adf = nq.fetch(scope_days=_SCOPE_LOOKBACK_DAYS, limit=500)
        fig = _build_category_heatmap(adf)
        sub = f"지역 뉴스 {regional}건(소량) — 카테고리 × 날짜로 대체"
    else:
        adf = nq.fetch(scope_days=_SCOPE_LOOKBACK_DAYS, limit=500)
        fig = _build_category_heatmap(adf)
        sub = "지역 뉴스 없음 — 카테고리 × 날짜"

    return banner, timeline_children, fig, sub


@callback(
    Output("page-insight-rag-results", "children"),
    Input("page-insight-rag-btn", "n_clicks"),
    Input("page-insight-rag-input", "n_submit"),
    State("page-insight-rag-input", "value"),
    prevent_initial_call=True,
)
def _run_rag_search(_n_clicks, _n_submit, query):
    q = (query or "").strip()
    if not q:
        return [EmptyState("질의어 입력", description="문서에서 검색할 키워드를 입력하세요.")]

    try:
        from agents.config import get_vector_store

        store = get_vector_store()
        docs = store.similarity_search(q, k=3)
    except Exception as e:
        return [
            EmptyState(
                "검색 실패",
                description=f"벡터스토어 오류: {e}",
                icon="triangle-exclamation",
            )
        ]

    if not docs:
        return [
            EmptyState(
                "검색 결과 없음",
                description="업로드된 PDF 문서가 없거나 관련 청크를 찾지 못했습니다.",
                icon="file-circle-question",
            )
        ]

    nodes: list = []
    for i, d in enumerate(docs, 1):
        meta = getattr(d, "metadata", {}) or {}
        source = meta.get("source") or "—"
        page = meta.get("page") or meta.get("page_label") or "?"
        content = (d.page_content or "").strip()[:300]
        nodes.append(
            html.Div(
                style={
                    "padding": "10px 4px",
                    "borderBottom": "1px solid var(--border-1)",
                },
                children=[
                    html.Div(
                        style={"display": "flex", "gap": 6, "fontSize": 11,
                               "marginBottom": 6, "color": "var(--fg-3)"},
                        children=[
                            html.Span(f"#{i}", style={"color": ACCENT_1, "fontWeight": 600}),
                            html.Span("·"),
                            html.Span(source),
                            html.Span("·"),
                            html.Span(f"p.{page}"),
                        ],
                    ),
                    html.Div(
                        content + ("…" if len(d.page_content or "") > 300 else ""),
                        style={"fontSize": 12, "color": "var(--fg-1)", "lineHeight": 1.5},
                    ),
                ],
            )
        )
    return nodes

"""전역 사이드바 — 브랜드 + 7페이지 네비게이션 + 필터 패널."""

from __future__ import annotations

from datetime import date

from dash import dcc, html

from dash_app.components.filter_panel import filter_panel
from dash_app.config import PAGES


def _fa(icon: str) -> html.I:
    return html.I(className=f"fa-solid fa-{icon}")


def _nav_link(path: str, name: str, icon: str) -> dcc.Link:
    return dcc.Link(
        [_fa(icon), html.Span(name)],
        href=path,
        id={"role": "page-nav", "path": path},
        className="",  # set by callback to "active" on current path
    )


def _page_nav() -> html.Nav:
    return html.Nav(
        className="page-nav",
        children=[
            html.Div(
                className="brand",
                children=[_fa("building"), html.Span("APT Insight")],
            ),
            *[_nav_link(p["path"], p["name"], p["icon"]) for p in PAGES],
        ],
    )


def sidebar(
    initial_sido: str = "서울특별시",
    last_refresh: date | None = None,
    show_filter: bool = True,
) -> html.Aside:
    """좌측 사이드바. show_filter=False 인 페이지(예: /about)는 필터를 숨긴다."""
    children: list = [_page_nav()]
    if show_filter:
        children.append(filter_panel(initial_sido=initial_sido, last_refresh=last_refresh))
    return html.Aside(className="filter-side", children=children)

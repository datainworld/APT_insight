"""전역 사이드바 — 브랜드 + 7페이지 네비게이션 + 필터 패널."""

from __future__ import annotations

import re
from datetime import date

from dash import html

from dash_app.components.filter_panel import filter_panel
from dash_app.config import PAGES


def _fa(icon: str) -> html.I:
    return html.I(className=f"fa-solid fa-{icon}")


def nav_link_id(path: str) -> str:
    """URL path → HTML-safe string id."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", path).strip("-") or "home"
    return f"page-nav-{slug}"


def _nav_link(path: str, name: str, icon: str) -> html.A:
    # html.A 사용 이유: dcc.Link 는 use_pages + 동일 기반 href 다수일 때 click routing 이
    # 인접 링크로 오라우팅되는 현상이 있었음. 브라우저 표준 a[href] 로 단순 GET 이동.
    # 전체 페이지 재로드 비용은 DB 쿼리(100~500ms) 대비 미미.
    return html.A(
        [_fa(icon), html.Span(name)],
        href=path,
        id=nav_link_id(path),
        className="",
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

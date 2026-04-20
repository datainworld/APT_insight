"""전역 네비게이션 콜백 — 현재 URL 에 해당하는 nav 링크를 active 로 표시."""

from __future__ import annotations

from dash import Input, Output, callback

from dash_app.components.sidebar import nav_link_id
from dash_app.config import PAGES

_OUTPUTS = [Output(nav_link_id(p["path"]), "className") for p in PAGES]


@callback(
    *_OUTPUTS,
    Input("_url", "pathname"),
)
def _highlight_active_nav(pathname: str | None) -> tuple[str, ...]:
    current = pathname or "/"
    return tuple("active" if p["path"] == current else "" for p in PAGES)

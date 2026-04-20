"""전역 네비게이션 콜백 — 현재 URL에 해당하는 nav 링크를 active로 표시."""

from __future__ import annotations

from dash import ALL, Input, Output, State, callback


@callback(
    Output({"role": "page-nav", "path": ALL}, "className"),
    Input("_url", "pathname"),
    State({"role": "page-nav", "path": ALL}, "id"),
)
def _highlight_active_nav(pathname: str | None, ids: list[dict]) -> list[str]:
    current = pathname or "/"
    return ["active" if i["path"] == current else "" for i in ids]

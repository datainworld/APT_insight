"""데이터 없음·오류 상태 표시 — 일관된 톤."""

from __future__ import annotations

from dash import html
from dash.development.base_component import Component


def EmptyState(
    title: str,
    description: str = "",
    action: Component | None = None,
    icon: str = "circle-info",
) -> html.Div:
    """데이터 부재·빈 결과·오류 표시. 파라미터만으로 렌더."""
    children: list = [
        html.Div(html.I(className=f"fa-solid fa-{icon}"), className="empty-state-icon"),
        html.H3(title, className="empty-state-title"),
    ]
    if description:
        children.append(html.P(description, className="empty-state-desc"))
    if action is not None:
        children.append(html.Div(action, className="empty-state-action"))
    return html.Div(className="empty-state", children=children)

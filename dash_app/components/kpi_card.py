"""단일 KPI 타일. 재사용 가능한 순수 함수."""

from __future__ import annotations

from typing import Literal

from dash import html
from dash.development.base_component import Component

from dash_app.components.term_tip import TermTip
from dash_app.glossary.terms import GLOSSARY

DeltaKind = Literal["up", "down", "neutral"]


def KpiCard(
    label: str,
    value_id: str,
    delta_id: str | None = None,
    *,
    value: str = "—",
    delta: str | None = " ",
    delta_kind: DeltaKind = "neutral",
    term: str | None = None,
    value_style: dict | None = None,
) -> html.Div:
    """KPI 타일 1개.

    Args:
        label: 라벨 문자열
        value_id: value slot Dash id (callback 타깃)
        delta_id: delta slot Dash id (None 이면 delta 슬롯 생략)
        value: 초기 value
        delta: 초기 delta
        delta_kind: 상승/하락/중립 — CSS 클래스 결정
        term: GLOSSARY 키 — 존재하면 label이 TermTip으로 자동 래핑
        value_style: value 슬롯 인라인 스타일 override
    """
    label_node: str | Component = (
        TermTip(term) if term and term in GLOSSARY else label
    )
    children: list = [
        html.Div(label_node, className="l"),
        html.Div(id=value_id, className="v", children=value, style=value_style),
    ]
    if delta_id is not None:
        children.append(
            html.Div(id=delta_id, className=f"d {delta_kind}", children=delta)
        )
    return html.Div(className="kpi-tile", children=children)

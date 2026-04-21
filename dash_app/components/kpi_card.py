"""단일 KPI 타일. 재사용 가능한 순수 함수.

구조 (위에서 아래):
    1) label       — 타이틀 (진한 색상, 굵게)
    2) period      — 기준 시기/범위 (회색, 작게) · 선택
    3) value       — 핵심 수치 (가장 크게)
    4) detail      — 보조 정보/분해 (회색, 작게) · 선택

이전의 `delta_id/delta` 는 상승/하락 방향 표기가 혼란을 유발한다는 피드백에 따라
`detail_id/detail` 로 일반화. 색 방향성은 제거.
"""

from __future__ import annotations

from typing import Any, Literal

from dash import html
from dash.development.base_component import Component

from dash_app.components.term_tip import TermTip
from dash_app.glossary.terms import GLOSSARY

TileKind = Literal["default", "leading"]
TileColor = Literal["blue", "purple", "green", "orange"]


def KpiCard(
    label: str,
    value_id: str,
    *,
    period_id: str | None = None,
    detail_id: str | None = None,
    value: Any = "—",
    period: Any = " ",
    detail: Any = " ",
    term: str | None = None,
    value_style: dict | None = None,
    tile_id: str | dict | None = None,
    kind: TileKind = "default",
    clickable: bool = False,
    selected: bool = False,
    color: TileColor = "blue",
) -> html.Div:
    """KPI 타일 1개.

    Args:
        label: 타이틀 문자열
        value_id: value slot Dash id (callback 타깃)
        period_id: 기준 시기 subtitle 용 id. 없으면 슬롯 생략.
        detail_id: 보조 정보 slot 용 id (이전 delta_id 역할). 없으면 슬롯 생략.
        value: 초기 value
        period: 초기 period 텍스트
        detail: 초기 detail 텍스트
        term: GLOSSARY 키 — 존재하면 label 에 hover 툴팁 부착 (텍스트는 label 그대로)
        value_style: value 슬롯 인라인 스타일 override
        tile_id: 타일 div 자체의 id. 콜백에서 className 을 바꾸고 싶을 때 필요.
        kind: `default` 또는 `leading` (선행 지표 강조 스타일)
        clickable: True 면 커서+hover 효과 + role="button"
        selected: True 면 초기 렌더부터 선택된 상태로 강조
        color: 지표 색상 — 선택 상태의 테두리/배경 tint 에 사용 (맵 choropleth 와 동기)
    """
    # term 이 지정돼도 label 텍스트는 보존 — hover 시에만 정의가 뜨도록.
    label_node: str | Component = (
        TermTip(term, display=label) if term and term in GLOSSARY else label
    )

    children: list = [html.Div(label_node, className="l")]
    if period_id is not None:
        children.append(
            html.Div(
                id=period_id,
                className="p",
                children=period,
            )
        )
    children.append(
        html.Div(id=value_id, className="v", children=value, style=value_style),
    )
    if detail_id is not None:
        children.append(
            html.Div(id=detail_id, className="dt", children=detail)
        )

    classes = ["kpi-tile", f"kpi-tile--color-{color}"]
    if kind == "leading":
        classes.append("kpi-tile--leading")
    if clickable:
        classes.append("kpi-tile--clickable")
    if selected:
        classes.append("kpi-tile--selected")

    extra: dict = {}
    if tile_id is not None:
        extra["id"] = tile_id
    if clickable:
        extra["n_clicks"] = 0
        extra["role"] = "button"
    return html.Div(className=" ".join(classes), children=children, **extra)

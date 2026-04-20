"""GLOSSARY에 등록된 용어 키를 받아 툴팁이 부착된 인라인 노드를 반환."""

from __future__ import annotations

import dash_mantine_components as dmc
from dash import html
from dash.development.base_component import Component

from dash_app.glossary.terms import GLOSSARY


def TermTip(term_key: str, display: str | None = None) -> Component:
    """용어에 hover 툴팁을 부착한 인라인 컴포넌트.

    Raises:
        KeyError: term_key가 GLOSSARY에 없을 때 (타이포 조기 발견)
    """
    term = GLOSSARY[term_key]
    return dmc.Tooltip(
        label=term["short"],
        multiline=True,
        w=280,
        withArrow=True,
        position="top",
        children=html.Span(
            display or term["label"],
            className="term-tip-target",
        ),
    )

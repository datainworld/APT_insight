"""GLOSSARY 에 등록된 용어 키를 받아 툴팁이 부착된 인라인 노드를 반환.

dmc.Tooltip 을 쓰지 않음 — MantineProvider 설정 없이도 동작하도록 native `title`
속성을 이용한다. 툴팁 UI 는 브라우저 기본 hover 툴팁으로 나타난다.
"""

from __future__ import annotations

from dash import html
from dash.development.base_component import Component

from dash_app.glossary.terms import GLOSSARY


def TermTip(term_key: str, display: str | None = None) -> Component:
    """용어에 hover 툴팁을 부착한 인라인 컴포넌트.

    Raises:
        KeyError: term_key 가 GLOSSARY 에 없을 때 (타이포 조기 발견)
    """
    term = GLOSSARY[term_key]
    return html.Span(
        display or term["label"],
        title=term["short"],
        className="term-tip-target",
    )

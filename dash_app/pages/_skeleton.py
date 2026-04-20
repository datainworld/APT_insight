"""신규 페이지의 공통 스켈레톤 레이아웃. Phase C 에서 실제 내용으로 대체."""

from __future__ import annotations

from dash import html


def skeleton(title: str, description: str, phase: str = "Phase C") -> html.Main:
    return html.Main(
        className="fd-main",
        children=[
            html.Section(
                className="page-skeleton",
                children=[
                    html.H1(title),
                    html.P(description),
                    html.Div(
                        className="stub",
                        children=f"{phase} 에서 구현 예정입니다.",
                    ),
                ],
            )
        ],
    )

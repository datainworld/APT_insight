"""페이지 상단 상태 배너 — 뉴스 요약 카운트 등."""

from __future__ import annotations

from typing import Literal, TypedDict

from dash import html

BannerKind = Literal["info", "warning", "success", "error"]


class BannerItem(TypedDict):
    label: str
    value: int | str


def StatusBanner(items: list[BannerItem], kind: BannerKind = "info") -> html.Div:
    """
    items 예: [{"label": "지역 뉴스", "value": 14}, {"label": "전국/정책", "value": 5}]
    """
    return html.Div(
        className=f"status-banner status-banner--{kind}",
        children=[
            html.Div(
                className="status-banner-item",
                children=[
                    html.Span(it["label"], className="label"),
                    html.B(str(it["value"]), className="value"),
                ],
            )
            for it in items
        ],
    )

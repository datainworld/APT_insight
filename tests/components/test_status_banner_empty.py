"""EmptyState + StatusBanner 렌더 스모크 테스트."""

from __future__ import annotations

from dash_app.components.empty_state import EmptyState
from dash_app.components.status_banner import StatusBanner


def test_empty_state_basic() -> None:
    node = EmptyState("데이터 없음")
    assert node.className == "empty-state"
    # 아이콘 + 제목만 (description 없음)
    assert len(node.children) == 2


def test_empty_state_with_description_and_action() -> None:
    from dash import html

    node = EmptyState(
        "없음",
        description="조건을 변경해 주세요",
        action=html.Button("초기화", id="reset"),
    )
    assert len(node.children) == 4


def test_status_banner_renders_items() -> None:
    node = StatusBanner(
        items=[
            {"label": "지역 뉴스", "value": 14},
            {"label": "전국/정책", "value": 5},
        ],
        kind="info",
    )
    assert "status-banner--info" in node.className
    assert len(node.children) == 2


def test_status_banner_warning_kind() -> None:
    node = StatusBanner(items=[{"label": "지역", "value": 0}], kind="warning")
    assert "status-banner--warning" in node.className

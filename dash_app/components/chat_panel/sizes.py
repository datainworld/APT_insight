"""플로팅 채팅 패널 4단계 크기 상수 + 상태 전환 규칙."""

from __future__ import annotations

from typing import Literal

SizeMode = Literal["minimized", "compact", "expanded", "maximized"]

SIZE_MODES: tuple[SizeMode, ...] = ("minimized", "compact", "expanded", "maximized")

# minimized=축소 아이콘(56x56), compact=기본 열림, expanded=우측 전체 높이, maximized=전체 오버레이
_ORDER = {mode: i for i, mode in enumerate(SIZE_MODES)}


def next_mode_up(current: SizeMode) -> SizeMode:
    """한 단계 크게 — maximized 에서는 그대로."""
    idx = _ORDER.get(current, 1)
    if idx >= len(SIZE_MODES) - 1:
        return current
    return SIZE_MODES[idx + 1]


def next_mode_down(current: SizeMode) -> SizeMode:
    """한 단계 작게 — minimized 에서는 그대로 (ESC 도 여기 호출)."""
    idx = _ORDER.get(current, 1)
    if idx <= 0:
        return current
    return SIZE_MODES[idx - 1]


def is_expandable(mode: SizeMode) -> bool:
    """maximized 이외에서 [⇲] 버튼이 활성."""
    return mode != "maximized"


def is_shrinkable(mode: SizeMode) -> bool:
    """maximized 일 때 [⇱] (shrink) 로 표시."""
    return mode == "maximized"

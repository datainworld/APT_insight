"""dash_app 전용 상수 (필터 옵션, 채팅 크기 등)."""

from __future__ import annotations

from typing import TypedDict


class PageDef(TypedDict):
    path: str
    name: str
    icon: str
    order: int


SIDO_OPTIONS = [
    {"label": "서울특별시", "value": "서울특별시"},
    {"label": "인천광역시", "value": "인천광역시"},
    {"label": "경기도", "value": "경기도"},
]

AREA_OPTIONS = [
    {"label": a, "value": a}
    for a in ["전체", "~60㎡", "60-85㎡", "85-102㎡", "102㎡~"]
]

DEAL_OPTIONS: list[tuple[str, str]] = [("sale", "매매"), ("lease", "전세"), ("rent", "월세")]
DEAL_LABELS: dict[str, str] = {k: v for k, v in DEAL_OPTIONS}

CHIP_PROMPTS = [
    "강남구 최근 거래 추이",
    "호가 괴리가 큰 단지",
    "갭투자 유망 단지 추천",
]

DEFAULT_SIDO = "서울특별시"
DEFAULT_PERIOD_MONTHS = 36

PAGES: list[PageDef] = [
    {"path": "/", "name": "시장 개요", "icon": "house", "order": 1},
    {"path": "/complex", "name": "단지 상세", "icon": "building", "order": 2},
    {"path": "/gap", "name": "실거래가 vs 호가", "icon": "arrows-left-right", "order": 3},
    {"path": "/invest", "name": "투자 지표", "icon": "chart-line", "order": 4},
    {"path": "/about", "name": "소개", "icon": "circle-info", "order": 5},
]

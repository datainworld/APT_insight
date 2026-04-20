"""format_won / format_percent / format_count 단위 테스트."""

from __future__ import annotations

import math

import pytest

from dash_app.components.formatters import (
    format_count,
    format_percent,
    format_ppm2,
    format_won,
)


class TestFormatWon:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, "—"),
            (float("nan"), "—"),
            (0, "0"),
            (500, "500"),
            (9_999, "9,999"),
            (10_000, "1억"),
            (10_500, "1억 500"),
            (105_000, "10억 5,000"),
            (100_000_000, "10000억"),
        ],
    )
    def test_compact(self, value: float | None, expected: str) -> None:
        assert format_won(value) == expected

    def test_non_compact(self) -> None:
        assert format_won(105_000, compact=False) == "105,000"


class TestFormatPercent:
    def test_ratio_input(self) -> None:
        assert format_percent(0.531) == "53.1%"
        assert format_percent(1.0) == "100.0%"

    def test_already_percent(self) -> None:
        assert format_percent(53.1, as_ratio=False) == "53.1%"

    def test_none(self) -> None:
        assert format_percent(None) == "—"

    def test_nan(self) -> None:
        assert format_percent(math.nan) == "—"


class TestFormatCount:
    def test_basic(self) -> None:
        assert format_count(12_345) == "12,345"
        assert format_count(0) == "0"
        assert format_count(None) == "—"


class TestFormatPpm2:
    def test_manwon(self) -> None:
        assert format_ppm2(3_936) == "3,936만원/㎡"

    def test_eok(self) -> None:
        assert format_ppm2(12_000) == "1.20억/㎡"

    def test_none(self) -> None:
        assert format_ppm2(None) == "—"

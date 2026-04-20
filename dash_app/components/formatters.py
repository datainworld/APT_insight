"""숫자·가격 포매터. 순수 함수, DB 의존 없음."""

from __future__ import annotations

import math
from typing import Any

_DASH = "—"


def _is_nullish(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    return False


def format_won(value_manwon: Any, *, compact: bool = True) -> str:
    """만원 단위 정수를 한국식 억/만원 포맷으로 변환.

    Args:
        value_manwon: 만원 단위 금액 (int / float / None / NaN 허용)
        compact: True 면 `10억 5,000`, False 면 `105,000`

    >>> format_won(10_000)
    '1억'
    >>> format_won(105_000)
    '10억 5,000'
    >>> format_won(500)
    '500'
    >>> format_won(None)
    '—'
    """
    if _is_nullish(value_manwon):
        return _DASH
    v = int(round(float(value_manwon)))
    if v == 0:
        return "0"
    if not compact:
        return f"{v:,}"
    eok = v // 10_000
    remainder = v % 10_000
    if eok == 0:
        return f"{v:,}"
    if remainder == 0:
        return f"{eok}억"
    return f"{eok}억 {remainder:,}"


def format_count(value: Any) -> str:
    """건수 (천 단위 콤마)."""
    if _is_nullish(value):
        return _DASH
    return f"{int(value):,}"


def format_percent(value: Any, *, digits: int = 1, as_ratio: bool = True) -> str:
    """비율을 퍼센트로 표시. as_ratio=True 면 0.531 → 53.1%, False 면 53.1 → 53.1%."""
    if _is_nullish(value):
        return _DASH
    pct = float(value) * 100 if as_ratio else float(value)
    return f"{pct:.{digits}f}%"


def format_ppm2(value_manwon_per_m2: Any) -> str:
    """평당가(만원/㎡) → `XX.X만원/㎡` 또는 `X.XX억/㎡`."""
    if _is_nullish(value_manwon_per_m2):
        return _DASH
    v = float(value_manwon_per_m2)
    if v >= 10_000:
        return f"{v / 10_000:.2f}억/㎡"
    return f"{v:,.0f}만원/㎡"

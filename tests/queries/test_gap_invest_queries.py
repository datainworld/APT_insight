"""gap_queries / invest_queries import + signature smoke."""

from __future__ import annotations

import inspect


def test_gap_queries_exports() -> None:
    from dash_app.queries import gap_queries as q

    assert callable(q.gap_ratio_by_sgg)
    assert callable(q.gap_ratio_by_complex)


def test_invest_queries_exports() -> None:
    from dash_app.queries import invest_queries as q

    assert callable(q.invest_by_sgg)
    assert callable(q.invest_by_complex)


def test_gap_complex_has_limit_param() -> None:
    from dash_app.queries.gap_queries import gap_ratio_by_complex

    sig = inspect.signature(gap_ratio_by_complex)
    assert "limit" in sig.parameters


def test_build_filter_defaults() -> None:
    from dash_app.queries.rt_queries import build_filter

    f = build_filter(None, None, None, None, None, None)
    assert f.sido == "서울특별시"
    assert f.sgg == "전체"
    assert f.period_months == 36


def test_build_filter_coerces_period() -> None:
    from dash_app.queries.rt_queries import build_filter

    f = build_filter("서울특별시", "강남구", "전체", "~60㎡", "sale", "24")
    assert f.period_months == 24
    assert f.sgg == "강남구"

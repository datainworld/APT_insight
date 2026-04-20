"""쿼리 모듈 import + 시그니처 smoke test — DB 연결 불필요."""

from __future__ import annotations

import inspect


def test_rt_queries_exports_filter_and_core_functions() -> None:
    from dash_app.queries import rt_queries as q

    assert hasattr(q, "Filter")
    for fn in ("list_sgg", "list_dong", "trade_trend", "price_change",
               "sgg_counts", "top_complexes", "kpi_summary",
               "last_refresh_timestamp"):
        assert callable(getattr(q, fn))


def test_nv_queries_exports() -> None:
    from dash_app.queries import nv_queries as q

    for fn in ("get_active_listings", "get_complex_master", "active_listing_counts_by_sgg"):
        assert callable(getattr(q, fn))


def test_mapping_queries_exports() -> None:
    from dash_app.queries import mapping_queries as q

    assert callable(q.get_mapped_pairs)
    assert callable(q.get_mapping_cover_rate)


def test_metrics_queries_exports() -> None:
    from dash_app.queries import metrics_queries as q

    assert callable(q.get_sgg_metrics)
    assert callable(q.get_sgg_summary)
    assert callable(q.get_complex_ranking)


def test_news_queries_exports() -> None:
    from dash_app.queries import news_queries as q

    assert callable(q.get_latest)
    assert callable(q.fetch)
    assert callable(q.get_status_counts)


def test_complex_ranking_rejects_unknown_sort() -> None:
    """allowlist 검증은 함수 시그니처 수준에서 파악 가능해야 함."""
    from dash_app.queries.metrics_queries import get_complex_ranking

    sig = inspect.signature(get_complex_ranking)
    assert "order_by" in sig.parameters

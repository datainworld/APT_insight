"""집계 Materialized View (mv_metrics_*) 쿼리 — Phase C 대시보드 가속용."""

from __future__ import annotations

import pandas as pd
from cachetools import TTLCache, cached  # type: ignore[import-untyped]
from sqlalchemy import text

from dash_app.db import get_engine

_SGG_CACHE: TTLCache = TTLCache(maxsize=256, ttl=300)
_COMPLEX_CACHE: TTLCache = TTLCache(maxsize=64, ttl=300)


def _sgg_cache_key(sido: str | None) -> str:
    return sido or "_"


@cached(_SGG_CACHE, key=_sgg_cache_key)
def get_sgg_metrics(sido: str | None = None) -> pd.DataFrame:
    """시군구별 집계 (mv_metrics_by_sgg). sido 미지정 시 전체."""
    where = ["1=1"]
    params: dict = {}
    if sido and sido != "전체":
        where.append("sido = :sido")
        params["sido"] = sido
    sql = text(f"""
        SELECT sido, sgg,
               trade_count_6m, trade_count_12m, trade_count_36m,
               avg_price_6m, median_ppm2_6m, median_ppm2_36m,
               sale_median_6m, jeonse_median_6m,
               CASE WHEN sale_median_6m > 0
                    THEN jeonse_median_6m / sale_median_6m
                    ELSE NULL END AS jeonse_ratio_6m
        FROM mv_metrics_by_sgg
        WHERE {' AND '.join(where)}
        ORDER BY trade_count_6m DESC NULLS LAST
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(sql, conn, params=params)


def get_sgg_summary(sido: str, sgg: str) -> dict | None:
    """단일 시군구의 핵심 KPI dict."""
    sql = text("""
        SELECT sido, sgg,
               trade_count_6m, trade_count_12m, trade_count_36m,
               avg_price_6m, median_ppm2_6m, median_ppm2_36m,
               sale_median_6m, jeonse_median_6m,
               CASE WHEN sale_median_6m > 0
                    THEN jeonse_median_6m / sale_median_6m
                    ELSE NULL END AS jeonse_ratio_6m
        FROM mv_metrics_by_sgg
        WHERE sido = :sido AND sgg = :sgg
    """)
    with get_engine().connect() as conn:
        row = conn.execute(sql, {"sido": sido, "sgg": sgg}).mappings().fetchone()
    return dict(row) if row else None


def get_complex_ranking(
    sido: str | None = None,
    sgg: str | None = None,
    order_by: str = "trade_count_6m",
    limit: int = 200,
) -> pd.DataFrame:
    """단지별 랭킹 (mv_metrics_by_complex). Phase C 지역/단지 페이지 테이블용."""
    allowed_sorts = {
        "trade_count_3m", "trade_count_6m", "trade_count_12m", "trade_count_36m",
        "avg_price_6m", "median_ppm2_6m", "last_deal_date",
    }
    if order_by not in allowed_sorts:
        order_by = "trade_count_6m"

    where = ["1=1"]
    params: dict = {"lim": int(limit)}
    if sido and sido != "전체":
        where.append("sido = :sido")
        params["sido"] = sido
    if sgg and sgg != "전체":
        where.append("sgg = :sgg")
        params["sgg"] = sgg

    sql = text(f"""
        SELECT apt_id, apt_name, sido, sgg, admin_dong, build_year,
               latitude, longitude,
               trade_count_3m, trade_count_6m, trade_count_12m, trade_count_36m,
               avg_price_6m, median_ppm2_6m, last_deal_date
        FROM mv_metrics_by_complex
        WHERE {' AND '.join(where)}
        ORDER BY {order_by} DESC NULLS LAST
        LIMIT :lim
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(sql, conn, params=params)

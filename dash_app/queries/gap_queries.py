"""호가 괴리 (gap) 관련 쿼리 — /gap 페이지용.

괴리율 = (호가 평균 - 실거래 중위값) / 실거래 중위값

base 조회는 `complex_mapping` 에 연결된 단지만 대상으로 하며, 매핑이 없으면
해당 단지는 집계에서 제외된다. (스펙 3.4 cover_rate 배지가 이 한계를 사용자에게 노출)
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import text

from dash_app.db import get_engine

_LOOKBACK_MONTHS = 6


def _gap_cte_sql(*, include_complex_cols: bool) -> str:
    """매핑된 단지별 (실거래 중위, 호가 평균, 거래량, 매물수) CTE SQL.

    include_complex_cols=True 면 apt_id + apt_name + lat/lon 컬럼을 투영.
    False 면 sido/sgg 만 투영하여 상위 집계에 위임.
    """
    projection = (
        "c.apt_id, c.apt_name, c.latitude, c.longitude, c.build_year,"
        if include_complex_cols
        else ""
    )
    return f"""
        SELECT
            {projection}
            c.sido_name AS sido,
            c.sgg_name  AS sgg,
            trade_stats.median_deal,
            trade_stats.trade_count,
            ask_stats.avg_ask,
            ask_stats.active_count,
            ask_stats.avg_days_listed
        FROM rt_complex c
        JOIN complex_mapping m ON c.apt_id = m.apt_id
        JOIN (
            SELECT apt_id,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY deal_amount) AS median_deal,
                   COUNT(*) AS trade_count
            FROM rt_trade
            WHERE deal_date >= CURRENT_DATE - INTERVAL '{_LOOKBACK_MONTHS} months'
            GROUP BY apt_id
        ) trade_stats ON c.apt_id = trade_stats.apt_id
        JOIN (
            SELECT complex_no,
                   AVG(current_price) AS avg_ask,
                   COUNT(*)            AS active_count,
                   AVG((CURRENT_DATE - first_seen_date)::int) AS avg_days_listed
            FROM nv_listing
            WHERE is_active = TRUE AND trade_type = 'A1' AND current_price IS NOT NULL
            GROUP BY complex_no
        ) ask_stats ON m.naver_complex_no = ask_stats.complex_no
        WHERE c.sgg_name IS NOT NULL AND trade_stats.median_deal > 0
    """


def gap_ratio_by_sgg(sido: str | None = None) -> pd.DataFrame:
    """시군구별 평균 호가 괴리율 + 의심 단지 수 + 평균 노출기간."""
    inner = _gap_cte_sql(include_complex_cols=False)
    where = ""
    params: dict = {}
    if sido and sido != "전체":
        where = "WHERE sido = :sido"
        params["sido"] = sido
    sql = text(f"""
        WITH per_complex AS (
            {inner}
        )
        SELECT sido, sgg,
               COUNT(*) AS mapped_count,
               AVG((avg_ask - median_deal) / NULLIF(median_deal, 0)) AS avg_gap_ratio,
               COUNT(*) FILTER (
                   WHERE (avg_ask - median_deal) / NULLIF(median_deal, 0) > 0.10
               ) AS suspect_count,
               AVG(avg_days_listed) AS avg_days_listed
        FROM per_complex
        {where}
        GROUP BY sido, sgg
        ORDER BY avg_gap_ratio DESC NULLS LAST
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(sql, conn, params=params)


def gap_ratio_by_complex(
    sido: str | None = None,
    sgg: str | None = None,
    limit: int = 500,
) -> pd.DataFrame:
    """단지별 호가 괴리 상세 — TOP N / scatter / KPI 집계에 공통 사용."""
    inner = _gap_cte_sql(include_complex_cols=True)
    wheres = []
    params: dict = {"lim": int(limit)}
    if sido and sido != "전체":
        wheres.append("sido = :sido")
        params["sido"] = sido
    if sgg and sgg != "전체":
        wheres.append("sgg = :sgg")
        params["sgg"] = sgg
    where_clause = ("WHERE " + " AND ".join(wheres)) if wheres else ""

    sql = text(f"""
        WITH per_complex AS (
            {inner}
        )
        SELECT apt_id, apt_name, sido, sgg, latitude, longitude, build_year,
               median_deal, avg_ask, trade_count, active_count, avg_days_listed,
               (avg_ask - median_deal) / NULLIF(median_deal, 0) AS gap_ratio
        FROM per_complex
        {where_clause}
        ORDER BY gap_ratio DESC NULLS LAST
        LIMIT :lim
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(sql, conn, params=params)

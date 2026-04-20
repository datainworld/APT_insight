"""투자 지표 (갭투자 / 전세가율 / 전월세전환율) 쿼리 — /invest 페이지용.

핵심 계산:
    갭         = 매매 중위 - 전세 중위
    전세가율   = 전세 중위 / 매매 중위
    전월세전환율 = (월세 × 12) / max(0, 전세_보증금 - 월세_보증금)

데이터 윈도우는 6개월. 매핑되지 않은 단지도 포함 (활성 매물 없이 실거래만으로 계산 가능).
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import text

from dash_app.db import get_engine

_LOOKBACK_MONTHS = 6


def _invest_cte_sql(*, include_complex_cols: bool) -> str:
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
            sale_stats.median_sale,
            sale_stats.sale_count,
            jeonse_stats.median_jeonse,
            jeonse_stats.jeonse_count,
            conv_stats.monthly_median,
            conv_stats.rent_deposit_median
        FROM rt_complex c
        LEFT JOIN (
            SELECT apt_id,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY deal_amount) AS median_sale,
                   COUNT(*) AS sale_count
            FROM rt_trade
            WHERE deal_date >= CURRENT_DATE - INTERVAL '{_LOOKBACK_MONTHS} months'
            GROUP BY apt_id
        ) sale_stats ON c.apt_id = sale_stats.apt_id
        LEFT JOIN (
            SELECT apt_id,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY deposit) AS median_jeonse,
                   COUNT(*) AS jeonse_count
            FROM rt_rent
            WHERE deal_date >= CURRENT_DATE - INTERVAL '{_LOOKBACK_MONTHS} months'
              AND monthly_rent = 0
            GROUP BY apt_id
        ) jeonse_stats ON c.apt_id = jeonse_stats.apt_id
        LEFT JOIN (
            SELECT apt_id,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY monthly_rent) AS monthly_median,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY deposit) AS rent_deposit_median
            FROM rt_rent
            WHERE deal_date >= CURRENT_DATE - INTERVAL '{_LOOKBACK_MONTHS} months'
              AND monthly_rent > 0
            GROUP BY apt_id
        ) conv_stats ON c.apt_id = conv_stats.apt_id
        WHERE c.sgg_name IS NOT NULL
          AND sale_stats.median_sale > 0
          AND jeonse_stats.median_jeonse > 0
    """


def invest_by_sgg(sido: str | None = None) -> pd.DataFrame:
    """시군구별 집계 KPI (/invest 상단 KPI + choropleth)."""
    inner = _invest_cte_sql(include_complex_cols=False)
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
               COUNT(*) AS complex_count,
               AVG(median_jeonse / NULLIF(median_sale, 0)) AS jeonse_ratio,
               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY median_sale - median_jeonse) AS median_gap,
               AVG(
                   CASE WHEN monthly_median IS NOT NULL AND median_jeonse > rent_deposit_median
                        THEN (monthly_median * 12.0) / (median_jeonse - rent_deposit_median)
                        ELSE NULL END
               ) AS conversion_rate
        FROM per_complex
        {where}
        GROUP BY sido, sgg
        ORDER BY jeonse_ratio DESC NULLS LAST
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(sql, conn, params=params)


def invest_by_complex(
    sido: str | None = None,
    sgg: str | None = None,
    limit: int = 500,
) -> pd.DataFrame:
    """단지별 갭투자 지표 — 갭 히스토그램 + 랭킹 테이블 소스.

    score(매력도) = 전세가율 × 40 + min(sale_count, 30)/30 × 30 +
                   (1 - normalized_std) × 30
    std 역수는 본 쿼리 범위 밖이므로 0 으로 대체 (단순화). Phase 후속에서 개선.
    """
    inner = _invest_cte_sql(include_complex_cols=True)
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
               median_sale, median_jeonse, sale_count, jeonse_count,
               monthly_median, rent_deposit_median,
               median_sale - median_jeonse AS gap,
               median_jeonse / NULLIF(median_sale, 0) AS jeonse_ratio,
               LEAST(sale_count, 30) / 30.0 AS volume_score,
               (median_jeonse / NULLIF(median_sale, 0)) * 40.0 +
               LEAST(sale_count, 30) / 30.0 * 30.0 AS attractiveness_score
        FROM per_complex
        {where_clause}
        ORDER BY attractiveness_score DESC NULLS LAST
        LIMIT :lim
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(sql, conn, params=params)

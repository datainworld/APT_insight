"""투자 지표 (갭투자 / 전세가율 / 전월세전환율) 쿼리 — /invest 페이지용.

**설계 원칙 — 평당가 기준 비교**
단지 내 다면적 혼재로 인해 단순 평균은 왜곡된다. 따라서 모든 집계는
`price / exclusive_area` (평당가) 기반 중위를 먼저 구하고, 그 분포로 지표를 계산한다.

핵심 계산:
    median_sale_ppm2    = median(매매 deal_amount / exclusive_area), 6개월
    median_jeonse_ppm2  = median(전세 deposit     / exclusive_area), 6개월
    갭_ppm2            = median_sale_ppm2 - median_jeonse_ppm2     (만원/㎡)
    전세가율            = median_jeonse_ppm2 / median_sale_ppm2    (dimensionless)
    전월세전환율        = 월세 × 12 / max(0, 전세보증금 - 월세보증금)

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
            sale_stats.median_sale_ppm2,
            sale_stats.sale_count,
            jeonse_stats.median_jeonse_ppm2,
            jeonse_stats.jeonse_count,
            conv_stats.monthly_median_ppm2,
            conv_stats.rent_deposit_median_ppm2
        FROM rt_complex c
        LEFT JOIN (
            SELECT apt_id,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (
                       ORDER BY deal_amount / NULLIF(exclusive_area, 0)
                   ) AS median_sale_ppm2,
                   COUNT(*) AS sale_count
            FROM rt_trade
            WHERE deal_date >= CURRENT_DATE - INTERVAL '{_LOOKBACK_MONTHS} months'
              AND exclusive_area > 0
            GROUP BY apt_id
        ) sale_stats ON c.apt_id = sale_stats.apt_id
        LEFT JOIN (
            SELECT apt_id,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (
                       ORDER BY deposit / NULLIF(exclusive_area, 0)
                   ) AS median_jeonse_ppm2,
                   COUNT(*) AS jeonse_count
            FROM rt_rent
            WHERE deal_date >= CURRENT_DATE - INTERVAL '{_LOOKBACK_MONTHS} months'
              AND monthly_rent = 0
              AND exclusive_area > 0
            GROUP BY apt_id
        ) jeonse_stats ON c.apt_id = jeonse_stats.apt_id
        LEFT JOIN (
            SELECT apt_id,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (
                       ORDER BY monthly_rent / NULLIF(exclusive_area, 0)
                   ) AS monthly_median_ppm2,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (
                       ORDER BY deposit / NULLIF(exclusive_area, 0)
                   ) AS rent_deposit_median_ppm2
            FROM rt_rent
            WHERE deal_date >= CURRENT_DATE - INTERVAL '{_LOOKBACK_MONTHS} months'
              AND monthly_rent > 0
              AND exclusive_area > 0
            GROUP BY apt_id
        ) conv_stats ON c.apt_id = conv_stats.apt_id
        WHERE c.sgg_name IS NOT NULL
          AND sale_stats.median_sale_ppm2 > 0
          AND jeonse_stats.median_jeonse_ppm2 > 0
    """


def invest_by_sgg(sido: str | None = None) -> pd.DataFrame:
    """시군구별 집계 KPI (/invest 상단 KPI + choropleth). 전부 평당 기준."""
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
               AVG(median_jeonse_ppm2 / NULLIF(median_sale_ppm2, 0)) AS jeonse_ratio,
               PERCENTILE_CONT(0.5) WITHIN GROUP (
                   ORDER BY median_sale_ppm2 - median_jeonse_ppm2
               ) AS median_gap_ppm2,
               AVG(
                   CASE WHEN monthly_median_ppm2 IS NOT NULL
                             AND median_jeonse_ppm2 > rent_deposit_median_ppm2
                        THEN (monthly_median_ppm2 * 12.0)
                             / (median_jeonse_ppm2 - rent_deposit_median_ppm2)
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
    """단지별 갭투자 지표 — 갭 히스토그램 + 랭킹 테이블 소스. 전부 평당 기준.

    score(매력도) = 전세가율 × 40 + min(sale_count, 30)/30 × 30
    (호가 표준편차 항은 Phase 후속에서 추가, 현재 공식은 70점 만점 단순화)
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
               median_sale_ppm2, median_jeonse_ppm2, sale_count, jeonse_count,
               monthly_median_ppm2, rent_deposit_median_ppm2,
               median_sale_ppm2 - median_jeonse_ppm2 AS gap_ppm2,
               median_jeonse_ppm2 / NULLIF(median_sale_ppm2, 0) AS jeonse_ratio,
               LEAST(sale_count, 30) / 30.0 AS volume_score,
               (median_jeonse_ppm2 / NULLIF(median_sale_ppm2, 0)) * 40.0 +
               LEAST(sale_count, 30) / 30.0 * 30.0 AS attractiveness_score
        FROM per_complex
        {where_clause}
        ORDER BY attractiveness_score DESC NULLS LAST
        LIMIT :lim
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(sql, conn, params=params)


def jeonse_ratio_monthly(sido: str | None = None, sgg: str | None = None) -> pd.DataFrame:
    """월별 매매 단위면적 중위 + 전세 보증금 단위면적 중위 → 전세가율 (36개월).

    반환 컬럼: ym, median_sale_ppm2, median_jeonse_ppm2, jeonse_ratio,
             sale_count, jeonse_count
    """
    sale_filter = ["t.deal_date >= CURRENT_DATE - INTERVAL '36 months'",
                   "t.exclusive_area > 0"]
    jeonse_filter = ["r.deal_date >= CURRENT_DATE - INTERVAL '36 months'",
                     "r.monthly_rent = 0",
                     "r.exclusive_area > 0"]
    common = ["c.sgg_name IS NOT NULL"]
    params: dict = {}
    if sido and sido != "전체":
        common.append("c.sido_name = :sido")
        params["sido"] = sido
    if sgg and sgg != "전체":
        common.append("c.sgg_name = :sgg")
        params["sgg"] = sgg

    sale_where = " AND ".join(sale_filter + common)
    jeonse_where = " AND ".join(jeonse_filter + common)

    sql = text(f"""
        WITH monthly_sale AS (
            SELECT DATE_TRUNC('month', t.deal_date)::date AS ym,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (
                       ORDER BY t.deal_amount / NULLIF(t.exclusive_area, 0)
                   ) AS median_sale_ppm2,
                   COUNT(*) AS sale_count
            FROM rt_trade t
            JOIN rt_complex c ON c.apt_id = t.apt_id
            WHERE {sale_where}
            GROUP BY ym
        ),
        monthly_jeonse AS (
            SELECT DATE_TRUNC('month', r.deal_date)::date AS ym,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (
                       ORDER BY r.deposit / NULLIF(r.exclusive_area, 0)
                   ) AS median_jeonse_ppm2,
                   COUNT(*) AS jeonse_count
            FROM rt_rent r
            JOIN rt_complex c ON c.apt_id = r.apt_id
            WHERE {jeonse_where}
            GROUP BY ym
        )
        SELECT COALESCE(s.ym, j.ym) AS ym,
               s.median_sale_ppm2,
               j.median_jeonse_ppm2,
               j.median_jeonse_ppm2 / NULLIF(s.median_sale_ppm2, 0) AS jeonse_ratio,
               COALESCE(s.sale_count, 0)   AS sale_count,
               COALESCE(j.jeonse_count, 0) AS jeonse_count
        FROM monthly_sale s
        FULL OUTER JOIN monthly_jeonse j ON j.ym = s.ym
        ORDER BY ym
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(sql, conn, params=params)

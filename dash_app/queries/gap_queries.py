"""호가 괴리 (gap) 관련 쿼리 — /gap 페이지용.

**설계 원칙 — 평당가 기준 비교**
아파트는 단지 내 다양한 면적대(전용면적)이 혼재하며, 거래가/호가는 면적에 종속된다.
따라서 단지의 "평균 매매가" 나 "호가 평균" 을 면적 고려 없이 비교하면 왜곡된다.
이 모듈의 모든 집계는 `price / exclusive_area` 를 먼저 계산한 뒤(평당가), 그 분포의
중위/평균을 취한다.

괴리율 = (호가 평당 평균 - 실거래 평당 중위) / 실거래 평당 중위

base 조회는 `complex_mapping` 에 연결된 단지만 대상으로 하며, 매핑이 없으면
해당 단지는 집계에서 제외된다. (스펙 3.4 cover_rate 배지가 이 한계를 사용자에게 노출)
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import text

from dash_app.db import get_engine

_LOOKBACK_MONTHS = 6


def _gap_cte_sql(*, include_complex_cols: bool) -> str:
    """매핑된 단지별 (실거래 평당 중위, 호가 평당 평균, 거래량, 매물수) CTE SQL.

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
            trade_stats.median_trade_ppm2,
            trade_stats.trade_count,
            ask_stats.avg_ask_ppm2,
            ask_stats.active_count,
            ask_stats.avg_days_listed
        FROM rt_complex c
        JOIN complex_mapping m ON c.apt_id = m.apt_id
        JOIN (
            SELECT apt_id,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (
                       ORDER BY deal_amount / NULLIF(exclusive_area, 0)
                   ) AS median_trade_ppm2,
                   COUNT(*) AS trade_count
            FROM rt_trade
            WHERE deal_date >= CURRENT_DATE - INTERVAL '{_LOOKBACK_MONTHS} months'
              AND exclusive_area > 0
            GROUP BY apt_id
        ) trade_stats ON c.apt_id = trade_stats.apt_id
        JOIN (
            SELECT complex_no,
                   AVG(current_price / NULLIF(exclusive_area, 0)) AS avg_ask_ppm2,
                   COUNT(*)                                         AS active_count,
                   AVG((CURRENT_DATE - first_seen_date)::int)       AS avg_days_listed
            FROM nv_listing
            WHERE is_active = TRUE
              AND trade_type = 'A1'
              AND current_price IS NOT NULL
              AND exclusive_area > 0
            GROUP BY complex_no
        ) ask_stats ON m.naver_complex_no = ask_stats.complex_no
        WHERE c.sgg_name IS NOT NULL
          AND trade_stats.median_trade_ppm2 > 0
    """


def gap_ratio_by_sgg(sido: str | None = None) -> pd.DataFrame:
    """시군구별 평균 호가 괴리율 + 의심 단지 수 + 평균 노출기간. 전부 평당 기준."""
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
               AVG(
                   (avg_ask_ppm2 - median_trade_ppm2) / NULLIF(median_trade_ppm2, 0)
               ) AS avg_gap_ratio,
               COUNT(*) FILTER (
                   WHERE (avg_ask_ppm2 - median_trade_ppm2)
                         / NULLIF(median_trade_ppm2, 0) > 0.10
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
    ascending: bool = False,
) -> pd.DataFrame:
    """단지별 호가 괴리 상세.

    ascending=False (기본): gap_ratio DESC — 거품 큰 순 (TOP/scatter 공용)
    ascending=True: gap_ratio ASC — 저평가 큰 순 (TOP under 전용)
    """
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
    direction = "ASC" if ascending else "DESC"

    sql = text(f"""
        WITH per_complex AS (
            {inner}
        )
        SELECT apt_id, apt_name, sido, sgg, latitude, longitude, build_year,
               median_trade_ppm2, avg_ask_ppm2, trade_count, active_count, avg_days_listed,
               (avg_ask_ppm2 - median_trade_ppm2)
                   / NULLIF(median_trade_ppm2, 0) AS gap_ratio
        FROM per_complex
        {where_clause}
        ORDER BY gap_ratio {direction} NULLS LAST
        LIMIT :lim
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(sql, conn, params=params)


def gap_ratio_monthly(sido: str | None = None, sgg: str | None = None) -> pd.DataFrame:
    """월별 신규 등록 매물 호가 평균 vs 같은 월 실거래 중위 (단위면적가, 만원/㎡).

    호가는 first_seen_date 기준 월별 평균 initial_price.
    실거래는 deal_date 기준 월별 중위 deal_amount.
    매핑된 단지(complex_mapping)에 한해 집계 — KPI/맵 일관성.

    반환 컬럼: ym, avg_ask_ppm2, median_trade_ppm2, listing_count, trade_count
    """
    listing_filter = ["l.trade_type = 'A1'",
                      "l.first_seen_date >= CURRENT_DATE - INTERVAL '36 months'",
                      "l.initial_price IS NOT NULL",
                      "l.exclusive_area > 0"]
    trade_filter = ["t.deal_date >= CURRENT_DATE - INTERVAL '36 months'",
                    "t.exclusive_area > 0"]
    common_filter = ["c.sgg_name IS NOT NULL"]
    params: dict = {}
    if sido and sido != "전체":
        common_filter.append("c.sido_name = :sido")
        params["sido"] = sido
    if sgg and sgg != "전체":
        common_filter.append("c.sgg_name = :sgg")
        params["sgg"] = sgg

    listing_where = " AND ".join(listing_filter + common_filter)
    trade_where = " AND ".join(trade_filter + common_filter)

    sql = text(f"""
        WITH monthly_listings AS (
            SELECT DATE_TRUNC('month', l.first_seen_date)::date AS ym,
                   AVG(l.initial_price / NULLIF(l.exclusive_area, 0)) AS avg_ask_ppm2,
                   COUNT(*) AS listing_count
            FROM nv_listing l
            JOIN complex_mapping m ON m.naver_complex_no = l.complex_no
            JOIN rt_complex c ON c.apt_id = m.apt_id
            WHERE {listing_where}
            GROUP BY ym
        ),
        monthly_trades AS (
            SELECT DATE_TRUNC('month', t.deal_date)::date AS ym,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (
                       ORDER BY t.deal_amount / NULLIF(t.exclusive_area, 0)
                   ) AS median_trade_ppm2,
                   COUNT(*) AS trade_count
            FROM rt_trade t
            JOIN rt_complex c ON c.apt_id = t.apt_id
            JOIN complex_mapping cm ON cm.apt_id = c.apt_id
            WHERE {trade_where}
            GROUP BY ym
        )
        SELECT COALESCE(l.ym, t.ym) AS ym,
               l.avg_ask_ppm2,
               t.median_trade_ppm2,
               COALESCE(l.listing_count, 0) AS listing_count,
               COALESCE(t.trade_count, 0)   AS trade_count
        FROM monthly_listings l
        FULL OUTER JOIN monthly_trades t ON t.ym = l.ym
        ORDER BY ym
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(sql, conn, params=params)

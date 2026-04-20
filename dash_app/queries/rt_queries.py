"""국토부 실거래가 테이블(rt_*) 집계 쿼리.

rt_complex has its own sido_name / sgg_name / admin_dong columns (coverage
~99.8%), so no mapping join is needed — just JOIN rt_complex and filter
directly. All monetary values are stored in 만원.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache

import pandas as pd
from sqlalchemy import text

from dash_app.db import get_engine

# ---------------------------------------------------------------------------
# Filter
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Filter:
    sido: str = "서울특별시"
    sgg: str = "전체"
    dong: str = "전체"
    area: str = "전체"
    deal: str = "sale"
    period_months: int = 36


def build_filter(
    sido: str | None,
    sgg: str | None,
    dong: str | None,
    area: str | None,
    deal: str | None,
    period: int | float | str | None,
) -> "Filter":
    """Dash State 값(None/빈 문자열/문자열 숫자)을 안전하게 Filter 로 변환."""
    return Filter(
        sido=sido or "서울특별시",
        sgg=sgg or "전체",
        dong=dong or "전체",
        area=area or "전체",
        deal=deal or "sale",
        period_months=int(period or 36),
    )


AREA_RANGES: dict[str, tuple[float | None, float | None]] = {
    "전체": (None, None),
    "~60㎡": (None, 60.0),
    "60-85㎡": (60.0, 85.0),
    "85-102㎡": (85.0, 102.0),
    "102㎡~": (102.0, None),
}


def _area_clause(area: str) -> tuple[str, dict]:
    lo, hi = AREA_RANGES.get(area, (None, None))
    parts, params = [], {}
    if lo is not None:
        parts.append("t.exclusive_area > :area_lo")
        params["area_lo"] = lo
    if hi is not None:
        parts.append("t.exclusive_area <= :area_hi")
        params["area_hi"] = hi
    return (" AND ".join(parts), params) if parts else ("", {})


def _table_for_deal(deal: str) -> tuple[str, str]:
    if deal == "sale":
        return "rt_trade", "t.deal_amount"
    if deal == "lease":
        return "rt_rent", "t.deposit"
    if deal == "rent":
        return "rt_rent", "(t.deposit + t.monthly_rent * 100)"
    raise ValueError(f"unknown deal: {deal}")


def _deal_extra(deal: str) -> str:
    if deal == "lease":
        return "t.monthly_rent = 0"
    if deal == "rent":
        return "t.monthly_rent > 0"
    return ""


def _geo_where(f: Filter) -> tuple[list[str], dict]:
    parts, params = [], {}
    if f.sido and f.sido != "전체":
        parts.append("c.sido_name = :sido")
        params["sido"] = f.sido
    if f.sgg and f.sgg != "전체":
        parts.append("c.sgg_name = :sgg")
        params["sgg"] = f.sgg
    if f.dong and f.dong != "전체":
        parts.append("c.admin_dong = :dong")
        params["dong"] = f.dong
    return parts, params


def _base_joins() -> str:
    """Join rt_trade/rt_rent with rt_complex — sido/sgg live on rt_complex."""
    return "JOIN rt_complex c ON t.apt_id = c.apt_id"


def _build_where(f: Filter) -> tuple[list[str], dict]:
    where = [f"t.deal_date >= CURRENT_DATE - INTERVAL '{int(f.period_months)} months'"]
    params: dict = {}

    geo_parts, geo_params = _geo_where(f)
    where += geo_parts
    params.update(geo_params)

    area_clause, area_params = _area_clause(f.area)
    if area_clause:
        where.append(area_clause)
        params.update(area_params)

    extra = _deal_extra(f.deal)
    if extra:
        where.append(extra)

    return where, params


# ---------------------------------------------------------------------------
# Cascade dropdowns
# ---------------------------------------------------------------------------


@lru_cache(maxsize=16)
def list_sgg(sido: str) -> tuple[str, ...]:
    sql = text("""
        SELECT DISTINCT sgg_name
        FROM rt_complex
        WHERE sido_name = :sido AND sgg_name IS NOT NULL
        ORDER BY sgg_name
    """)
    with get_engine().connect() as conn:
        rows = conn.execute(sql, {"sido": sido}).fetchall()
    return tuple(r[0] for r in rows if r[0])


@lru_cache(maxsize=256)
def list_dong(sido: str, sgg: str) -> tuple[str, ...]:
    sql = text("""
        SELECT DISTINCT admin_dong
        FROM rt_complex
        WHERE sido_name = :sido AND sgg_name = :sgg
          AND admin_dong IS NOT NULL
        ORDER BY admin_dong
    """)
    with get_engine().connect() as conn:
        rows = conn.execute(sql, {"sido": sido, "sgg": sgg}).fetchall()
    return tuple(r[0] for r in rows if r[0])


# ---------------------------------------------------------------------------
# Chart queries
# ---------------------------------------------------------------------------


def trade_trend(f: Filter) -> pd.DataFrame:
    table, _ = _table_for_deal(f.deal)
    where, params = _build_where(f)
    sql = text(f"""
        SELECT t.deal_date AS deal_date, COUNT(*) AS count
        FROM {table} t {_base_joins()}
        WHERE {' AND '.join(where)}
        GROUP BY t.deal_date
        ORDER BY t.deal_date
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(sql, conn, params=params)


def price_change(f: Filter) -> pd.DataFrame:
    table, value_expr = _table_for_deal(f.deal)
    where, params = _build_where(f)
    where.append("t.exclusive_area > 0")
    sql = text(f"""
        SELECT to_char(t.deal_date, 'YYYY-MM') AS ym,
               AVG({value_expr} / t.exclusive_area) AS avg_per_m2,
               PERCENTILE_CONT(0.5) WITHIN GROUP (
                   ORDER BY {value_expr} / t.exclusive_area
               ) AS median_per_m2
        FROM {table} t {_base_joins()}
        WHERE {' AND '.join(where)}
        GROUP BY ym
        ORDER BY ym
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(sql, conn, params=params)


def sgg_counts(f: Filter) -> pd.DataFrame:
    table, _ = _table_for_deal(f.deal)
    where, params = _build_where(f)
    # Keep only sido-scoped sgg aggregation, ignore sgg/dong restriction for the map
    where = [w for w in where if ":sgg" not in w and ":dong" not in w]
    for k in ("sgg", "dong"):
        params.pop(k, None)
    where.append("c.sgg_name IS NOT NULL")

    sql = text(f"""
        SELECT c.sgg_name AS sgg, COUNT(*) AS count
        FROM {table} t {_base_joins()}
        WHERE {' AND '.join(where)}
        GROUP BY c.sgg_name
        ORDER BY count DESC
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(sql, conn, params=params)


def top_complexes(f: Filter, limit: int = 200) -> pd.DataFrame:
    table, _ = _table_for_deal(f.deal)
    where, params = _build_where(f)
    params["lim"] = int(limit)
    sql = text(f"""
        SELECT c.apt_id          AS apt_id,
               c.apt_name        AS apt_name,
               c.sgg_name        AS sgg,
               c.admin_dong      AS admin_dong,
               c.build_year      AS build_year,
               c.latitude        AS latitude,
               c.longitude       AS longitude,
               COUNT(*)          AS count
        FROM {table} t {_base_joins()}
        WHERE {' AND '.join(where)}
        GROUP BY c.apt_id, c.apt_name, c.sgg_name, c.admin_dong,
                 c.build_year, c.latitude, c.longitude
        ORDER BY count DESC
        LIMIT :lim
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(sql, conn, params=params)


def kpi_summary(f: Filter) -> dict:
    """Compute totals inline (don't re-use top_complexes — that's capped)."""
    table, _ = _table_for_deal(f.deal)
    where, params = _build_where(f)
    sql = text(f"""
        SELECT COUNT(*)                         AS total,
               COUNT(DISTINCT c.apt_id)         AS uniq
        FROM {table} t {_base_joins()}
        WHERE {' AND '.join(where)}
    """)
    with get_engine().connect() as conn:
        row = conn.execute(sql, params).fetchone()
    total = int((row[0] if row else 0) or 0)
    uniq = int((row[1] if row else 0) or 0)

    sql_max = text(f"""
        SELECT MAX(cnt) FROM (
            SELECT COUNT(*) AS cnt
            FROM {table} t {_base_joins()}
            WHERE {' AND '.join(where)}
            GROUP BY c.apt_id
        ) x
    """)
    with get_engine().connect() as conn:
        max_v = conn.execute(sql_max, params).scalar() or 0

    avg = int(round(total / uniq)) if uniq else 0
    return {"total": total, "uniq": uniq, "avg": avg, "max": int(max_v)}


def last_refresh_timestamp() -> date | None:
    with get_engine().connect() as conn:
        row = conn.execute(text("SELECT MAX(deal_date) FROM rt_trade")).scalar()
    return row

"""네이버 매물(nv_*) 집계 쿼리."""

from __future__ import annotations

import pandas as pd
from sqlalchemy import text

from dash_app.db import get_engine

_TRADE_TYPE_MAP = {"sale": "A1", "lease": "B1", "rent": "B2"}


def get_active_listings(
    sido: str | None = None,
    sgg: str | None = None,
    deal: str | None = None,
    limit: int = 500,
) -> pd.DataFrame:
    """활성(is_active=TRUE) 매물 조회. nv_complex 조인으로 시도/시군구 필터."""
    where = ["l.is_active = TRUE"]
    params: dict = {"lim": int(limit)}
    if sido and sido != "전체":
        where.append("c.sido_name = :sido")
        params["sido"] = sido
    if sgg and sgg != "전체":
        where.append("c.sgg_name = :sgg")
        params["sgg"] = sgg
    if deal and deal in _TRADE_TYPE_MAP:
        where.append("l.trade_type = :trade_type")
        params["trade_type"] = _TRADE_TYPE_MAP[deal]

    sql = text(f"""
        SELECT l.article_no, l.complex_no, l.trade_type,
               l.exclusive_area, l.initial_price, l.current_price, l.rent_price,
               l.floor_info, l.direction, l.confirm_date,
               l.first_seen_date, l.last_seen_date,
               c.complex_name, c.sido_name, c.sgg_name, c.dong_name,
               c.latitude, c.longitude
        FROM nv_listing l
        JOIN nv_complex c ON l.complex_no = c.complex_no
        WHERE {' AND '.join(where)}
        ORDER BY l.last_seen_date DESC
        LIMIT :lim
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(sql, conn, params=params)


def get_complex_master(complex_no: str) -> dict | None:
    """단일 네이버 단지의 마스터 정보."""
    sql = text("""
        SELECT complex_no, complex_name, sido_name, sgg_name, dong_name,
               latitude, longitude
        FROM nv_complex WHERE complex_no = :complex_no
    """)
    with get_engine().connect() as conn:
        row = conn.execute(sql, {"complex_no": complex_no}).mappings().fetchone()
    return dict(row) if row else None


def listings_by_apt_id(apt_id: str) -> pd.DataFrame:
    """complex_mapping 을 거쳐 rt apt_id → nv_listing 전체 매물 조회.

    /complex 의 호가 추이 탭용. first_seen_date 부터 last_seen_date 까지 시간축 구성.
    """
    sql = text("""
        SELECT l.article_no, l.trade_type, l.exclusive_area,
               l.initial_price, l.current_price, l.rent_price,
               l.first_seen_date, l.last_seen_date, l.is_active
        FROM nv_listing l
        JOIN complex_mapping m ON l.complex_no = m.naver_complex_no
        WHERE m.apt_id = :apt_id
        ORDER BY l.first_seen_date
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(sql, conn, params={"apt_id": apt_id})


def active_listing_counts_by_sgg(sido: str | None = None) -> pd.DataFrame:
    """시군구별 활성 매물 수 (KPI용)."""
    where = ["l.is_active = TRUE"]
    params: dict = {}
    if sido and sido != "전체":
        where.append("c.sido_name = :sido")
        params["sido"] = sido
    sql = text(f"""
        SELECT c.sido_name AS sido, c.sgg_name AS sgg, COUNT(*) AS active_listings
        FROM nv_listing l
        JOIN nv_complex c ON l.complex_no = c.complex_no
        WHERE {' AND '.join(where)} AND c.sgg_name IS NOT NULL
        GROUP BY c.sido_name, c.sgg_name
        ORDER BY active_listings DESC
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(sql, conn, params=params)

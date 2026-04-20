"""단지 매핑(complex_mapping) 쿼리."""

from __future__ import annotations

import pandas as pd
from sqlalchemy import text

from dash_app.db import get_engine


def get_mapped_pairs(min_confidence: float = 0.0) -> pd.DataFrame:
    """rt_complex ↔ nv_complex 매핑 + 양쪽 마스터 조인."""
    sql = text("""
        SELECT m.apt_id, m.naver_complex_no, m.confidence_score, m.mapping_method,
               rc.apt_name, rc.sido_name, rc.sgg_name, rc.admin_dong,
               rc.latitude AS rt_lat, rc.longitude AS rt_lon,
               nc.complex_name, nc.latitude AS nv_lat, nc.longitude AS nv_lon
        FROM complex_mapping m
        LEFT JOIN rt_complex rc ON m.apt_id = rc.apt_id
        LEFT JOIN nv_complex nc ON m.naver_complex_no = nc.complex_no
        WHERE m.confidence_score >= :min_conf
        ORDER BY m.confidence_score DESC
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(sql, conn, params={"min_conf": float(min_confidence)})


def get_mapping_cover_rate() -> dict:
    """매핑 커버 비율 — 스펙 3.4 상단 배지(`cover 81%`)용."""
    sql = text("""
        SELECT
          (SELECT COUNT(*) FROM complex_mapping)                           AS mapped,
          (SELECT COUNT(*) FROM rt_complex WHERE sgg_name IS NOT NULL)    AS total_rt
    """)
    with get_engine().connect() as conn:
        row = conn.execute(sql).fetchone()
    mapped = int((row[0] if row else 0) or 0)
    total = int((row[1] if row else 0) or 0)
    rate = round(mapped / total, 4) if total else 0.0
    return {"mapped": mapped, "total": total, "cover_rate": rate}

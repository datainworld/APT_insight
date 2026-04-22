"""About 페이지 — 데이터 소스 커버리지 수치."""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import text

from dash_app.db import get_engine


@lru_cache(maxsize=1)
def get_coverage() -> dict:
    """각 테이블의 row count. 5분 TTL 캐시 없이 간단 lru_cache (프로세스 수명).

    About 페이지는 자주 조회되지 않고, 세부 수치 10분 단위 지연은 허용.
    """
    sql = text("""
        SELECT
            (SELECT COUNT(*) FROM rt_complex)                              AS rt_complex,
            (SELECT COUNT(*) FROM rt_trade)                                AS rt_trade,
            (SELECT COUNT(*) FROM rt_rent)                                 AS rt_rent,
            (SELECT COUNT(*) FROM nv_complex)                              AS nv_complex,
            (SELECT COUNT(*) FROM nv_listing WHERE is_active = TRUE)       AS nv_active,
            (SELECT COUNT(*) FROM complex_mapping)                         AS mapping,
            (SELECT COUNT(*) FROM news_articles)                           AS news
    """)
    with get_engine().connect() as conn:
        row = dict(conn.execute(sql).mappings().fetchone() or {})
    return {k: int(v or 0) for k, v in row.items()}


def get_pdf_count() -> int:
    """PGVector 에 적재된 문서 파일 수 (고유 source 기준). 실패 시 0."""
    try:
        sql = text(
            "SELECT COUNT(DISTINCT cmetadata->>'source') FROM langchain_pg_embedding"
        )
        with get_engine().connect() as conn:
            return int(conn.execute(sql).scalar() or 0)
    except Exception:
        return 0

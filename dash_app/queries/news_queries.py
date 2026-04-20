"""news_articles 조회 쿼리 — 홈 사이드 뉴스 + /insight 페이지용."""

from __future__ import annotations

import pandas as pd
from sqlalchemy import text

from dash_app.db import get_engine

_ALLOWED_SCOPES = {"regional", "national", "policy", "unknown"}
_ALLOWED_CATEGORIES = {"market", "policy", "rates", "other"}


def get_latest(n: int = 4, include_ads: bool = False) -> pd.DataFrame:
    """최근 뉴스 n건. 광고성 기사는 기본 제외."""
    where = []
    params: dict = {"lim": int(n)}
    if not include_ads:
        where.append("ad_filtered = FALSE")
    sql = text(f"""
        SELECT id, url, title, description, publisher, published_at,
               scope, sido_name, sgg_name, category
        FROM news_articles
        {('WHERE ' + ' AND '.join(where)) if where else ''}
        ORDER BY published_at DESC NULLS LAST
        LIMIT :lim
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(sql, conn, params=params)


def fetch(
    scope_days: int = 7,
    scope: str | None = None,
    category: str | None = None,
    sgg: str | None = None,
    include_ads: bool = False,
    limit: int = 200,
) -> pd.DataFrame:
    """유연한 필터 조회. 사용자 대상 파라미터는 모두 allowlist 검증."""
    where = [
        "published_at >= CURRENT_DATE - make_interval(days => :scope_days)",
    ]
    params: dict = {"scope_days": int(scope_days), "lim": int(limit)}
    if not include_ads:
        where.append("ad_filtered = FALSE")
    if scope in _ALLOWED_SCOPES:
        where.append("scope = :scope")
        params["scope"] = scope
    if category in _ALLOWED_CATEGORIES:
        where.append("category = :category")
        params["category"] = category
    if sgg:
        where.append("sgg_name = :sgg")
        params["sgg"] = sgg

    sql = text(f"""
        SELECT id, url, title, description, publisher, published_at,
               scope, sido_name, sgg_name, category
        FROM news_articles
        WHERE {' AND '.join(where)}
        ORDER BY published_at DESC NULLS LAST
        LIMIT :lim
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(sql, conn, params=params)


def get_status_counts(scope_days: int = 7) -> dict:
    """/insight 상단 status banner 용 — `지역 N · 전국/정책 M · 추출 불가 K`."""
    sql = text("""
        SELECT scope, COUNT(*) AS n
        FROM news_articles
        WHERE published_at >= CURRENT_DATE - make_interval(days => :scope_days)
          AND ad_filtered = FALSE
        GROUP BY scope
    """)
    with get_engine().connect() as conn:
        rows = conn.execute(sql, {"scope_days": int(scope_days)}).fetchall()
    counts = {scope: 0 for scope in _ALLOWED_SCOPES}
    for scope, n in rows:
        if scope in counts:
            counts[scope] = int(n)
    return counts

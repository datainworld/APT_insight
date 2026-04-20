"""부동산 뉴스 수집 ETL — Naver 검색 API → news_articles 테이블.

매일 run_daily.py 에서 호출된다. URL UNIQUE 제약으로 중복 삽입을 방지한다.

수집 전략:
- 수도권 시도별 + 전국 정책 키워드 + 시장 키워드로 검색
- 시도+시군구명이 본문/제목에 포함되면 scope=regional 로 태깅
- 카테고리는 키워드 매칭 (market/policy/rates/other)
- 광고성 기사는 ad_filtered=TRUE 로 표시하되 적재는 유지 (사후 필터링)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from sqlalchemy import text

from shared.config import NAVER_CLIENT_ID, NAVER_CLIENT_SECRET
from shared.db import get_engine

_KST = timezone(timedelta(hours=9))
_MAX_AGE_DAYS = 30
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_QUERIES_MARKET = [
    "수도권 아파트 매매", "서울 아파트 거래량", "경기도 아파트 시세",
    "인천 아파트 매매", "수도권 분양", "서울 전세",
]
_QUERIES_POLICY = [
    "부동산 대책", "재건축 규제", "주택 공급 정책", "전월세 법안",
    "다주택자 세제", "부동산 세금",
]
_QUERIES_RATES = ["주택담보대출 금리", "부동산 대출 규제", "전세자금대출"]

_SIDO_NAMES = {"서울": "서울특별시", "서울특별시": "서울특별시",
               "경기": "경기도", "경기도": "경기도",
               "인천": "인천광역시", "인천광역시": "인천광역시"}
_BODY_SELECTORS = [
    "article", "#articleBodyContents", "#article-view-content-div",
    ".article_body", "#newsct_article", "#content-body", ".news_view",
]
_AD_BRACKET_RE = re.compile(
    r"\[\s*(광고|AD|PR|보도자료|분양특집|특집|스폰서|Sponsored|기획)\s*\]",
    re.IGNORECASE,
)
_AD_TITLE_KEYWORDS = ("모델하우스", "선착순 분양", "마감임박", "즉시입주",
                      "분양 문의", "분양문의", "청약접수")
_AD_URL_PATTERNS = ("/ad/", "/promo/", "/pr/", "advertise", "sponsored", "promotion")


@dataclass
class CollectResult:
    queries_run: int = 0
    fetched: int = 0
    inserted: int = 0
    skipped_duplicate: int = 0
    skipped_stale: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


def _search_naver(query: str, display: int = 10) -> list[dict]:
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        return []
    try:
        resp = requests.get(
            "https://openapi.naver.com/v1/search/news.json",
            headers={
                "X-Naver-Client-Id": NAVER_CLIENT_ID,
                "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
            },
            params={"query": query, "display": display, "sort": "date"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("items", [])
    except Exception:
        return []


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


def _parse_pubdate(pub_date: str) -> datetime | None:
    try:
        return parsedate_to_datetime(pub_date).astimezone(_KST)
    except Exception:
        return None


def _scrape(url: str) -> tuple[str, str]:
    """Returns (body_preview_2kb, publisher). Best-effort."""
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"},
            timeout=5,
            allow_redirects=True,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        og = soup.find("meta", property="og:site_name")
        publisher = (
            og["content"].strip()
            if og and og.get("content")
            else urlparse(url).netloc.replace("www.", "")
        )

        body = ""
        for sel in _BODY_SELECTORS:
            tag = soup.select_one(sel)
            if tag:
                txt = tag.get_text(separator=" ", strip=True)
                if len(txt) > 100:
                    body = txt[:2000]
                    break
        return body, publisher
    except Exception:
        return "", urlparse(url).netloc.replace("www.", "")


# ---------------------------------------------------------------------------
# Classify
# ---------------------------------------------------------------------------


def _is_ad_like(title: str, desc: str, url: str) -> bool:
    if _AD_BRACKET_RE.search(title) or _AD_BRACKET_RE.search(desc):
        return True
    if any(k in title for k in _AD_TITLE_KEYWORDS):
        return True
    if any(p in url.lower() for p in _AD_URL_PATTERNS):
        return True
    return False


def _classify_category(query: str, title: str, desc: str) -> str:
    hay = f"{title} {desc}"
    if query in _QUERIES_POLICY or any(k in hay for k in ("규제", "정책", "법안", "세제")):
        return "policy"
    if query in _QUERIES_RATES or any(k in hay for k in ("금리", "대출")):
        return "rates"
    if query in _QUERIES_MARKET or any(k in hay for k in ("거래량", "매매", "전세", "분양", "시세")):
        return "market"
    return "other"


_SGG_CACHE: set[str] | None = None


def _known_sggs() -> set[str]:
    """Load sgg names from rt_complex — for regional scope tagging."""
    global _SGG_CACHE
    if _SGG_CACHE is not None:
        return _SGG_CACHE
    try:
        with get_engine().connect() as conn:
            rows = conn.execute(
                text("SELECT DISTINCT sgg_name FROM rt_complex WHERE sgg_name IS NOT NULL")
            ).fetchall()
        _SGG_CACHE = {r[0] for r in rows if r[0]}
    except Exception:
        _SGG_CACHE = set()
    return _SGG_CACHE


def _detect_region(title: str, desc: str) -> tuple[str, str | None, str | None]:
    """Return (scope, sido, sgg). scope ∈ {regional, national, unknown}."""
    hay = f"{title} {desc}"
    sgg_hit: str | None = None
    for s in _known_sggs():
        if s and s in hay:
            sgg_hit = s
            break

    sido_hit: str | None = None
    for short, full in _SIDO_NAMES.items():
        if short in hay:
            sido_hit = full
            break

    if sgg_hit or sido_hit:
        return "regional", sido_hit, sgg_hit
    if any(k in hay for k in ("전국", "정부", "국토부", "금융위")):
        return "national", None, None
    return "unknown", None, None


# ---------------------------------------------------------------------------
# Persist
# ---------------------------------------------------------------------------


_INSERT_SQL = text("""
    INSERT INTO news_articles
      (url, title, description, body, publisher, published_at,
       scope, sido_name, sgg_name, category, ad_filtered)
    VALUES
      (:url, :title, :description, :body, :publisher, :published_at,
       :scope, :sido_name, :sgg_name, :category, :ad_filtered)
    ON CONFLICT (url) DO NOTHING
""")


def _upsert(conn, article: dict) -> bool:
    res = conn.execute(_INSERT_SQL, article)
    return (res.rowcount or 0) > 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def collect(scrape_body: bool = True) -> dict:
    """Collect latest news and upsert to news_articles. Returns status dict."""
    result = CollectResult()
    cutoff = datetime.now(_KST) - timedelta(days=_MAX_AGE_DAYS)
    all_queries = _QUERIES_MARKET + _QUERIES_POLICY + _QUERIES_RATES
    engine = get_engine()

    with engine.begin() as conn:
        seen: set[str] = set()
        for query in all_queries:
            result.queries_run += 1
            for item in _search_naver(query, display=10):
                raw_url = (item.get("originallink") or item.get("link") or "").strip()
                if not raw_url or raw_url in seen:
                    continue
                seen.add(raw_url)
                result.fetched += 1

                title = _strip_html(item.get("title", ""))
                desc = _strip_html(item.get("description", ""))
                published_at = _parse_pubdate(item.get("pubDate", ""))
                if published_at and published_at < cutoff:
                    result.skipped_stale += 1
                    continue

                scope, sido, sgg = _detect_region(title, desc)
                category = _classify_category(query, title, desc)
                ad_flag = _is_ad_like(title, desc, raw_url)

                body, publisher = ("", urlparse(raw_url).netloc.replace("www.", ""))
                if scrape_body and not ad_flag:
                    body, publisher = _scrape(raw_url)

                try:
                    inserted = _upsert(
                        conn,
                        {
                            "url": raw_url,
                            "title": title[:500],
                            "description": desc[:2000] if desc else None,
                            "body": body[:2000] if body else None,
                            "publisher": publisher[:100] if publisher else None,
                            "published_at": published_at,
                            "scope": scope,
                            "sido_name": sido,
                            "sgg_name": sgg,
                            "category": category,
                            "ad_filtered": ad_flag,
                        },
                    )
                except Exception as e:
                    result.errors.append(f"{raw_url}: {e}")
                    continue

                if inserted:
                    result.inserted += 1
                else:
                    result.skipped_duplicate += 1

    return {
        "status": "success" if not result.errors else "partial",
        "queries_run": result.queries_run,
        "fetched": result.fetched,
        "inserted": result.inserted,
        "skipped_duplicate": result.skipped_duplicate,
        "skipped_stale": result.skipped_stale,
        "error_count": len(result.errors),
    }


if __name__ == "__main__":
    import json

    print(json.dumps(collect(), ensure_ascii=False, indent=2))

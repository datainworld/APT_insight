"""News 에이전트 — 네이버 검색 API로 실시간 뉴스 검색 + 요약.

DB에 저장하지 않고, 질의 시 실시간으로 검색하여 답변한다.
"""

import re
import requests
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from langchain_core.messages import HumanMessage, SystemMessage

from agents.config import get_llm
from shared.config import NAVER_CLIENT_ID, NAVER_CLIENT_SECRET

_KST = timezone(timedelta(hours=9))
_MAX_AGE_DAYS = 180  # 이보다 오래된 기사는 제외

# 기사 본문 추출용 CSS 선택자 (한국 언론사 공통 패턴)
_BODY_SELECTORS = [
    "article",
    "#articleBodyContents",
    "#article-view-content-div",
    ".article_body",
    "#newsct_article",
    ".go_trans",
    "#content-body",
    ".news_view",
    "div[class*='article']",
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
}

# ── 광고성 기사 필터링 패턴 ──
# 브래킷 형태 광고 태그 (정규식 — 공백 허용)
_AD_BRACKET_RE = re.compile(
    r"\[\s*(광고|AD|PR|보도자료|분양특집|특집|스폰서|Sponsored|기획)\s*\]",
    re.IGNORECASE,
)
# 제목에 포함되면 직접 판매성 기사로 간주
_AD_TITLE_KEYWORDS = (
    "모델하우스", "선착순 분양", "특별 분양", "마감임박", "즉시입주",
    "계약금 ", "분양 문의", "분양문의", "청약접수",
)
# URL 경로에 광고 흔적
_AD_URL_PATTERNS = ("/ad/", "/promo/", "/pr/", "advertise", "sponsored", "promotion")
# 설명(description)에 포함되면 광고성
_AD_DESC_KEYWORDS = (
    "자료 제공", "자료제공", "본 기사는 광고", "보도자료입니다",
    "분양 문의", "모델하우스 문의",
)


def _is_ad_like(title: str, desc: str, url: str) -> bool:
    """광고성·분양홍보 기사 여부를 메타데이터만으로 판정한다."""
    if _AD_BRACKET_RE.search(title) or _AD_BRACKET_RE.search(desc):
        return True
    if any(kw in title for kw in _AD_TITLE_KEYWORDS):
        return True
    url_lower = url.lower()
    if any(p in url_lower for p in _AD_URL_PATTERNS):
        return True
    if any(kw in desc for kw in _AD_DESC_KEYWORDS):
        return True
    return False

SYSTEM_PROMPT_TEMPLATE: str = """당신은 수도권 아파트 부동산 뉴스 분석 전문가입니다.
오늘 날짜: {today}.

사용자 질문에 답하려면 반드시 search_news 도구로 먼저 검색한 후 그 결과만 사용하세요.

규칙:
- 검색 결과에 있는 제목·본문·날짜·수치만 인용하세요. **검색 결과에 없는 통계·사건·수치는 절대 만들지 마세요.**
- 모든 인용에 언론사·날짜·URL을 명시하세요.
- 기사 날짜를 답변에 쓸 때는 제공된 YYYY-MM-DD 형식 그대로 사용하세요.
- 기사가 오늘({today})보다 과거이면 반드시 "YYYY-MM-DD 보도" 형태로 과거 시점임을 밝히세요.
- 검색 결과가 부족하면 "관련 최신 뉴스가 부족합니다"라고 솔직히 답하세요.
- 한국어로 답변하세요.
"""


def _search_naver_news(query: str, display: int = 5) -> list[dict]:
    """네이버 검색 API로 뉴스를 조회한다."""
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


def _scrape_article(url: str) -> tuple[str, str]:
    """기사 URL에서 본문과 언론사명을 추출한다. 실패 시 ("", "")."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=5, allow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # 언론사명
        og = soup.find("meta", property="og:site_name")
        source = og["content"].strip() if og and og.get("content") else ""
        if not source:
            source = urlparse(url).netloc.replace("www.", "")

        # 본문
        body = ""
        for selector in _BODY_SELECTORS:
            tag = soup.select_one(selector)
            if tag:
                text = tag.get_text(separator=" ", strip=True)
                if len(text) > 100:
                    body = text[:2000]
                    break

        return body, source
    except Exception:
        return "", ""


def _clean_html(text: str) -> str:
    """HTML 태그 제거."""
    return re.sub(r"<[^>]+>", "", text).strip()


def _parse_pubdate(pub_date: str) -> datetime | None:
    """RFC 822 pubDate → KST datetime. 실패 시 None."""
    try:
        dt = parsedate_to_datetime(pub_date)
        return dt.astimezone(_KST) if dt else None
    except (TypeError, ValueError):
        return None


def _extract_text(content) -> str:
    """Gemini가 content를 리스트로 반환할 때 텍스트를 추출한다."""
    if isinstance(content, list):
        return "".join(
            p.get("text", "") if isinstance(p, dict) else str(p)
            for p in content
        )
    return content if isinstance(content, str) else str(content)


def _fetch_articles(query: str, cutoff) -> str:
    """네이버 뉴스 검색 + 필터링 + 본문 스크래핑 → 포매팅 문자열."""
    items = _search_naver_news(query, display=30)
    if not items:
        return ""

    results = []
    for item in items:
        if len(results) >= 10:
            break

        title = _clean_html(item.get("title", ""))
        desc = _clean_html(item.get("description", ""))
        link = item.get("link", "")
        pub_date_raw = item.get("pubDate", "")

        # 1차 필터: 메타데이터 기반 광고성 기사 제외
        if _is_ad_like(title, desc, link):
            continue

        # 2차 필터: 180일 이상 된 기사 제외
        pub_dt = _parse_pubdate(pub_date_raw)
        if pub_dt and pub_dt.date() < cutoff:
            continue
        pub_date_fmt = pub_dt.strftime("%Y-%m-%d") if pub_dt else pub_date_raw

        body, source = _scrape_article(link)

        results.append(
            f"제목: {title}\n"
            f"언론사: {source}\n"
            f"날짜: {pub_date_fmt}\n"
            f"URL: {link}\n"
            f"내용: {body or desc}\n"
        )

    return "\n---\n".join(results)


def run_news(query: str) -> str:
    """질의 → 네이버 뉴스 검색 → LLM 1회 호출로 요약."""
    today = datetime.now(_KST).date()
    cutoff = today - timedelta(days=_MAX_AGE_DAYS)
    articles = _fetch_articles(query, cutoff)

    if not articles:
        return "관련 최신 뉴스가 부족합니다 (광고·180일 경과 기사 제외)."

    llm = get_llm()
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(today=today.strftime("%Y-%m-%d"))
    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"[사용자 질의]\n{query}\n\n[검색된 뉴스 기사]\n{articles}"),
    ])
    return _extract_text(response.content)

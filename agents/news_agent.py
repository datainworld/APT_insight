"""News 에이전트 — 네이버 검색 API로 실시간 뉴스 검색 + 요약.

DB에 저장하지 않고, 질의 시 실시간으로 검색하여 답변한다.
"""

import re
import requests
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from langchain.agents import create_agent
from langchain.tools import tool

from agents.config import get_llm
from shared.config import NAVER_CLIENT_ID, NAVER_CLIENT_SECRET

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

SYSTEM_PROMPT: str = """당신은 수도권 아파트 부동산 뉴스 분석 전문가입니다.
사용자의 질문에 답하기 위해 반드시 search_news 도구로 최신 뉴스를 검색한 후 답변하세요.

규칙:
- 검색된 기사 내용만을 근거로 답변하세요.
- 출처(언론사, 날짜, URL)를 반드시 포함하세요.
- 검색 결과가 부족하면 솔직히 알려주세요.
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


def create_news_agent():
    """News 에이전트를 생성한다."""
    llm = get_llm()

    @tool
    def search_news(query: str) -> str:
        """네이버 뉴스 검색 API로 최신 부동산 뉴스를 검색합니다.
        query: 검색어 (예: '아파트 시장 전망', '강남 아파트 가격')
        """
        items = _search_naver_news(query, display=5)
        if not items:
            return "뉴스 검색 결과가 없습니다."

        results = []
        for item in items[:3]:
            title = _clean_html(item.get("title", ""))
            desc = _clean_html(item.get("description", ""))
            link = item.get("link", "")
            pub_date = item.get("pubDate", "")

            body, source = _scrape_article(link)

            results.append(
                f"제목: {title}\n"
                f"언론사: {source}\n"
                f"날짜: {pub_date}\n"
                f"URL: {link}\n"
                f"내용: {body or desc}\n"
            )

        return "\n---\n".join(results)

    return create_agent(llm, [search_news], system_prompt=SYSTEM_PROMPT)

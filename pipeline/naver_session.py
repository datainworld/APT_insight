"""네이버 부동산 API 세션 + adaptive delay (교재 10장).

curl_cffi 세션(Chrome 지문 우회), JWT 토큰 취득, 쿠키 주입,
adaptive delay(성공 시 감소·429 시 증가), 지수 백오프 재시도를 담당.

초기 수집(`collect_naver.py full`)과 일일 갱신(`update_nv_daily.py`) 공용.
"""

import random
import re
import threading
import time

from curl_cffi import requests as curl_requests

from shared.config import NAVER_LAND_COOKIE

BASE_URL = "https://new.land.naver.com/api"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://new.land.naver.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "sec-ch-ua": '"Chromium";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}

MIN_DELAY = 0.8
MAX_DELAY = 3.5
MAX_RETRIES = 5

_delay_lock = threading.Lock()
_current_delay = 1.5

_session = curl_requests.Session(impersonate="chrome")
_session.headers.update(_HEADERS)
_initialized = False


def set_min_delay(seconds: float) -> None:
    """운영 수집용 MIN_DELAY 하향 (교재 18장: 0.5s)."""
    global MIN_DELAY, _current_delay
    with _delay_lock:
        MIN_DELAY = seconds
        if _current_delay > seconds:
            _current_delay = seconds


def _init_session() -> None:
    global _initialized
    if _initialized:
        return

    print("  세션 초기화 중...")
    try:
        resp = _session.get("https://new.land.naver.com/", timeout=30)
        m = re.search(r'"token"\s*:\s*"([^"]+)"', resp.text)
        if m:
            _session.headers["authorization"] = f"Bearer {m.group(1)}"
            print("    JWT 토큰 획득")
        time.sleep(2)
    except Exception as e:
        print(f"    메인 페이지 방문 실패: {e}")

    if NAVER_LAND_COOKIE:
        for part in NAVER_LAND_COOKIE.split(";"):
            part = part.strip()
            if "=" in part:
                key, _, val = part.partition("=")
                _session.cookies.set(key.strip(), val.strip())

    _initialized = True
    print("  세션 초기화 완료")


def _adjust_delay(success: bool) -> None:
    global _current_delay
    with _delay_lock:
        if success:
            _current_delay = max(MIN_DELAY, _current_delay * 0.95)
        else:
            _current_delay = min(MAX_DELAY, _current_delay * 1.5)


def request_json(url: str, params: dict | None = None,
                  retries: int = MAX_RETRIES) -> dict | None:
    """adaptive delay + 재시도가 붙은 네이버 API GET → JSON. 404는 None."""
    _init_session()

    for attempt in range(retries):
        try:
            with _delay_lock:
                delay = _current_delay
            time.sleep(delay + random.uniform(0, 0.3))

            resp = _session.get(url, params=params, timeout=30)

            if resp.status_code == 429:
                _adjust_delay(False)
                wait = (2 ** attempt) * 5
                print(f"  Rate limit (429). {attempt + 1}/{retries}회 재시도, {wait}s 대기")
                time.sleep(wait)
                continue

            if resp.status_code == 404:
                _adjust_delay(True)
                return None

            resp.raise_for_status()
            _adjust_delay(True)
            return resp.json()

        except Exception as e:
            if attempt < retries - 1:
                wait = (2 ** attempt) * 2
                print(f"  요청 실패 ({attempt + 1}/{retries}): {e}, {wait}s 후 재시도")
                time.sleep(wait)
            else:
                print(f"  최종 실패: {url}")
    return None

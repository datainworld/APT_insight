"""파이프라인 공통 유틸리티.

- API 요청 (fetch_data, parse_api_items)
- 지오코딩 (get_kakao_coords, build_address)
- 파일 관리 (save_to_csv, get_latest_file, get_today_str)
"""

import os
import re
import glob
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import unquote

KST = ZoneInfo("Asia/Seoul")


def now_kst() -> datetime:
    """KST 기준 현재 시각. VPS가 UTC여도 날짜가 한국 시간과 일치하도록."""
    return datetime.now(KST)

import pandas as pd
import requests
import xmltodict

from shared.config import DATA_API_KEY, KAKAO_API_KEY, BASE_DIR

DATA_DIR = str(BASE_DIR / "data")
os.makedirs(DATA_DIR, exist_ok=True)


# ==============================================================================
# API 유틸리티
# ==============================================================================

def fetch_data(url: str, params: dict, retries: int = 5) -> dict | str | None:
    """공공데이터 API 요청. serviceKey 자동 추가, XML/JSON 자동 파싱."""
    if not DATA_API_KEY:
        raise ValueError("DATA_API_KEY가 .env에 설정되지 않았습니다.")
    params["serviceKey"] = unquote(DATA_API_KEY)

    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code == 429:
                print("Rate limit (429). 스킵합니다.")
                return None
            resp.raise_for_status()

            text = resp.text.strip()
            content_type = resp.headers.get("Content-Type", "")
            if "xml" in content_type or text.startswith("<"):
                return xmltodict.parse(text)
            if "json" in content_type:
                return resp.json()
            return text

        except requests.RequestException as e:
            print(f"요청 실패 ({attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(2)
    return None


def parse_api_items(data: dict | None) -> list[dict]:
    """공공데이터 API 응답에서 item 리스트를 추출한다."""
    if not data or not isinstance(data, dict):
        return []
    try:
        response = data.get("response", {})
        header = response.get("header", {})
        if str(header.get("resultCode")) not in ("00", "000"):
            return []
        items = response.get("body", {}).get("items")
        if not items:
            return []
        if isinstance(items, list):
            return items
        if isinstance(items, dict):
            item_list = items.get("item", [])
            return [item_list] if isinstance(item_list, dict) else item_list
    except (AttributeError, TypeError):
        pass
    return []


# ==============================================================================
# 지오코딩
# ==============================================================================

def get_kakao_coords(address: str) -> tuple[str | None, str | None, str | None]:
    """Kakao API로 주소 → (위도, 경도, 행정동) 변환."""
    if not KAKAO_API_KEY or not address:
        return None, None, None

    headers = {"Authorization": f"KakaoAK {KAKAO_API_KEY}"}
    try:
        resp = requests.get(
            "https://dapi.kakao.com/v2/local/search/address.json",
            headers=headers, params={"query": address}, timeout=5, verify=False,
        )
        if resp.status_code != 200 or not resp.json().get("documents"):
            return None, None, None

        doc = resp.json()["documents"][0]
        y, x = doc["y"], doc["x"]

        # 행정동 조회
        admin_dong = None
        try:
            c_resp = requests.get(
                "https://dapi.kakao.com/v2/local/geo/coord2regioncode.json",
                headers=headers, params={"x": x, "y": y}, timeout=5, verify=False,
            )
            if c_resp.status_code == 200:
                for region in c_resp.json().get("documents", []):
                    if region["region_type"] == "H":
                        admin_dong = region["region_3depth_name"]
                        break
        except Exception:
            pass

        if not admin_dong and doc.get("address"):
            admin_dong = doc["address"].get("region_3depth_name")

        return y, x, admin_dong
    except Exception:
        return None, None, None


def build_address(row) -> str:
    """거래 원본 레코드에서 검색용 도로명/지번 주소를 조합한다."""
    sgg = str(row.get("sggNm", "")) if pd.notna(row.get("sggNm")) else ""
    road = str(row.get("roadNm", "")) if pd.notna(row.get("roadNm")) else ""

    def _clean_num(n):
        if pd.isna(n) or str(n) == "nan":
            return ""
        try:
            return str(int(float(str(n))))
        except (ValueError, TypeError):
            return str(n).strip()

    if road and road != "nan":
        bon = _clean_num(row.get("roadNmBonbun", ""))
        bu = _clean_num(row.get("roadNmBubun", ""))
        addr = f"{sgg} {road}"
        if bon and bon != "0":
            addr += f" {bon}"
            if bu and bu != "0":
                addr += f"-{bu}"
        return addr.strip()

    umd = str(row.get("umdNm", "")) if pd.notna(row.get("umdNm")) else ""
    jibun = str(row.get("jibun", "")) if pd.notna(row.get("jibun")) else ""
    return f"{sgg} {umd} {jibun}".strip()


# ==============================================================================
# 파일 관리
# ==============================================================================

def get_today_str() -> str:
    """오늘 날짜를 YYYYMMDD 형식으로 반환 (KST)."""
    return now_kst().strftime("%Y%m%d")


def save_to_csv(data_list: list[dict], filename: str) -> None:
    """딕셔너리 리스트를 DATA_DIR 아래 CSV로 저장."""
    if not data_list:
        print(f"저장할 데이터 없음: {filename}")
        return
    filepath = os.path.join(DATA_DIR, filename)
    df = pd.DataFrame(data_list)
    df.to_csv(filepath, index=False, encoding="utf-8-sig")
    print(f"저장: {filepath} ({len(df)}건)")


def get_latest_file(pattern: str, exclude_today: bool = False) -> str | None:
    """DATA_DIR에서 패턴에 맞는 최신 파일 경로를 반환."""
    files = glob.glob(os.path.join(DATA_DIR, pattern))
    if not files:
        return None
    files.sort(key=os.path.getctime, reverse=True)
    if exclude_today:
        today = get_today_str()
        files = [f for f in files if today not in f]
    return files[0] if files else None

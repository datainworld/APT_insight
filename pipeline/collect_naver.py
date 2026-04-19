"""네이버 부동산 매물 초기 수집 스크립트 (교재 10~13장).

최초 전체 수집(full)만 담당. 일일 증분은 `update_nv_daily.py`, 매핑은 `build_mapping.py`.

사용법:
    python -m pipeline.collect_naver              # 전체 수집
    python -m pipeline.collect_naver --skip-db    # DB 저장 생략
    python -m pipeline.collect_naver --test       # 테스트 모드 (10개 동, 20단지)
    python -m pipeline.collect_naver --resume     # 체크포인트 이어받기
"""

import os
import re
import json
import time
import argparse

import pandas as pd
import requests as std_requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlalchemy import text

from shared.config import KAKAO_API_KEY
from shared.db import get_engine
from pipeline.utils import get_latest_file, get_today_str, now_kst, DATA_DIR
from pipeline.naver_session import BASE_URL, request_json


# ==============================================================================
# 상수
# ==============================================================================

SIDO_CODES = {
    "서울특별시": "1100000000",
    "경기도": "4100000000",
    "인천광역시": "2800000000",
}

TRADE_TYPES = {"A1": "매매", "B1": "전세", "B2": "월세"}

MAX_WORKERS = 12  # 네이버 수집 병렬도 (adaptive delay가 429 감지 시 자동 조절)
CHECKPOINT_INTERVAL = 200


# ==============================================================================
# 가격 파싱
# ==============================================================================

def _parse_price(price_str: str | None) -> int:
    if not price_str or not isinstance(price_str, str):
        return 0
    price_str = price_str.strip().replace(",", "")
    total = 0
    eok = re.search(r"(\d+)억", price_str)
    if eok:
        total += int(eok.group(1)) * 10000
    remaining = re.sub(r"\d+억\s*", "", price_str).strip()
    if remaining:
        num = re.search(r"(\d+)", remaining)
        if num:
            total += int(num.group(1))
    elif not eok:
        num = re.search(r"(\d+)", price_str)
        if num:
            total = int(num.group(1))
    return total


# ==============================================================================
# Step 1: 지역코드 수집
# ==============================================================================

def _collect_sido_dongs(sido_name: str, sido_code: str) -> tuple[list[dict], int]:
    """단일 시도의 시군구→읍면동 코드를 수집한다 (병렬 워커용)."""
    dongs = []
    data = request_json(f"{BASE_URL}/regions/list", {"cortarNo": sido_code})
    if not data or "regionList" not in data:
        return dongs, 0

    sgg_list = data["regionList"]
    for sgg in sgg_list:
        sgg_code = sgg.get("cortarNo", "")
        sgg_name = sgg.get("cortarName", "")
        dong_data = request_json(f"{BASE_URL}/regions/list", {"cortarNo": sgg_code})
        if not dong_data or "regionList" not in dong_data:
            continue

        for dong in dong_data["regionList"]:
            dongs.append({
                "sido_name": sido_name,
                "sgg_name": sgg_name,
                "sgg_code": sgg_code,
                "dong_name": dong.get("cortarName", ""),
                "dong_code": dong.get("cortarNo", ""),
                "center_lat": dong.get("centerLat", 0),
                "center_lon": dong.get("centerLon", 0),
            })

    return dongs, len(sgg_list)


def get_cortars() -> tuple[list[dict], int]:
    """서울/경기/인천 시군구→읍면동 코드를 병렬 수집한다."""
    print("\n[Step 1] 지역코드 수집 (3개 시도 병렬)")
    all_dongs = []
    sgg_count = 0

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_collect_sido_dongs, name, code): name
            for name, code in SIDO_CODES.items()
        }
        for future in as_completed(futures):
            sido_name = futures[future]
            try:
                dongs, sgg_cnt = future.result()
                all_dongs.extend(dongs)
                sgg_count += sgg_cnt
                print(f"  {sido_name}: {len(dongs)}개 읍면동 ({sgg_cnt}개 시군구)")
            except Exception as e:
                print(f"  {sido_name} 수집 실패: {e}")

    print(f"  총 {len(all_dongs)}개 읍면동 (시군구 {sgg_count}개)")
    return all_dongs, sgg_count


# ==============================================================================
# Step 2: 단지 목록 수집
# ==============================================================================

def get_active_complexes(dong_list: list[dict],
                          test_mode: bool = False) -> dict[str, dict]:
    """동별 아파트 단지 목록을 수집한다."""
    print("\n[Step 2] 단지 목록 수집")
    complexes = {}
    targets = dong_list[:10] if test_mode else dong_list

    for i, dong in enumerate(targets):
        if (i + 1) % 50 == 0 or i == 0:
            print(f"  진행: {i + 1}/{len(targets)} ({dong['sgg_name']} {dong['dong_name']})")

        data = request_json(
            f"{BASE_URL}/regions/complexes",
            {"cortarNo": dong["dong_code"], "realEstateType": "APT", "order": ""},
        )
        if not data:
            continue

        for cpx in data.get("complexList", []):
            cno = str(cpx.get("complexNo", ""))
            if cno:
                complexes[cno] = {
                    "complex_no": cno,
                    "complex_name": cpx.get("complexName", ""),
                    "sido_name": dong["sido_name"],
                    "sgg_name": dong["sgg_name"],
                    "latitude": float(cpx.get("latitude", 0)),
                    "longitude": float(cpx.get("longitude", 0)),
                }

    print(f"  수집 단지: {len(complexes)}개")
    return complexes


# ==============================================================================
# Step 3: 행정동 변환
# ==============================================================================

def _get_admin_dong(lat: float, lon: float) -> str | None:
    if not KAKAO_API_KEY or not lat or not lon:
        return None
    try:
        resp = std_requests.get(
            "https://dapi.kakao.com/v2/local/geo/coord2regioncode.json",
            headers={"Authorization": f"KakaoAK {KAKAO_API_KEY}"},
            params={"x": lon, "y": lat}, timeout=5, verify=False,
        )
        if resp.status_code == 200:
            for region in resp.json().get("documents", []):
                if region["region_type"] == "H":
                    return region["region_3depth_name"]
    except Exception:
        pass
    return None


def convert_to_admin_dong(complexes: dict) -> dict:
    """위경도 → 행정동 일괄 변환 (20 workers)."""
    print("\n[Step 3] 행정동 변환")
    if not KAKAO_API_KEY:
        print("  KAKAO_API_KEY 없음. 건너뜀.")
        for info in complexes.values():
            info["dong_name"] = None
        return complexes

    total, success = len(complexes), 0
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {
            executor.submit(_get_admin_dong, info["latitude"], info["longitude"]): cno
            for cno, info in complexes.items()
        }
        for future in as_completed(futures):
            cno = futures[future]
            try:
                admin_dong = future.result()
            except Exception:
                admin_dong = None
            complexes[cno]["dong_name"] = admin_dong
            if admin_dong:
                success += 1

    print(f"  행정동 변환: {success}/{total}건 성공")
    return complexes


def sync_complexes(new_complexes: dict, existing_df: pd.DataFrame
                    ) -> tuple[dict, pd.DataFrame, int]:
    """기존 단지와 비교하여 신규만 행정동 변환 후 병합 (daily용)."""
    print("\n[Step 2b] 단지 동기화")
    existing_nos = set(existing_df["complex_no"].astype(str))
    new_only = {k: v for k, v in new_complexes.items() if k not in existing_nos}
    print(f"  기존: {len(existing_nos)}개, 신규: {len(new_only)}개")

    if new_only:
        convert_to_admin_dong(new_only)
        new_rows = pd.DataFrame(new_only.values())
        existing_df = pd.concat([existing_df, new_rows], ignore_index=True)
        existing_df.drop_duplicates(subset=["complex_no"], keep="last", inplace=True)

    all_complexes = {}
    for _, row in existing_df.iterrows():
        cno = str(row["complex_no"])
        all_complexes[cno] = {
            "complex_no": cno,
            "complex_name": row.get("complex_name", ""),
            "sido_name": row.get("sido_name", ""),
            "sgg_name": row.get("sgg_name", ""),
            "dong_name": row.get("dong_name", None),
            "latitude": row.get("latitude", 0),
            "longitude": row.get("longitude", 0),
        }
    return all_complexes, existing_df, len(new_only)


# ==============================================================================
# Step 4: 매물 수집
# ==============================================================================

def _fetch_articles(complex_no: str, trade_type: str) -> list[dict]:
    articles = []
    page = 1
    while page <= 10:
        data = request_json(
            f"{BASE_URL}/articles/complex/{complex_no}",
            {"realEstateType": "APT", "tradeType": trade_type,
             "page": page, "sameAddressGroup": "false"},
        )
        if not data:
            break
        article_list = data.get("articleList", [])
        if not article_list:
            break
        articles.extend(article_list)
        if not data.get("isMoreData", False):
            break
        page += 1
    return articles


def _parse_article(article: dict, complex_no: str,
                    trade_type: str, today_str: str) -> dict | None:
    article_no = str(article.get("articleNo", ""))
    if not article_no:
        return None

    area2 = article.get("area2", article.get("exclusiveArea", 0))
    try:
        exclusive_area = int(float(area2))
    except (ValueError, TypeError):
        exclusive_area = 0

    price = _parse_price(str(article.get("dealOrWarrantPrc", "0")))
    rent = _parse_price(str(article.get("rentPrc", "0"))) if trade_type == "B2" else 0

    confirm_ymd = article.get("articleConfirmYmd", "")
    confirm_date = None
    if confirm_ymd and len(confirm_ymd) == 8:
        confirm_date = f"{confirm_ymd[:4]}-{confirm_ymd[4:6]}-{confirm_ymd[6:8]}"

    return {
        "article_no": article_no,
        "complex_no": complex_no,
        "trade_type": trade_type,
        "exclusive_area": exclusive_area,
        "initial_price": price,
        "current_price": price,
        "rent_price": rent,
        "floor_info": str(article.get("floorInfo", "")).strip() or None,
        "direction": str(article.get("direction", "")).strip() or None,
        "confirm_date": confirm_date,
        "first_seen_date": today_str,
        "last_seen_date": today_str,
        "is_active": True,
    }


# 체크포인트

def _checkpoint_path() -> str:
    return os.path.join(DATA_DIR, f"checkpoint_listing_{get_today_str()}.json")


def _save_checkpoint(processed: set, listings: list, stats: dict) -> None:
    with open(_checkpoint_path(), "w", encoding="utf-8") as f:
        json.dump({
            "date": get_today_str(),
            "processed_complexes": list(processed),
            "listings": listings,
            "stats": stats,
        }, f, ensure_ascii=False)
    print(f"  체크포인트 저장: {len(processed)}단지, {len(listings)}건")


def _load_checkpoint() -> dict | None:
    path = _checkpoint_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _collect_one_complex(cno: str, today_date: str) -> tuple[str, list[dict]]:
    results = []
    for trade_type in TRADE_TYPES:
        for art in _fetch_articles(cno, trade_type):
            parsed = _parse_article(art, cno, trade_type, today_date)
            if parsed:
                results.append(parsed)
    return cno, results


def collect_listings_incremental(complexes: dict,
                                  test_mode: bool = False,
                                  resume: bool = False) -> tuple[pd.DataFrame, dict]:
    """단지별 매물을 병렬 수집하고 증분 비교한다."""
    print("\n[Step 4] 매물 증분 수집")
    today_date = now_kst().strftime("%Y-%m-%d")

    # 기존 매물 로드 (증분 비교)
    existing_articles: dict[str, dict] = {}
    prev_file = get_latest_file("naver_listing_*.csv", exclude_today=True)
    if prev_file:
        try:
            df_prev = pd.read_csv(prev_file, dtype={"article_no": str})
            for _, row in df_prev[df_prev["is_active"] == True].iterrows():
                existing_articles[str(row["article_no"])] = row.to_dict()
            print(f"  기존 활성 매물: {len(existing_articles)}건")
        except Exception as e:
            print(f"  기존 데이터 로드 실패: {e}")

    complex_list = list(complexes.keys())
    if test_mode:
        complex_list = complex_list[:20]

    all_listings: list[dict] = []
    processed_set: set[str] = set()
    stats = {"sale": 0, "jeonse": 0, "monthly": 0, "new": 0, "updated": 0}

    if resume:
        ckpt = _load_checkpoint()
        if ckpt and ckpt.get("date") == get_today_str():
            processed_set = set(ckpt["processed_complexes"])
            all_listings = ckpt["listings"]
            stats = ckpt["stats"]
            print(f"  체크포인트 복원: {len(processed_set)}단지, {len(all_listings)}건")

    remaining = [c for c in complex_list if c not in processed_set]
    total_all = len(complex_list)
    print(f"  수집 대상: {len(remaining)}단지 (전체 {total_all})")

    seen_article_nos = {item.get("article_no", "") for item in all_listings}
    batch_count = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(_collect_one_complex, cno, today_date): cno
            for cno in remaining
        }
        for future in as_completed(futures):
            cno = futures[future]
            try:
                _, results = future.result()
            except Exception as e:
                print(f"  {cno} 수집 오류: {e}")
                continue

            for parsed in results:
                ano = parsed["article_no"]
                seen_article_nos.add(ano)

                tt = parsed["trade_type"]
                if tt == "A1":
                    stats["sale"] += 1
                elif tt == "B1":
                    stats["jeonse"] += 1
                else:
                    stats["monthly"] += 1

                if ano in existing_articles:
                    prev = existing_articles[ano]
                    parsed["first_seen_date"] = prev.get("first_seen_date", today_date)
                    parsed["initial_price"] = prev.get("initial_price", parsed["current_price"])
                    if parsed["current_price"] != prev.get("current_price"):
                        stats["updated"] += 1
                else:
                    stats["new"] += 1

                all_listings.append(parsed)

            processed_set.add(cno)
            batch_count += 1

            done = len(processed_set)
            if done % 100 == 0 or done == total_all:
                print(f"  진행: {done}/{total_all} ({stats['new']}신규, {stats['updated']}갱신)")
            if batch_count % CHECKPOINT_INTERVAL == 0:
                _save_checkpoint(processed_set, all_listings, stats)

    # 종료 매물 처리
    closed_count = 0
    for ano, prev in existing_articles.items():
        if ano not in seen_article_nos:
            prev_copy = dict(prev)
            prev_copy["is_active"] = False
            all_listings.append(prev_copy)
            closed_count += 1

    stats["closed"] = closed_count
    stats["total"] = len(all_listings)

    print(f"\n  매매: {stats['sale']}, 전세: {stats['jeonse']}, 월세: {stats['monthly']}")
    print(f"  신규: {stats['new']}, 가격변경: {stats['updated']}, 종료: {stats['closed']}, 총: {stats['total']}")

    # 체크포인트 삭제
    path = _checkpoint_path()
    if os.path.exists(path):
        os.remove(path)

    return pd.DataFrame(all_listings) if all_listings else pd.DataFrame(), stats


# ==============================================================================
# Step 5: CSV 저장
# ==============================================================================

def save_results_csv(df_complex: pd.DataFrame,
                      df_listing: pd.DataFrame) -> dict[str, str]:
    print("\n[Step 5] CSV 저장")
    today = get_today_str()
    files = {}

    complex_file = os.path.join(DATA_DIR, f"naver_complex_{today}.csv")
    df_complex.to_csv(complex_file, index=False, encoding="utf-8-sig")
    print(f"  단지: {complex_file} ({len(df_complex)}건)")
    files["complex"] = complex_file

    if not df_listing.empty:
        listing_file = os.path.join(DATA_DIR, f"naver_listing_{today}.csv")
        df_listing.to_csv(listing_file, index=False, encoding="utf-8-sig")
        print(f"  매물: {listing_file} ({len(df_listing)}건)")
        files["listing"] = listing_file

    return files


# ==============================================================================
# Step 6: DB 저장 (UPSERT)
# ==============================================================================

def save_to_db(df_complex: pd.DataFrame, df_listing: pd.DataFrame) -> dict:
    """nv_complex/nv_listing에 UPSERT한다."""
    print("\n[Step 6] DB 적재")
    engine = get_engine()
    results = {}

    # nv_complex UPSERT
    chunk_size = 5000
    total_complex = 0
    with engine.begin() as conn:
        for i in range(0, len(df_complex), chunk_size):
            chunk = df_complex.iloc[i:i + chunk_size]
            chunk.to_sql("nv_complex_staging", conn, if_exists="replace", index=False)
            conn.execute(text("""
                INSERT INTO nv_complex (complex_no, complex_name, sido_name, sgg_name,
                                        dong_name, latitude, longitude)
                SELECT CAST(complex_no AS VARCHAR), CAST(complex_name AS VARCHAR),
                       CAST(sido_name AS VARCHAR), CAST(sgg_name AS VARCHAR),
                       CAST(dong_name AS VARCHAR),
                       CAST(latitude AS DOUBLE PRECISION), CAST(longitude AS DOUBLE PRECISION)
                FROM nv_complex_staging
                ON CONFLICT (complex_no) DO UPDATE SET
                    complex_name = EXCLUDED.complex_name,
                    sido_name = EXCLUDED.sido_name,
                    sgg_name = EXCLUDED.sgg_name,
                    dong_name = EXCLUDED.dong_name,
                    latitude = EXCLUDED.latitude,
                    longitude = EXCLUDED.longitude;
            """))
            conn.execute(text("DROP TABLE IF EXISTS nv_complex_staging;"))
            total_complex += len(chunk)
    results["complex"] = total_complex
    print(f"  nv_complex: {total_complex}건")

    # nv_listing UPSERT
    if not df_listing.empty:
        df_listing = df_listing.drop_duplicates(subset=["article_no"], keep="last")
        for col in ["confirm_date", "first_seen_date", "last_seen_date"]:
            if col in df_listing.columns:
                df_listing[col] = pd.to_datetime(df_listing[col], errors="coerce")

        total_listing = 0
        with engine.begin() as conn:
            for i in range(0, len(df_listing), chunk_size):
                chunk = df_listing.iloc[i:i + chunk_size]
                chunk.to_sql("nv_listing_staging", conn, if_exists="replace", index=False)
                conn.execute(text("""
                    INSERT INTO nv_listing (
                        article_no, complex_no, trade_type, exclusive_area,
                        initial_price, current_price, rent_price, floor_info,
                        direction, confirm_date, first_seen_date, last_seen_date, is_active
                    )
                    SELECT CAST(article_no AS VARCHAR), CAST(complex_no AS VARCHAR),
                           CAST(trade_type AS VARCHAR), CAST(exclusive_area AS INTEGER),
                           CAST(initial_price AS INTEGER), CAST(current_price AS INTEGER),
                           CAST(rent_price AS INTEGER), CAST(floor_info AS VARCHAR),
                           CAST(direction AS VARCHAR), CAST(confirm_date AS DATE),
                           CAST(first_seen_date AS DATE), CAST(last_seen_date AS DATE),
                           CAST(is_active AS BOOLEAN)
                    FROM nv_listing_staging
                    ON CONFLICT (article_no) DO UPDATE SET
                        current_price = EXCLUDED.current_price,
                        rent_price = EXCLUDED.rent_price,
                        last_seen_date = EXCLUDED.last_seen_date,
                        is_active = EXCLUDED.is_active;
                """))
                conn.execute(text("DROP TABLE IF EXISTS nv_listing_staging;"))
                total_listing += len(chunk)
        results["listing"] = total_listing
        print(f"  nv_listing: {total_listing}건")
    else:
        results["listing"] = 0

    return results


# ==============================================================================
# Step 7: 디스크 정리
# ==============================================================================

def cleanup_old_files() -> None:
    print("\n[Step 7] 디스크 정리")
    import glob
    today = get_today_str()
    patterns = ["naver_complex_*.csv", "naver_listing_*.csv", "checkpoint_listing_*.json"]
    removed = 0
    for pattern in patterns:
        for f in glob.glob(os.path.join(DATA_DIR, pattern)):
            if today not in os.path.basename(f):
                os.remove(f)
                removed += 1
    print(f"  {removed}개 파일 삭제" if removed else "  정리할 파일 없음")


# ==============================================================================
# 메인
# ==============================================================================

def main(skip_db: bool = False, test_mode: bool = False, resume: bool = False) -> None:
    print("=" * 60)
    print("  네이버 매물 초기 수집 [FULL]")
    print("=" * 60)

    dong_list, _ = get_cortars()
    if not dong_list:
        print("지역코드 수집 실패.")
        return

    complexes = get_active_complexes(dong_list, test_mode=test_mode)
    if not complexes:
        print("단지 수집 실패.")
        return

    complexes = convert_to_admin_dong(complexes)
    df_complex = pd.DataFrame(complexes.values())

    df_listing, _stats = collect_listings_incremental(complexes, test_mode, resume)
    save_results_csv(df_complex, df_listing)

    if not skip_db:
        try:
            save_to_db(df_complex, df_listing)
        except Exception as e:
            print(f"\n  DB 저장 실패: {e}")

    cleanup_old_files()

    print("\n" + "=" * 60)
    print("  수집 완료!")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="네이버 매물 초기 수집 (일일 증분은 pipeline.update_nv_daily, 매핑은 pipeline.build_mapping)"
    )
    parser.add_argument("--skip-db", action="store_true")
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    main(args.skip_db, args.test, args.resume)

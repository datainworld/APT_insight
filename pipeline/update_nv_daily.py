"""일일 네이버 매물 갱신 (교재 18장).

`diff_listings` 순수함수로 {new, changed, kept, closed} 분류 + 생명주기 필드 관리:
- 신규: `first_seen_date`·`initial_price` 설정
- 가격변경: `current_price` 갱신, `first_seen_date`·`initial_price` 불변
- 유지: `last_seen_date` 갱신
- 종료: `is_active=False` (삭제 아님)

수집 대상: A1(매매) + B1(전세) + B2(월세) 모두 (`collect_naver._collect_one_complex` 기본값).
MIN_DELAY 0.8 → 0.5 조정 (교재 18장 운영 수집용).

사용법:
    python -m pipeline.update_nv_daily
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from sqlalchemy.engine import Engine

from pipeline.collect_naver import (
    MAX_WORKERS,
    _collect_one_complex,
    get_active_complexes,
    get_cortars,
    save_to_db,
    sync_complexes,
)
from pipeline.naver_session import set_min_delay
from pipeline.utils import now_kst
from shared.db import get_engine


def diff_listings(
    yesterday_dict: dict[str, dict],
    today_list: list[dict],
    today_str: str,
) -> tuple[list[dict], dict[str, int]]:
    """어제 활성 매물과 오늘 수집을 비교해 레코드 + {new, changed, kept, closed} 통계 반환.

    순수함수 — DB/IO/외부 API 없음. 생명주기 규칙은 모듈 docstring 참조.
    """
    counts = {"new": 0, "changed": 0, "kept": 0, "closed": 0}
    result: list[dict] = []
    seen: set[str] = set()

    for row in today_list:
        ano = str(row["article_no"])
        seen.add(ano)
        new_row = dict(row)

        if ano in yesterday_dict:
            prev = yesterday_dict[ano]
            new_row["first_seen_date"] = prev.get("first_seen_date") or today_str
            new_row["initial_price"] = (
                prev.get("initial_price") if prev.get("initial_price") is not None
                else row["current_price"]
            )
            new_row["last_seen_date"] = today_str
            new_row["is_active"] = True
            if row["current_price"] != prev.get("current_price"):
                counts["changed"] += 1
            else:
                counts["kept"] += 1
        else:
            new_row["first_seen_date"] = today_str
            new_row["last_seen_date"] = today_str
            new_row["initial_price"] = row["current_price"]
            new_row["is_active"] = True
            counts["new"] += 1

        result.append(new_row)

    for ano, prev in yesterday_dict.items():
        if ano not in seen:
            closed = dict(prev)
            closed["is_active"] = False
            closed["last_seen_date"] = today_str
            counts["closed"] += 1
            result.append(closed)

    return result, counts


def load_yesterday_active(engine: Engine) -> dict[str, dict]:
    """DB에서 is_active=TRUE 매물을 article_no 키 dict로 반환."""
    with engine.connect() as conn:
        df = pd.read_sql(
            "SELECT article_no, complex_no, trade_type, exclusive_area, "
            "initial_price, current_price, rent_price, floor_info, direction, "
            "confirm_date, first_seen_date, last_seen_date, is_active "
            "FROM nv_listing WHERE is_active = TRUE",
            conn,
        )
    return {str(r["article_no"]): r.to_dict() for _, r in df.iterrows()}


def _collect_raw_today(complexes: dict) -> list[dict]:
    """단지별 매물을 병렬 수집 (A1+B1+B2). 생명주기 필드는 `_collect_one_complex` 기본값."""
    today_date = now_kst().strftime("%Y-%m-%d")
    total = len(complexes)
    results: list[dict] = []
    done = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(_collect_one_complex, cno, today_date): cno
            for cno in complexes.keys()
        }
        for future in as_completed(futures):
            try:
                _, arts = future.result()
                results.extend(arts)
            except Exception as e:
                print(f"  수집 오류: {e}")
            done += 1
            if done % 500 == 0 or done == total:
                print(f"  수집 진행 {done}/{total}")
    return results


def main(sample: int | None = None) -> dict:
    print("=" * 60)
    print("  [네이버] 일일 매물 갱신 (교재 18장)")
    if sample:
        print(f"  [SAMPLE 모드] 단지 {sample}개만 수집 (개발 검증용)")
    print("=" * 60)

    set_min_delay(0.5)
    engine = get_engine()

    # 1. 지역 → 오늘 단지 목록
    dong_list, _ = get_cortars()
    today_complexes = get_active_complexes(dong_list)
    if not today_complexes:
        return {"status": "error", "message": "단지 수집 실패"}

    # 2. DB의 기존 단지와 병합 (신규만 행정동 변환)
    with engine.connect() as conn:
        df_existing = pd.read_sql("SELECT * FROM nv_complex", conn)
    all_complexes, df_complex, _ = sync_complexes(today_complexes, df_existing)

    if sample:
        all_complexes = dict(list(all_complexes.items())[:sample])
        df_complex = df_complex[df_complex["complex_no"].astype(str).isin(all_complexes.keys())].copy()
        print(f"  샘플 단지 {len(all_complexes)}개로 제한")

    # 3. 어제 활성 매물
    yesterday = load_yesterday_active(engine)
    if sample:
        # 샘플 단지 밖 매물이 closed로 오판되는 것을 방지
        yesterday = {
            k: v for k, v in yesterday.items()
            if str(v.get("complex_no")) in all_complexes
        }
    print(f"\n  어제 활성 매물: {len(yesterday):,}건")

    # 4. 오늘 매물 수집 (A1+B1+B2)
    print("\n[수집] 단지별 매물")
    today_list = _collect_raw_today(all_complexes)
    print(f"  오늘 수집: {len(today_list):,}건")

    # 5. 순수함수 diff
    today_str = now_kst().strftime("%Y-%m-%d")
    records, stats = diff_listings(yesterday, today_list, today_str)
    print(f"\n[diff] 신규 {stats['new']:,} / 가격변경 {stats['changed']:,} / "
          f"유지 {stats['kept']:,} / 종료 {stats['closed']:,}")

    # 6. UPSERT (nv_complex → nv_listing 순서, FK 안전)
    df_listing = pd.DataFrame(records)
    save_to_db(df_complex, df_listing)

    result = {"status": "success", **stats}
    print(f"\n완료: {result}")
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="일일 네이버 매물 갱신 (교재 18장)")
    parser.add_argument("--sample", type=int, default=None,
                        help="단지 개수 제한 (Local 검증용)")
    args = parser.parse_args()
    main(sample=args.sample)

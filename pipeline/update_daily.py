"""일일 증분 갱신 + DB 마이그레이션 스크립트.

사용법:
    python -m pipeline.update_daily                  # 전체 실행
    python -m pipeline.update_daily --skip-update    # 수집 건너뛰기 (DB만)
    python -m pipeline.update_daily --skip-db        # DB 건너뛰기
    python -m pipeline.update_daily --skip-cleanup   # 파일 정리 건너뛰기
"""

import argparse
import os
import glob
import datetime

import pandas as pd
from dateutil.relativedelta import relativedelta
from sqlalchemy import text
from concurrent.futures import ThreadPoolExecutor, as_completed

from shared.db import get_engine
from pipeline.utils import (
    get_kakao_coords, build_address,
    get_today_str, get_latest_file, DATA_DIR,
)
from pipeline.collect_rt import LAWD_CODES, _collect_paginated


# ==============================================================================
# 스키마 변환 (원본 API → 가공)
# ==============================================================================

def _parse_money(x) -> float:
    try:
        return float(str(x).replace(",", ""))
    except (ValueError, TypeError):
        return 0.0


def convert_to_trade_schema(raw_data: list[dict] | pd.DataFrame) -> pd.DataFrame:
    """원본 매매 데이터 → rt_trade 스키마."""
    df = pd.DataFrame(raw_data) if isinstance(raw_data, list) else raw_data.copy()
    if df.empty:
        return pd.DataFrame()

    if "excluUseAr" in df.columns:
        df["excluUseAr"] = pd.to_numeric(df["excluUseAr"], errors="coerce").fillna(0).astype(int)
        df = df[df["excluUseAr"] > 0]

    df["deal_date"] = pd.to_datetime(
        df["dealYear"].astype(str) + "-" +
        df["dealMonth"].astype(str).str.zfill(2) + "-" +
        df["dealDay"].astype(str).str.zfill(2),
        errors="coerce",
    )

    df.rename(columns={
        "aptSeq": "apt_id", "aptNm": "apartment_name", "dealAmount": "deal_amount",
        "excluUseAr": "exclusive_area", "floor": "floor", "buyerGbn": "buyer_type",
        "slerGbn": "seller_type", "dealingGbn": "dealing_type",
        "cdealType": "cancellation_deal_type", "cdealDay": "cancellation_deal_day",
        "rgstDate": "registration_date",
    }, inplace=True)

    df["deal_amount"] = df["deal_amount"].apply(_parse_money)

    cols = ["apt_id", "apartment_name", "deal_date", "deal_amount", "exclusive_area",
            "floor", "buyer_type", "seller_type", "dealing_type",
            "cancellation_deal_type", "cancellation_deal_day", "registration_date"]
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df[cols]


def convert_to_rent_schema(raw_data: list[dict] | pd.DataFrame) -> pd.DataFrame:
    """원본 전월세 데이터 → rt_rent 스키마."""
    df = pd.DataFrame(raw_data) if isinstance(raw_data, list) else raw_data.copy()
    if df.empty:
        return pd.DataFrame()

    if "excluUseAr" in df.columns:
        df["excluUseAr"] = pd.to_numeric(df["excluUseAr"], errors="coerce").fillna(0).astype(int)
        df = df[df["excluUseAr"] > 0]

    df["deal_date"] = pd.to_datetime(
        df["dealYear"].astype(str) + "-" +
        df["dealMonth"].astype(str).str.zfill(2) + "-" +
        df["dealDay"].astype(str).str.zfill(2),
        errors="coerce",
    )

    df.rename(columns={
        "aptSeq": "apt_id", "aptNm": "apartment_name", "deposit": "deposit",
        "monthlyRent": "monthly_rent", "excluUseAr": "exclusive_area",
        "floor": "floor", "contractTerm": "contract_term", "contractType": "contract_type",
    }, inplace=True)

    df["deposit"] = df["deposit"].apply(_parse_money)
    df["monthly_rent"] = df["monthly_rent"].apply(_parse_money)

    cols = ["apt_id", "apartment_name", "deal_date", "deposit", "monthly_rent",
            "exclusive_area", "floor", "contract_term", "contract_type"]
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df[cols]


# ==============================================================================
# Step 1: 매매/전월세 증분 수집
# ==============================================================================

def step_1_update_trade_rent() -> tuple[int, int, list, list]:
    """최근 3개월 매매/전월세를 증분 수집하고 36개월 마스터와 병합한다.

    Returns:
        (매매 건수, 전월세 건수, 원본 매매 리스트, 원본 전월세 리스트)
    """
    print(">>> Step 1: 매매/전월세 증분 수집")

    trade_url = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
    rent_url = "https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent"

    today = datetime.datetime.now()
    target_months = [(today - relativedelta(months=i)).strftime("%Y%m") for i in range(3)]
    print(f"  대상 월: {target_months}")

    all_trades, all_rents = [], []
    count, total = 0, len(LAWD_CODES) * len(target_months)

    for lawd in LAWD_CODES:
        for ym in target_months:
            count += 1
            if count % 10 == 0:
                print(f"  진행 {count}/{total}")

            trades = _collect_paginated(trade_url, {"LAWD_CD": lawd, "DEAL_YMD": ym})
            for t in trades:
                t["LAWD_CD"] = lawd
                t["DEAL_YMD"] = ym
            all_trades.extend(trades)

            import time
            time.sleep(1.0)

            rents = _collect_paginated(rent_url, {"LAWD_CD": lawd, "DEAL_YMD": ym})
            for r in rents:
                r["LAWD_CD"] = lawd
                r["DEAL_YMD"] = ym
            all_rents.extend(rents)

            time.sleep(1.0)

    # 스키마 변환
    df_new_t = convert_to_trade_schema(all_trades)
    df_new_r = convert_to_rent_schema(all_rents)
    print(f"  가공: 매매 {len(df_new_t)}건, 전월세 {len(df_new_r)}건")

    # 기존 마스터와 병합
    cutoff_date = pd.to_datetime((today - relativedelta(months=36)).strftime("%Y-%m-%d"))

    def _merge(df_master: pd.DataFrame, df_new: pd.DataFrame) -> pd.DataFrame:
        if df_master.empty and df_new.empty:
            return pd.DataFrame()
        if not df_master.empty:
            df_master["deal_date"] = pd.to_datetime(df_master["deal_date"], errors="coerce")
            df_master = df_master[df_master["deal_date"] >= cutoff_date]
        if df_new.empty:
            return df_master
        df_new["deal_date"] = pd.to_datetime(df_new["deal_date"], errors="coerce")
        collected_months = set(df_new["deal_date"].dt.strftime("%Y%m").dropna())
        if not df_master.empty:
            df_master = df_master[
                ~df_master["deal_date"].dt.strftime("%Y%m").isin(collected_months)
            ]
        return pd.concat([df_master, df_new], ignore_index=True)

    t_master = get_latest_file("apt_trade_master_*.csv")
    df_master_t = pd.read_csv(t_master, low_memory=False) if t_master else pd.DataFrame()

    r_master = get_latest_file("apt_rent_master_*.csv")
    df_master_r = pd.read_csv(r_master, low_memory=False) if r_master else pd.DataFrame()

    df_final_t = _merge(df_master_t, df_new_t)
    df_final_r = _merge(df_master_r, df_new_r)

    today_str = get_today_str()
    df_final_t.to_csv(
        os.path.join(DATA_DIR, f"apt_trade_master_{today_str}.csv"),
        index=False, encoding="utf-8-sig",
    )
    df_final_r.to_csv(
        os.path.join(DATA_DIR, f"apt_rent_master_{today_str}.csv"),
        index=False, encoding="utf-8-sig",
    )

    return len(df_final_t), len(df_final_r), all_trades, all_rents


# ==============================================================================
# Step 2: 신규 apt_id 감지 → rt_complex 추가
# ==============================================================================

def step_2_update_basic_from_trades(raw_trades: list, raw_rents: list) -> int:
    """거래 데이터에서 신규 apt_id를 감지하고 지오코딩하여 기본 정보에 추가한다."""
    print(">>> Step 2: 신규 apt_id 감지")

    df_all = pd.concat(
        [pd.DataFrame(raw_trades), pd.DataFrame(raw_rents)], ignore_index=True
    )
    if df_all.empty or "aptSeq" not in df_all.columns:
        print("  원본 데이터 없음")
        return 0

    raw_ids = set(df_all["aptSeq"].dropna().astype(str).unique())

    kb_master = get_latest_file("apt_basic_info_master_*.csv")
    if kb_master:
        df_kb = pd.read_csv(kb_master)
        existing_ids = set(df_kb["apt_id"].dropna().astype(str).unique())
    else:
        df_kb = pd.DataFrame()
        existing_ids = set()

    new_ids = raw_ids - existing_ids
    if not new_ids:
        print("  신규 없음")
        return 0

    print(f"  신규 {len(new_ids)}건 발견, 지오코딩 중...")

    df_new = df_all[df_all["aptSeq"].astype(str).isin(new_ids)].drop_duplicates(
        subset=["aptSeq"], keep="first"
    )

    results = []
    with ThreadPoolExecutor(max_workers=20) as executor:
        future_to_row = {
            executor.submit(get_kakao_coords, build_address(row)): row
            for _, row in df_new.iterrows()
        }
        for future in as_completed(future_to_row):
            row = future_to_row[future]
            try:
                lat, lon, admin = future.result()
            except Exception:
                lat, lon, admin = None, None, None

            build_year = ""
            if pd.notna(row.get("buildYear")):
                try:
                    build_year = int(float(str(row["buildYear"])))
                except (ValueError, TypeError):
                    build_year = ""

            sgg = str(row.get("sggNm", "")) if pd.notna(row.get("sggNm")) else ""
            umd = str(row.get("umdNm", "")) if pd.notna(row.get("umdNm")) else ""
            jibun = str(row.get("jibun", "")) if pd.notna(row.get("jibun")) else ""

            results.append({
                "apt_id": str(row["aptSeq"]),
                "apt_name": row.get("aptNm", ""),
                "build_year": build_year,
                "road_address": build_address(row),
                "jibun_address": f"{sgg} {umd} {jibun}".strip(),
                "latitude": lat,
                "longitude": lon,
                "admin_dong": admin,
            })

    df_kb = pd.concat([df_kb, pd.DataFrame(results)], ignore_index=True)
    df_kb.drop_duplicates(subset=["apt_id"], keep="last", inplace=True)

    out = os.path.join(DATA_DIR, f"apt_basic_info_master_{get_today_str()}.csv")
    df_kb.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"  저장: {out} ({len(df_kb)}건, 신규 {len(new_ids)}건)")
    return len(new_ids)


# ==============================================================================
# Step 3: DB 마이그레이션 (TRUNCATE + INSERT)
# ==============================================================================

def run_migration() -> dict:
    """CSV 마스터 파일을 DB에 적재한다 (TRUNCATE + INSERT)."""
    print("\n=== DB 마이그레이션 ===")
    engine = get_engine()
    results = {}

    # rt_complex
    file_basic = get_latest_file("apt_basic_info_master_*.csv")
    if file_basic:
        df = pd.read_csv(file_basic)
        cols = ["apt_id", "apt_name", "build_year", "road_address",
                "jibun_address", "latitude", "longitude", "admin_dong"]
        avail = [c for c in cols if c in df.columns]
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE rt_complex CASCADE;"))
            df[avail].to_sql("rt_complex", conn, if_exists="append", index=False, chunksize=5000)
        results["rt_complex"] = len(df)
        print(f"  rt_complex: {len(df)}건")

    # rt_trade
    file_trade = get_latest_file("apt_trade_master_*.csv")
    if file_trade:
        cols = ["apt_id", "apartment_name", "deal_date", "deal_amount", "exclusive_area",
                "floor", "buyer_type", "seller_type", "dealing_type",
                "cancellation_deal_type", "cancellation_deal_day", "registration_date"]
        count = 0
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE rt_trade;"))
            for chunk in pd.read_csv(file_trade, chunksize=50000, low_memory=False):
                chunk["deal_date"] = pd.to_datetime(chunk.get("deal_date"), errors="coerce")
                avail = [c for c in cols if c in chunk.columns]
                chunk[avail].to_sql("rt_trade", conn, if_exists="append", index=False)
                count += len(chunk)
                print(".", end="", flush=True)
        print(f" rt_trade: {count}건")
        results["rt_trade"] = count

    # rt_rent
    file_rent = get_latest_file("apt_rent_master_*.csv")
    if file_rent:
        cols = ["apt_id", "apartment_name", "deal_date", "deposit", "monthly_rent",
                "exclusive_area", "floor", "contract_term", "contract_type"]
        count = 0
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE rt_rent;"))
            for chunk in pd.read_csv(file_rent, chunksize=50000, low_memory=False):
                chunk["deal_date"] = pd.to_datetime(chunk.get("deal_date"), errors="coerce")
                avail = [c for c in cols if c in chunk.columns]
                chunk[avail].to_sql("rt_rent", conn, if_exists="append", index=False)
                count += len(chunk)
                print(".", end="", flush=True)
        print(f" rt_rent: {count}건")
        results["rt_rent"] = count

    print("=== 마이그레이션 완료 ===")
    return results


# ==============================================================================
# Step 4: 파일 정리
# ==============================================================================

def cleanup_old_files() -> list[str]:
    """이전 버전 마스터 및 원본 파일을 삭제한다."""
    print("\n>>> 파일 정리")
    deleted = []
    today_str = get_today_str()

    patterns = [
        "apt_basic_info_master_*.csv",
        "apt_trade_master_*.csv",
        "apt_rent_master_*.csv",
    ]
    for pattern in patterns:
        for f in glob.glob(os.path.join(DATA_DIR, pattern)):
            if today_str not in f:
                os.remove(f)
                deleted.append(f)

    # 원본 raw 파일 (master가 아닌 것)
    for pattern in ["apt_trade_2*.csv", "apt_rent_2*.csv"]:
        for f in glob.glob(os.path.join(DATA_DIR, pattern)):
            if "master" not in f:
                os.remove(f)
                deleted.append(f)

    print(f"  {len(deleted)}개 파일 삭제" if deleted else "  정리할 파일 없음")
    return deleted


# ==============================================================================
# 메인
# ==============================================================================

def main(skip_update: bool = False, skip_db: bool = False,
         skip_cleanup: bool = False) -> None:
    print("=" * 60)
    print("  일일 업데이트 + DB 마이그레이션")
    print("=" * 60)

    if not skip_update:
        t_count, r_count, raw_trades, raw_rents = step_1_update_trade_rent()
        step_2_update_basic_from_trades(raw_trades, raw_rents)
        print(f"\n  매매: {t_count}건, 전월세: {r_count}건")
    else:
        print(">>> 데이터 수집 건너뜀")

    if not skip_db:
        run_migration()
        # complex_mapping 갱신
        print("\n>>> complex_mapping 갱신")
        try:
            from pipeline.collect_naver import run_mapping
            run_mapping()
        except Exception as e:
            print(f"  매핑 실패 (무시): {e}")
    else:
        print(">>> DB 마이그레이션 건너뜀")

    if not skip_cleanup:
        cleanup_old_files()

    print("\n완료!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="일일 업데이트 + DB 마이그레이션")
    parser.add_argument("--skip-update", action="store_true")
    parser.add_argument("--skip-db", action="store_true")
    parser.add_argument("--skip-cleanup", action="store_true")
    args = parser.parse_args()
    main(args.skip_update, args.skip_db, args.skip_cleanup)

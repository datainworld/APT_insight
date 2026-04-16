"""국토부 실거래가 수집·가공 스크립트.

사용법:
    python -m pipeline.collect_rt --months 36
    python -m pipeline.collect_rt --skip-trade   # 매매/전월세 수집 건너뛰기
"""

import argparse
import os
import time

import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from dateutil.relativedelta import relativedelta
from datetime import datetime

from pipeline.utils import (
    fetch_data, parse_api_items, get_kakao_coords, build_address,
    save_to_csv, get_today_str, DATA_DIR,
)


# ==============================================================================
# 상수: 수도권 LAWD_CD (5자리 지역코드)
# ==============================================================================

# fmt: off
LAWD_CODES = [
    # 서울 (25구)
    "11110", "11140", "11170", "11200", "11215", "11230", "11260", "11290",
    "11305", "11320", "11350", "11380", "11410", "11440", "11470", "11500",
    "11530", "11545", "11560", "11590", "11620", "11650", "11680", "11710", "11740",
    # 인천 (10구군)
    "28110", "28140", "28177", "28185", "28200", "28237", "28245", "28260", "28710",
    # 경기 (44시군)
    "41111", "41113", "41115", "41117", "41131", "41133", "41135", "41150",
    "41171", "41173", "41192", "41194", "41196", "41210", "41220", "41250",
    "41271", "41273", "41281", "41285", "41287", "41290", "41310", "41360",
    "41370", "41390", "41410", "41430", "41450", "41461", "41463", "41465",
    "41480", "41500", "41550", "41570", "41590", "41593", "41595", "41597",
    "41610", "41630", "41650", "41670",
]
# fmt: on


# ==============================================================================
# 수집: 매매/전월세 거래
# ==============================================================================

def _get_month_list(months_back: int = 36) -> list[str]:
    """현재로부터 months_back 개월치 YYYYMM 목록을 반환한다."""
    today = datetime.now()
    return sorted(
        (today - relativedelta(months=i)).strftime("%Y%m")
        for i in range(months_back + 1)
    )


def _collect_paginated(url: str, params: dict) -> list[dict]:
    """페이지네이션을 처리하여 모든 아이템을 수집한다."""
    all_items = []
    params = {**params, "numOfRows": 1000, "pageNo": 1}

    while True:
        data = fetch_data(url, params)
        items = parse_api_items(data)
        if not items:
            break
        all_items.extend(items)
        if len(items) < 1000:
            break
        params["pageNo"] += 1

    return all_items


def collect_all_trade_rent(months_back: int = 36) -> tuple[str, str]:
    """모든 지역 × 월에 대해 매매/전월세 데이터를 수집한다."""
    trade_url = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
    rent_url = "https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent"

    month_list = _get_month_list(months_back)
    total = len(LAWD_CODES) * len(month_list)
    print(f"수집 대상: {len(LAWD_CODES)}개 지역 × {len(month_list)}개월 = {total}건")

    all_trades, all_rents = [], []
    count = 0

    for lawd in LAWD_CODES:
        for ym in month_list:
            count += 1
            if count % 10 == 0:
                print(f"진행 {count}/{total} (지역: {lawd}, 월: {ym})")

            trades = _collect_paginated(trade_url, {"LAWD_CD": lawd, "DEAL_YMD": ym})
            for t in trades:
                t["LAWD_CD"] = lawd
                t["DEAL_YMD"] = ym
            all_trades.extend(trades)

            rents = _collect_paginated(rent_url, {"LAWD_CD": lawd, "DEAL_YMD": ym})
            for r in rents:
                r["LAWD_CD"] = lawd
                r["DEAL_YMD"] = ym
            all_rents.extend(rents)

            time.sleep(0.1)

    today_str = get_today_str()
    save_to_csv(all_trades, f"apt_trade_{today_str}.csv")
    save_to_csv(all_rents, f"apt_rent_{today_str}.csv")

    return (
        os.path.join(DATA_DIR, f"apt_trade_{today_str}.csv"),
        os.path.join(DATA_DIR, f"apt_rent_{today_str}.csv"),
    )


# ==============================================================================
# 3. 가공: 기본 정보 (rt_complex)
# ==============================================================================

def process_basic_info(trade_file: str, rent_file: str | None = None) -> pd.DataFrame | None:
    """매매/전월세 원본에서 고유 아파트를 추출하고 지오코딩한다."""
    print("--- 기본 정보 가공 (지오코딩) ---")

    if not os.path.exists(trade_file):
        print(f"매매 파일 없음: {trade_file}")
        return None

    cols = ["aptSeq", "aptNm", "buildYear", "jibun", "roadNm",
            "roadNmBonbun", "roadNmBubun", "umdNm", "sggNm"]

    df_trade = pd.read_csv(trade_file, dtype={"aptSeq": str}, low_memory=False)
    avail = [c for c in cols if c in df_trade.columns]
    df_combined = df_trade[avail].drop_duplicates(subset=["aptSeq"])

    if rent_file and os.path.exists(rent_file):
        df_rent = pd.read_csv(rent_file, dtype={"aptSeq": str}, low_memory=False)
        avail_r = [c for c in cols if c in df_rent.columns]
        df_combined = pd.concat(
            [df_combined, df_rent[avail_r].drop_duplicates(subset=["aptSeq"])]
        ).drop_duplicates(subset=["aptSeq"])

    # 이어받기
    out_file = os.path.join(DATA_DIR, f"apt_basic_info_master_{get_today_str()}.csv")
    processed_ids: set[str] = set()
    all_results: list[dict] = []

    if os.path.exists(out_file):
        df_exist = pd.read_csv(out_file, dtype={"apt_id": str})
        processed_ids = set(df_exist["apt_id"].unique())
        all_results = df_exist.to_dict("records")
        print(f"이어받기: {len(processed_ids)}건 처리 완료")

    df_todo = df_combined[~df_combined["aptSeq"].isin(processed_ids)]
    print(f"남은 가공 대상: {len(df_todo)}건")

    if len(df_todo) > 0:
        df_todo = df_todo.copy()
        df_todo["search_addr"] = df_todo.apply(build_address, axis=1)

        print("지오코딩 시작 (20 threads)...")
        with ThreadPoolExecutor(max_workers=20) as executor:
            future_to_row = {
                executor.submit(get_kakao_coords, row["search_addr"]): row
                for _, row in df_todo.iterrows()
            }
            completed = 0
            for future in as_completed(future_to_row):
                row = future_to_row[future]
                try:
                    lat, lon, admin = future.result()
                except Exception:
                    lat, lon, admin = None, None, None

                all_results.append({
                    "apt_id": row["aptSeq"],
                    "apt_name": row.get("aptNm"),
                    "build_year": row.get("buildYear"),
                    "road_address": row.get("search_addr"),
                    "jibun_address": f"{row.get('umdNm', '')} {row.get('jibun', '')}".strip(),
                    "latitude": lat,
                    "longitude": lon,
                    "admin_dong": admin,
                })

                completed += 1
                if completed % 100 == 0:
                    print(f"지오코딩 {completed}/{len(df_todo)}...")
                    pd.DataFrame(all_results).to_csv(out_file, index=False, encoding="utf-8-sig")

    df_basic = pd.DataFrame(all_results)
    df_basic.to_csv(out_file, index=False, encoding="utf-8-sig")
    print(f"저장: {out_file} ({len(df_basic)}건)")
    return df_basic


# ==============================================================================
# 4. 가공: 매매/전월세 (rt_trade, rt_rent)
# ==============================================================================

def _parse_money(x) -> float:
    try:
        return float(str(x).replace(",", ""))
    except (ValueError, TypeError):
        return 0.0


def process_trade_rent(trade_file: str, rent_file: str | None = None) -> None:
    """매매/전월세 원본 데이터를 가공하여 master CSV를 생성한다."""
    print("--- 매매/전월세 가공 ---")
    today_str = get_today_str()

    # 매매
    if os.path.exists(trade_file):
        df = pd.read_csv(trade_file, low_memory=False)

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

        t_cols = ["apt_id", "apartment_name", "deal_date", "deal_amount", "exclusive_area",
                  "floor", "buyer_type", "seller_type", "dealing_type",
                  "cancellation_deal_type", "cancellation_deal_day", "registration_date"]
        for c in t_cols:
            if c not in df.columns:
                df[c] = None
        out = os.path.join(DATA_DIR, f"apt_trade_master_{today_str}.csv")
        df[t_cols].to_csv(out, index=False, encoding="utf-8-sig")
        print(f"저장: {out}")

    # 전월세
    if rent_file and os.path.exists(rent_file):
        df = pd.read_csv(rent_file, low_memory=False)

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

        r_cols = ["apt_id", "apartment_name", "deal_date", "deposit", "monthly_rent",
                  "exclusive_area", "floor", "contract_term", "contract_type"]
        for c in r_cols:
            if c not in df.columns:
                df[c] = None
        out = os.path.join(DATA_DIR, f"apt_rent_master_{today_str}.csv")
        df[r_cols].to_csv(out, index=False, encoding="utf-8-sig")
        print(f"저장: {out}")

    print("매매/전월세 가공 완료.")


# ==============================================================================
# 메인
# ==============================================================================

def main(months_back: int = 36, skip_trade: bool = False) -> None:
    """전체 수집·가공 파이프라인을 실행한다."""
    print("=" * 60)
    print(f"국토부 실거래가 수집 (기간: {months_back}개월)")
    print("=" * 60)

    today_str = get_today_str()
    trade_file = os.path.join(DATA_DIR, f"apt_trade_{today_str}.csv")
    rent_file = os.path.join(DATA_DIR, f"apt_rent_{today_str}.csv")

    # Step 1: 매매/전월세
    if not skip_trade:
        print("\n[Step 1/2] 매매/전월세 수집")
        trade_file, rent_file = collect_all_trade_rent(months_back)
    else:
        print("\n[Step 1/2] 건너뜀")

    # Step 2: 가공
    print("\n[Step 2/2] 데이터 가공")
    process_basic_info(trade_file, rent_file)
    process_trade_rent(trade_file, rent_file)

    print("\n" + "=" * 60)
    print("수집·가공 완료!")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="국토부 실거래가 수집·가공")
    parser.add_argument("--months", type=int, default=36, help="수집 기간(개월)")
    parser.add_argument("--skip-trade", action="store_true", help="매매/전월세 수집 건너뛰기")
    args = parser.parse_args()
    main(args.months, args.skip_trade)

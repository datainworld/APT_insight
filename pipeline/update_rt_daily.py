"""일일 국토부 실거래가 갱신 (교재 17장).

최근 3개월 슬라이딩 윈도우 수집 → `ON CONFLICT DO NOTHING` 누적 적재
+ 36개월 초과 자동 삭제 (rolling window).

FK 순서: 신규 단지(rt_complex) 등록 → rt_trade → rt_rent → cleanup.

사용법:
    python -m pipeline.update_rt_daily
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from dateutil.relativedelta import relativedelta
from sqlalchemy import text
from sqlalchemy.engine import Engine

from pipeline.collect_rt import LAWD_CODES, _collect_paginated
from pipeline.schemas import (
    convert_to_rent_schema,
    convert_to_trade_schema,
    extract_complex_info,
)
from pipeline.utils import build_address, get_kakao_coords, now_kst
from shared.db import get_engine

TRADE_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
RENT_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent"


def get_recent_months(n: int = 3) -> list[str]:
    """오늘로부터 최근 n개월 YYYYMM 오름차순 리스트."""
    today = now_kst()
    return sorted((today - relativedelta(months=i)).strftime("%Y%m") for i in range(n))


def collect_recent_trades_rents() -> tuple[list[dict], list[dict]]:
    """최근 3개월 × 수도권 LAWD 매매·전월세 원본 raw 수집."""
    months = get_recent_months(3)
    total = len(LAWD_CODES) * len(months)
    print(f"수집: {len(LAWD_CODES)}개 지역 × {len(months)}개월 = {total}건 (월: {months})")

    all_trades, all_rents = [], []
    for count, lawd in enumerate(LAWD_CODES, 1):
        for ym in months:
            trades = _collect_paginated(TRADE_URL, {"LAWD_CD": lawd, "DEAL_YMD": ym})
            for t in trades:
                t["LAWD_CD"] = lawd
                t["DEAL_YMD"] = ym
            all_trades.extend(trades)
            time.sleep(0.3)

            rents = _collect_paginated(RENT_URL, {"LAWD_CD": lawd, "DEAL_YMD": ym})
            for r in rents:
                r["LAWD_CD"] = lawd
                r["DEAL_YMD"] = ym
            all_rents.extend(rents)
            time.sleep(0.3)

        if count % 10 == 0 or count == len(LAWD_CODES):
            print(f"  진행 {count}/{len(LAWD_CODES)} LAWD")

    print(f"  수집 완료: 매매 {len(all_trades)}건, 전월세 {len(all_rents)}건")
    return all_trades, all_rents


def _geocode_new_complex_rows(df_new: pd.DataFrame) -> pd.DataFrame:
    """신규 apt_id 행들을 병렬 지오코딩해 rt_complex 스키마 DataFrame으로 반환."""
    records = []
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

            by = row.get("buildYear")
            try:
                build_year = int(float(str(by))) if pd.notna(by) else None
            except (ValueError, TypeError):
                build_year = None

            sgg = str(row.get("sggNm", "") or "")
            umd = str(row.get("umdNm", "") or "")
            jibun = str(row.get("jibun", "") or "")

            records.append({
                "apt_id": str(row["aptSeq"]),
                "apt_name": str(row.get("aptNm", "") or ""),
                "build_year": build_year,
                "road_address": build_address(row),
                "jibun_address": f"{sgg} {umd} {jibun}".strip(),
                "latitude": lat,
                "longitude": lon,
                "admin_dong": admin,
            })
    return pd.DataFrame(records)


def upsert_new_complexes(raw_trades: list[dict], raw_rents: list[dict], engine: Engine) -> int:
    """신규 apt_id 감지 + 지오코딩 + rt_complex UPSERT (ON CONFLICT DO NOTHING). FK 순서상 최초 실행."""
    df = extract_complex_info(raw_trades, raw_rents)
    if df.empty:
        print("  신규 단지 없음 (원본 비어있음)")
        return 0

    collected_ids = set(df["aptSeq"].astype(str))
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT apt_id FROM rt_complex")).fetchall()
        existing_ids = {r[0] for r in rows}

    new_ids = collected_ids - existing_ids
    if not new_ids:
        print("  신규 단지 0건")
        return 0

    df_new = df[df["aptSeq"].astype(str).isin(new_ids)].copy()
    print(f"  신규 단지 {len(df_new)}건 → 지오코딩 + INSERT")

    df_out = _geocode_new_complex_rows(df_new)
    if df_out.empty:
        return 0

    with engine.begin() as conn:
        df_out.to_sql("rt_complex_staging", conn, if_exists="replace", index=False)
        conn.execute(text("""
            INSERT INTO rt_complex (apt_id, apt_name, build_year, road_address,
                                    jibun_address, latitude, longitude, admin_dong)
            SELECT apt_id, apt_name,
                   CAST(build_year AS INTEGER),
                   road_address, jibun_address,
                   CAST(latitude AS DOUBLE PRECISION),
                   CAST(longitude AS DOUBLE PRECISION),
                   admin_dong
            FROM rt_complex_staging
            ON CONFLICT (apt_id) DO NOTHING;
        """))
        conn.execute(text("DROP TABLE rt_complex_staging;"))

    return len(df_out)


def upsert_trades(raw_trades: list[dict], engine: Engine) -> int:
    """rt_trade 누적. 자연키 UNIQUE 제약으로 ON CONFLICT DO NOTHING."""
    df = convert_to_trade_schema(raw_trades)
    if df.empty:
        print("  매매 데이터 없음")
        return 0

    with engine.begin() as conn:
        before = conn.execute(text("SELECT COUNT(*) FROM rt_trade")).scalar() or 0
        df.to_sql("rt_trade_staging", conn, if_exists="replace", index=False)
        conn.execute(text("""
            INSERT INTO rt_trade (apt_id, apartment_name, deal_date, deal_amount,
                                   exclusive_area, floor, buyer_type, seller_type,
                                   dealing_type, cancellation_deal_type,
                                   cancellation_deal_day, registration_date)
            SELECT CAST(s.apt_id AS VARCHAR), CAST(s.apartment_name AS VARCHAR),
                   CAST(s.deal_date AS DATE),
                   CAST(s.deal_amount AS DOUBLE PRECISION),
                   CAST(s.exclusive_area AS DOUBLE PRECISION),
                   CAST(s.floor AS INTEGER),
                   CAST(s.buyer_type AS VARCHAR), CAST(s.seller_type AS VARCHAR),
                   CAST(s.dealing_type AS VARCHAR),
                   CAST(s.cancellation_deal_type AS VARCHAR),
                   CAST(s.cancellation_deal_day AS VARCHAR),
                   CAST(s.registration_date AS VARCHAR)
            FROM rt_trade_staging s
            WHERE EXISTS (SELECT 1 FROM rt_complex c WHERE c.apt_id = s.apt_id)
            ON CONFLICT ON CONSTRAINT rt_trade_natural_uq DO NOTHING;
        """))
        conn.execute(text("DROP TABLE rt_trade_staging;"))
        after = conn.execute(text("SELECT COUNT(*) FROM rt_trade")).scalar() or 0

    return after - before


def upsert_rents(raw_rents: list[dict], engine: Engine) -> int:
    """rt_rent 누적. 자연키 UNIQUE 제약으로 ON CONFLICT DO NOTHING."""
    df = convert_to_rent_schema(raw_rents)
    if df.empty:
        print("  전월세 데이터 없음")
        return 0

    with engine.begin() as conn:
        before = conn.execute(text("SELECT COUNT(*) FROM rt_rent")).scalar() or 0
        df.to_sql("rt_rent_staging", conn, if_exists="replace", index=False)
        conn.execute(text("""
            INSERT INTO rt_rent (apt_id, apartment_name, deal_date, deposit,
                                  monthly_rent, exclusive_area, floor,
                                  contract_term, contract_type)
            SELECT CAST(s.apt_id AS VARCHAR), CAST(s.apartment_name AS VARCHAR),
                   CAST(s.deal_date AS DATE),
                   CAST(s.deposit AS DOUBLE PRECISION),
                   CAST(s.monthly_rent AS DOUBLE PRECISION),
                   CAST(s.exclusive_area AS DOUBLE PRECISION),
                   CAST(s.floor AS INTEGER),
                   CAST(s.contract_term AS VARCHAR),
                   CAST(s.contract_type AS VARCHAR)
            FROM rt_rent_staging s
            WHERE EXISTS (SELECT 1 FROM rt_complex c WHERE c.apt_id = s.apt_id)
            ON CONFLICT ON CONSTRAINT rt_rent_natural_uq DO NOTHING;
        """))
        conn.execute(text("DROP TABLE rt_rent_staging;"))
        after = conn.execute(text("SELECT COUNT(*) FROM rt_rent")).scalar() or 0

    return after - before


def cleanup_old_data(engine: Engine, months: int = 36) -> tuple[int, int]:
    """36개월 초과 rt_trade·rt_rent 삭제. rt_complex는 유지 (기본정보)."""
    with engine.begin() as conn:
        res_t = conn.execute(text(
            f"DELETE FROM rt_trade WHERE deal_date < CURRENT_DATE - INTERVAL '{months} months'"
        ))
        res_r = conn.execute(text(
            f"DELETE FROM rt_rent WHERE deal_date < CURRENT_DATE - INTERVAL '{months} months'"
        ))
    return res_t.rowcount, res_r.rowcount


def main() -> dict:
    print("=" * 60)
    print("  [국토부] 일일 슬라이딩 윈도우 갱신 (교재 17장)")
    print("=" * 60)

    engine = get_engine()
    raw_trades, raw_rents = collect_recent_trades_rents()

    print("\n[1/4] 신규 단지 등록 (FK 순서상 최초)")
    new_complexes = upsert_new_complexes(raw_trades, raw_rents, engine)

    print("\n[2/4] rt_trade 누적")
    new_trades = upsert_trades(raw_trades, engine)
    print(f"  추가 {new_trades:,}건")

    print("\n[3/4] rt_rent 누적")
    new_rents = upsert_rents(raw_rents, engine)
    print(f"  추가 {new_rents:,}건")

    print("\n[4/4] 36개월 초과 데이터 정리")
    deleted_trades, deleted_rents = cleanup_old_data(engine, months=36)
    print(f"  rt_trade 삭제 {deleted_trades:,}건, rt_rent 삭제 {deleted_rents:,}건")

    result = {
        "status": "success",
        "new_complexes": new_complexes,
        "new_trades": new_trades,
        "new_rents": new_rents,
        "deleted_trades": deleted_trades,
        "deleted_rents": deleted_rents,
    }
    print(f"\n완료: {result}")
    return result


if __name__ == "__main__":
    main()

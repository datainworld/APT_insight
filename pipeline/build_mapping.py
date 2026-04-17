"""rt_complex ↔ nv_complex 매핑 (교재 14장).

공간 필터(±0.005도) → Haversine 정밀 거리(300m 이내) → 이름 유사도(token_set_ratio)
2단계 스코어링으로 1:1 매핑. `complex_mapping` 테이블에 UPSERT.

사용법:
    python -m pipeline.build_mapping
"""

import re
import time

import pandas as pd
from haversine import haversine, Unit
from sqlalchemy import text
from thefuzz import fuzz

from shared.db import get_engine


def normalize_name(name) -> str:
    """단지명 정규화: 괄호 제거·공백 제거·공통 접미어 제거."""
    if pd.isna(name) or not name:
        return ""
    name = re.sub(r"\(.*?\)", "", str(name))
    name = re.sub(r"\s+", "", name)
    return name.replace("아파트", "").replace("마을", "").replace("단지", "")


def main() -> None:
    print("=" * 60)
    print("  단지 매핑 (apt_id ↔ complex_no)")
    print("=" * 60)

    engine = get_engine()

    print("[1] DB 로드...")
    try:
        with engine.connect() as conn:
            df_apt = pd.read_sql(
                "SELECT apt_id, apt_name, latitude, longitude FROM rt_complex", conn
            )
            df_naver = pd.read_sql(
                "SELECT complex_no, complex_name, latitude, longitude FROM nv_complex", conn
            )
    except Exception as e:
        print(f"DB 로드 실패: {e}")
        return

    print(f"  rt_complex: {len(df_apt)}건, nv_complex: {len(df_naver)}건")

    df_apt = df_apt.dropna(subset=["latitude", "longitude"]).copy()
    df_naver = df_naver.dropna(subset=["latitude", "longitude"]).copy()

    df_apt["clean_name"] = df_apt["apt_name"].apply(normalize_name)
    df_naver["clean_name"] = df_naver["complex_name"].apply(normalize_name)

    print("[2] 공간+텍스트 매핑...")
    mappings = []
    start_time = time.time()

    for count, (_, row_apt) in enumerate(df_apt.iterrows(), 1):
        lat_a, lon_a = row_apt["latitude"], row_apt["longitude"]

        candidates = df_naver[
            (df_naver["latitude"].between(lat_a - 0.005, lat_a + 0.005)) &
            (df_naver["longitude"].between(lon_a - 0.005, lon_a + 0.005))
        ]

        best_match, best_score, best_method = None, 0, ""

        for _, row_n in candidates.iterrows():
            dist_m = haversine(
                (lat_a, lon_a), (row_n["latitude"], row_n["longitude"]), unit=Unit.METERS
            )
            if dist_m > 300:
                continue

            sim = fuzz.token_set_ratio(row_apt["clean_name"], row_n["clean_name"])

            if dist_m < 50 and sim > 40:
                score = 100 - dist_m + sim
                if score > best_score:
                    best_score, best_match, best_method = score, row_n, "DISTANCE"

            elif sim >= 70 and dist_m <= 300:
                score = sim + (300 - dist_m) / 10
                if score > best_score:
                    best_score, best_match, best_method = score, row_n, "NAME_SIMILARITY"

        if best_match is not None:
            mappings.append({
                "apt_id": row_apt["apt_id"],
                "naver_complex_no": best_match["complex_no"],
                "mapping_method": best_method,
                "confidence_score": round(best_score, 2),
            })

        if count % 2000 == 0:
            print(f"  진행: {count}/{len(df_apt)} ({time.time() - start_time:.1f}s)")

    df_mapping = pd.DataFrame(mappings)
    rate = len(df_mapping) / len(df_apt) * 100 if len(df_apt) else 0
    print(f"\n[결과] {len(df_apt)}개 중 {len(df_mapping)}개 매핑 ({rate:.1f}%)")

    if not df_mapping.empty:
        print("[3] DB 저장...")
        with engine.begin() as conn:
            df_mapping.to_sql("complex_mapping_staging", conn, if_exists="replace", index=False)
            conn.execute(text("""
                INSERT INTO complex_mapping (apt_id, naver_complex_no, mapping_method, confidence_score)
                SELECT apt_id, naver_complex_no, mapping_method, confidence_score
                FROM complex_mapping_staging
                ON CONFLICT (apt_id) DO UPDATE SET
                    naver_complex_no = EXCLUDED.naver_complex_no,
                    mapping_method = EXCLUDED.mapping_method,
                    confidence_score = EXCLUDED.confidence_score,
                    created_at = CURRENT_TIMESTAMP;
            """))
            conn.execute(text("DROP TABLE IF EXISTS complex_mapping_staging;"))
        print("  DB 저장 완료")


if __name__ == "__main__":
    main()

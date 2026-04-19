"""rt_complex 에 sido_name / sgg_name 컬럼 추가 + 백필 (1회성).

apt_id 앞 5자리 (LAWD_CD) 를 `pipeline.lawd.LAWD_SGG` 로 매핑하여 UPDATE.
멱등: 이미 컬럼이 있으면 skip. 백필은 NULL 인 행만 대상.

사용:
    python -m scripts.add_sgg_columns           # ALTER + 백필 실행
    python -m scripts.add_sgg_columns --dry     # 영향 범위만 출력
"""

import argparse

from sqlalchemy import text

from pipeline.lawd import LAWD_SGG
from shared.db import get_engine


def _columns_exist(conn) -> tuple[bool, bool]:
    rows = conn.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'rt_complex' AND column_name IN ('sido_name', 'sgg_name')
    """)).fetchall()
    names = {r[0] for r in rows}
    return "sido_name" in names, "sgg_name" in names


def main(dry_run: bool = False) -> None:
    engine = get_engine()

    with engine.connect() as conn:
        has_sido, has_sgg = _columns_exist(conn)
        total = conn.execute(text("SELECT COUNT(*) FROM rt_complex")).scalar()

    print(f"== 현황 ==")
    print(f"  rt_complex: {total:,} 건")
    print(f"  sido_name 컬럼: {'있음' if has_sido else '없음'}")
    print(f"  sgg_name 컬럼: {'있음' if has_sgg else '없음'}")
    print(f"  LAWD_SGG 매핑: {len(LAWD_SGG)} 개")

    # 백필 영향 범위
    with engine.connect() as conn:
        # 컬럼이 없으면 전체가 백필 대상, 있으면 NULL 인 것만
        if has_sgg:
            unfilled = conn.execute(text(
                "SELECT COUNT(*) FROM rt_complex WHERE sgg_name IS NULL AND apt_id ~ '^[0-9]{5}-'"
            )).scalar()
        else:
            unfilled = conn.execute(text(
                "SELECT COUNT(*) FROM rt_complex WHERE apt_id ~ '^[0-9]{5}-'"
            )).scalar()
        # 매핑 불가 (LAWD_CD 가 LAWD_SGG 에 없음)
        all_lawds = conn.execute(text(
            "SELECT DISTINCT LEFT(apt_id, 5) FROM rt_complex WHERE apt_id ~ '^[0-9]{5}-'"
        )).fetchall()
        uncovered = sorted({r[0] for r in all_lawds} - set(LAWD_SGG.keys()))

    print(f"\n  백필 대상 (NULL): {unfilled:,}")
    if uncovered:
        print(f"  매핑 불가 LAWD_CD: {uncovered}")

    if dry_run:
        print("\n(dry-run) 종료")
        return

    # 1) ALTER TABLE
    with engine.begin() as conn:
        if not has_sido:
            print("\n[ALTER] sido_name 컬럼 추가")
            conn.execute(text("ALTER TABLE rt_complex ADD COLUMN sido_name VARCHAR(20)"))
        if not has_sgg:
            print("[ALTER] sgg_name 컬럼 추가")
            conn.execute(text("ALTER TABLE rt_complex ADD COLUMN sgg_name VARCHAR(30)"))

    # 2) 백필 — LAWD_CD 별 일괄 UPDATE
    print(f"\n[BACKFILL] {len(LAWD_SGG)}개 LAWD_CD 순회")
    updated_total = 0
    with engine.begin() as conn:
        for lawd_cd, (sido, sgg) in LAWD_SGG.items():
            res = conn.execute(
                text("""
                    UPDATE rt_complex
                    SET sido_name = :sido, sgg_name = :sgg
                    WHERE LEFT(apt_id, 5) = :cd
                      AND (sido_name IS NULL OR sgg_name IS NULL)
                """),
                {"sido": sido, "sgg": sgg, "cd": lawd_cd},
            )
            updated_total += res.rowcount or 0
    print(f"  업데이트 {updated_total:,} 행")

    # 3) 인덱스 (검색 성능)
    with engine.begin() as conn:
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_rt_complex_sgg ON rt_complex(sgg_name)"))
    print("[INDEX] idx_rt_complex_sgg 생성/확인")

    # 검증
    with engine.connect() as conn:
        still_null = conn.execute(
            text("SELECT COUNT(*) FROM rt_complex WHERE sgg_name IS NULL")
        ).scalar()
    print(f"\n== 완료 ==")
    print(f"  백필 후 sgg_name NULL: {still_null} (매핑 없는 LAWD_CD 또는 비정형 apt_id)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry", action="store_true", help="ALTER/UPDATE 실행 없이 영향 범위만 출력")
    args = parser.parse_args()
    main(dry_run=args.dry)

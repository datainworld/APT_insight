"""Remote DB FK 복구 (1회성).

Phase 5 배포 시 대량 `COPY` 후 재설정되지 않은 FK 제약을 복원한다.
부모 테이블(rt_complex / nv_complex)에 없는 고아 자식 레코드는 삭제 후 FK 추가.

멱등: 이미 FK가 있으면 skip.

사용법:
    python -m scripts.restore_fk           # 실제 실행
    python -m scripts.restore_fk --dry     # orphan 건수만 확인
"""

import argparse

from sqlalchemy import text

from shared.db import get_engine

# (table, fk_name, child_col, ref_table, ref_col)
FKS = [
    ("rt_trade", "rt_trade_apt_id_fkey", "apt_id", "rt_complex", "apt_id"),
    ("rt_rent", "rt_rent_apt_id_fkey", "apt_id", "rt_complex", "apt_id"),
    ("nv_listing", "nv_listing_complex_no_fkey", "complex_no", "nv_complex", "complex_no"),
    ("complex_mapping", "complex_mapping_apt_id_fkey", "apt_id", "rt_complex", "apt_id"),
    ("complex_mapping", "complex_mapping_naver_complex_no_fkey",
     "naver_complex_no", "nv_complex", "complex_no"),
]


def constraint_exists(conn, name: str) -> bool:
    row = conn.execute(
        text("SELECT 1 FROM pg_constraint WHERE conname = :n"),
        {"n": name},
    ).fetchone()
    return row is not None


def main(dry_run: bool = False) -> None:
    engine = get_engine()

    print("== 현황 ==")
    plan = []
    with engine.connect() as conn:
        for tbl, conname, col, ref_tbl, ref_col in FKS:
            if constraint_exists(conn, conname):
                print(f"  {conname:<45} 이미 존재")
                continue
            orphan = conn.execute(text(
                f"SELECT COUNT(*) FROM {tbl} "
                f"WHERE {col} IS NOT NULL "
                f"AND {col} NOT IN (SELECT {ref_col} FROM {ref_tbl})"
            )).scalar() or 0
            total = conn.execute(text(f"SELECT COUNT(*) FROM {tbl}")).scalar() or 0
            print(f"  {tbl:<18}.{col:<18} → {ref_tbl}.{ref_col}: "
                  f"orphan {orphan:,} / total {total:,}")
            plan.append((tbl, conname, col, ref_tbl, ref_col, orphan))

    if dry_run:
        print("\n[DRY RUN] 변경 없음")
        return

    if not plan:
        print("\n모든 FK 이미 복원됨 — skip")
        return

    print("\n== 실행 ==")
    for tbl, conname, col, ref_tbl, ref_col, orphan in plan:
        if orphan > 0:
            with engine.begin() as conn:
                res = conn.execute(text(
                    f"DELETE FROM {tbl} "
                    f"WHERE {col} IS NOT NULL "
                    f"AND {col} NOT IN (SELECT {ref_col} FROM {ref_tbl})"
                ))
                print(f"  {tbl}: orphan {res.rowcount:,}건 삭제")

        with engine.begin() as conn:
            conn.execute(text(
                f"ALTER TABLE {tbl} ADD CONSTRAINT {conname} "
                f"FOREIGN KEY ({col}) REFERENCES {ref_tbl}({ref_col})"
            ))
            print(f"  {tbl}: FK {conname} 추가 완료")

    print("\n완료")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry", action="store_true", help="orphan 건수만 확인")
    args = parser.parse_args()
    main(args.dry)

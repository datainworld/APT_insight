"""1회성 마이그레이션: rt_trade, rt_rent 자연키 UNIQUE 제약 추가.

교재 17장의 `INSERT OR IGNORE` 동작(PostgreSQL `ON CONFLICT DO NOTHING`)을
활성화하려면 자연키 UNIQUE 제약이 필요하다. 기존 중복을 먼저 제거한 후
`ALTER TABLE ADD CONSTRAINT`를 실행한다.

사용법:
    python -m scripts.migrate_unique_constraints           # 실행
    python -m scripts.migrate_unique_constraints --dry     # 중복 건수만 확인

멱등: 제약이 이미 존재하면 해당 테이블은 skip.
"""

import argparse

from sqlalchemy import text

from shared.db import get_engine

TRADE_CONSTRAINT = "rt_trade_natural_uq"
RENT_CONSTRAINT = "rt_rent_natural_uq"

#  CTID + ROW_NUMBER 방식: O(N log N), 자기조인(O(N²)) 대비 수십 배 빠름.
#  PARTITION BY는 NULL을 같은 그룹으로 묶으므로 IS NOT DISTINCT FROM과 동일 동작.
DEDUP_TRADE_SQL = """
DELETE FROM rt_trade
WHERE ctid IN (
    SELECT ctid FROM (
        SELECT ctid, ROW_NUMBER() OVER (
            PARTITION BY apt_id, deal_date, deal_amount, exclusive_area, floor
            ORDER BY id
        ) AS rn FROM rt_trade
    ) t WHERE rn > 1
);
"""

DEDUP_RENT_SQL = """
DELETE FROM rt_rent
WHERE ctid IN (
    SELECT ctid FROM (
        SELECT ctid, ROW_NUMBER() OVER (
            PARTITION BY apt_id, deal_date, deposit, monthly_rent, exclusive_area, floor
            ORDER BY id
        ) AS rn FROM rt_rent
    ) t WHERE rn > 1
);
"""

ADD_TRADE_CONSTRAINT = f"""
ALTER TABLE rt_trade
ADD CONSTRAINT {TRADE_CONSTRAINT}
UNIQUE (apt_id, deal_date, deal_amount, exclusive_area, floor);
"""

ADD_RENT_CONSTRAINT = f"""
ALTER TABLE rt_rent
ADD CONSTRAINT {RENT_CONSTRAINT}
UNIQUE (apt_id, deal_date, deposit, monthly_rent, exclusive_area, floor);
"""


def constraint_exists(conn, name: str) -> bool:
    row = conn.execute(
        text("SELECT 1 FROM pg_constraint WHERE conname = :name"),
        {"name": name},
    ).fetchone()
    return row is not None


def count_rows_and_dups(conn) -> tuple[int, int, int, int]:
    trade_total = conn.execute(text("SELECT COUNT(*) FROM rt_trade")).scalar() or 0
    rent_total = conn.execute(text("SELECT COUNT(*) FROM rt_rent")).scalar() or 0
    trade_dup = conn.execute(text("""
        SELECT COUNT(*) - COUNT(*) FILTER (WHERE rn = 1) FROM (
            SELECT ROW_NUMBER() OVER (
                PARTITION BY apt_id, deal_date, deal_amount, exclusive_area, floor
                ORDER BY id
            ) AS rn FROM rt_trade
        ) t
    """)).scalar() or 0
    rent_dup = conn.execute(text("""
        SELECT COUNT(*) - COUNT(*) FILTER (WHERE rn = 1) FROM (
            SELECT ROW_NUMBER() OVER (
                PARTITION BY apt_id, deal_date, deposit, monthly_rent, exclusive_area, floor
                ORDER BY id
            ) AS rn FROM rt_rent
        ) t
    """)).scalar() or 0
    return trade_total, rent_total, trade_dup, rent_dup


def main(dry_run: bool = False) -> None:
    engine = get_engine()

    with engine.connect() as conn:
        trade_total, rent_total, trade_dup, rent_dup = count_rows_and_dups(conn)
        has_trade = constraint_exists(conn, TRADE_CONSTRAINT)
        has_rent = constraint_exists(conn, RENT_CONSTRAINT)

    print(f"rt_trade: {trade_total:,}건 (중복 {trade_dup:,}건) / 제약={has_trade}")
    print(f"rt_rent:  {rent_total:,}건 (중복 {rent_dup:,}건) / 제약={has_rent}")

    if dry_run:
        print("\n[DRY RUN] 변경 없음")
        return

    if has_trade and has_rent:
        print("\n두 제약 모두 이미 존재 — skip")
        return

    with engine.begin() as conn:
        if not has_trade:
            if trade_dup > 0:
                print(f"\nrt_trade 중복 제거 중...")
                res = conn.execute(text(DEDUP_TRADE_SQL))
                print(f"  {res.rowcount:,}건 삭제")
            print(f"rt_trade UNIQUE 제약 추가 ({TRADE_CONSTRAINT})")
            conn.execute(text(ADD_TRADE_CONSTRAINT))
        else:
            print(f"\nrt_trade: {TRADE_CONSTRAINT} 이미 존재 — skip")

        if not has_rent:
            if rent_dup > 0:
                print(f"\nrt_rent 중복 제거 중...")
                res = conn.execute(text(DEDUP_RENT_SQL))
                print(f"  {res.rowcount:,}건 삭제")
            print(f"rt_rent UNIQUE 제약 추가 ({RENT_CONSTRAINT})")
            conn.execute(text(ADD_RENT_CONSTRAINT))
        else:
            print(f"\nrt_rent: {RENT_CONSTRAINT} 이미 존재 — skip")

    print("\n완료")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry", action="store_true", help="중복 건수만 확인")
    args = parser.parse_args()
    main(args.dry)

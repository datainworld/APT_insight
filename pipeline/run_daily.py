"""일일 파이프라인 오케스트레이터 (교재 19장).

RT → NV → News → MV refresh 순차 실행, 각 단계 에러 격리, JSON 리포트 저장, exit code 0/1.
모든 성공 시 success / 일부 실패 시 partial / 전원 실패 시 error.

사용법:
    python -m pipeline.run_daily

크론 예시 (매일 새벽 3시):
    0 3 * * * cd /path/to/APT_insight_04 && python -m pipeline.run_daily
"""

import json
import sys
import time
import traceback

from sqlalchemy import text

from pipeline.collect_news import collect as collect_news
from pipeline.update_nv_daily import main as update_nv
from pipeline.update_rt_daily import main as update_rt
from pipeline.utils import now_kst
from shared.config import BASE_DIR
from shared.db import get_engine

_MV_NAMES = ("mv_metrics_by_sgg", "mv_metrics_by_complex")


def _refresh_mvs() -> dict:
    """REFRESH MATERIALIZED VIEW for each MV. CONCURRENTLY 우선, 실패 시 일반 REFRESH.

    첫 실행 시에는 데이터가 없어 CONCURRENTLY 가 실패할 수 있어 폴백을 둔다.
    """
    refreshed: list[str] = []
    errors: list[str] = []
    engine = get_engine()
    for name in _MV_NAMES:
        try:
            with engine.connect() as conn:
                # Autocommit for MV refresh (CONCURRENTLY requires no open txn)
                conn.execution_options(isolation_level="AUTOCOMMIT").execute(
                    text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {name}")
                )
            refreshed.append(name)
        except Exception:
            try:
                with engine.connect() as conn:
                    conn.execution_options(isolation_level="AUTOCOMMIT").execute(
                        text(f"REFRESH MATERIALIZED VIEW {name}")
                    )
                refreshed.append(name)
            except Exception as e:
                errors.append(f"{name}: {e}")
    return {
        "status": "success" if not errors else ("partial" if refreshed else "error"),
        "refreshed": refreshed,
        "error_count": len(errors),
    }


def main(nv_sample: int | None = None) -> None:
    started_at = now_kst()
    report: dict = {
        "date": started_at.strftime("%Y-%m-%d"),
        "started_at": started_at.isoformat(timespec="seconds"),
        "rt": {"status": "pending"},
        "nv": {"status": "pending"},
        "news": {"status": "pending"},
        "mv_refresh": {"status": "pending"},
        "status": "pending",
    }

    t0 = time.time()

    # --- RT ---
    try:
        report["rt"] = update_rt()
    except Exception as e:
        traceback.print_exc()
        report["rt"] = {"status": "error", "message": str(e)}

    # --- NV (1회 재시도) ---
    try:
        report["nv"] = update_nv(sample=nv_sample)
    except Exception as e:
        print(f"\n[NV 1차 실패] {e} / 60초 후 1회 재시도")
        time.sleep(60)
        try:
            report["nv"] = update_nv(sample=nv_sample)
        except Exception as e2:
            traceback.print_exc()
            report["nv"] = {"status": "error", "message": str(e2)}

    # --- News ---
    try:
        report["news"] = collect_news()
    except Exception as e:
        traceback.print_exc()
        report["news"] = {"status": "error", "message": str(e)}

    # --- MV Refresh (RT/NV 후 최신 상태로 갱신) ---
    try:
        report["mv_refresh"] = _refresh_mvs()
    except Exception as e:
        traceback.print_exc()
        report["mv_refresh"] = {"status": "error", "message": str(e)}

    # --- 최종 상태 (핵심 단계: RT + NV 기준, 뉴스/MV 는 보조) ---
    rt_ok = report["rt"].get("status") == "success"
    nv_ok = report["nv"].get("status") == "success"
    if rt_ok and nv_ok:
        report["status"] = "success"
    elif rt_ok or nv_ok:
        report["status"] = "partial"
    else:
        report["status"] = "error"

    finished_at = now_kst()
    report["finished_at"] = finished_at.isoformat(timespec="seconds")
    report["elapsed_seconds"] = round(time.time() - t0, 1)

    # --- 리포트 저장 ---
    reports_dir = BASE_DIR / "data" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"{report['date']}.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print("\n" + "=" * 60)
    print(f"  [일일 파이프라인] {report['status'].upper()} / {report['elapsed_seconds']}s")
    print(f"  리포트: {report_path}")
    print("=" * 60)

    sys.exit(0 if report["status"] == "success" else 1)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="일일 파이프라인 오케스트레이터 (교재 19장)")
    parser.add_argument(
        "--nv-sample",
        type=int,
        default=None,
        help="네이버 단지 개수 제한 (Local 검증용)",
    )
    args = parser.parse_args()
    main(nv_sample=args.nv_sample)

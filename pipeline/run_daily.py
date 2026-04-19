"""일일 파이프라인 오케스트레이터 (교재 19장).

RT → NV 순차 실행, 각 단계 에러 격리, JSON 리포트 저장, exit code 0/1.
한쪽 실패 시 `status: "partial"`.

사용법:
    python -m pipeline.run_daily

크론 예시 (매일 새벽 3시):
    0 3 * * * cd /path/to/APT_insight_04 && python -m pipeline.run_daily
"""

import json
import sys
import time
import traceback

from pipeline.update_nv_daily import main as update_nv
from pipeline.update_rt_daily import main as update_rt
from pipeline.utils import now_kst
from shared.config import BASE_DIR


def main(nv_sample: int | None = None) -> None:
    started_at = now_kst()
    report: dict = {
        "date": started_at.strftime("%Y-%m-%d"),
        "started_at": started_at.isoformat(timespec="seconds"),
        "rt": {"status": "pending"},
        "nv": {"status": "pending"},
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

    # --- 최종 상태 ---
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
    parser.add_argument("--nv-sample", type=int, default=None,
                        help="네이버 단지 개수 제한 (Local 검증용)")
    args = parser.parse_args()
    main(nv_sample=args.nv_sample)

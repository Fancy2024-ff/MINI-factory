"""core.pipeline.auto_runner — 一键主流程编排：抓取 → 机会队列 → 生成小程序。

只做编排，不重写抓取/生成实现：
- 抓取实现在 core.opportunity.crawl_runner（run_once 写出 opportunity-queue.json）。
- 生成走现有 queue 链路（core/pipeline/runner.py --mode queue），每个 feature 一个子进程，
  避免 runner 模块级全局状态在多次生成间串味。
- 输出 auto-report.json：crawl summary + 已生成 jobs。

入口：python -m core.pipeline.auto_runner --job-id auto-smoke-001 \
        --regions CN,US --platforms app_store --limit 10 --max-generate 1
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from core.opportunity import crawl_runner
from core.opportunity import opportunity_queue as oq

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OPP_DIR = PROJECT_ROOT / "data" / "opportunity"
OUTPUTS_DIR = PROJECT_ROOT / "data" / "outputs"
QUEUE_PATH = OPP_DIR / "opportunity-queue.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_one(job_id: str) -> dict:
    """跑一次 queue 模式生成（子进程隔离）。返回该 job 的结果摘要。"""
    cmd = [sys.executable, "-X", "utf8", str(PROJECT_ROOT / "core" / "pipeline" / "runner.py"),
           "--mode", "queue", "--job-id", job_id]
    proc = subprocess.run(
        cmd, cwd=str(PROJECT_ROOT), capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )
    out_dir = OUTPUTS_DIR / job_id
    result = {"job_id": job_id, "exit_code": proc.returncode,
              "build_passed": None, "qa_passed": None, "feature_key": None,
              "selected_template": None}

    qa_path = out_dir / "qa-report.json"
    if qa_path.exists():
        try:
            qa = json.loads(qa_path.read_text(encoding="utf-8-sig"))
            result["qa_passed"] = qa.get("passed")
            result["build_passed"] = qa.get("checks", {}).get("build_passed", qa.get("build_passed"))
        except Exception:
            pass
    sel_path = out_dir / "template-selection.json"
    if sel_path.exists():
        try:
            result["selected_template"] = json.loads(sel_path.read_text(encoding="utf-8-sig")).get("selected_template")
        except Exception:
            pass
    return result


def run_auto(
    job_id: str | None = None,
    regions: str = "",
    platforms: str = "",
    limit: int | None = None,
    max_generate: int = 1,
) -> dict:
    """抓取 → 队列 → 生成。返回 auto-report dict 并写盘。"""
    base_job = job_id or ("auto-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    _regions = [r.strip().upper() for r in regions.split(",") if r.strip()] or None
    _platforms = [p.strip() for p in platforms.split(",") if p.strip()] or None

    print(f"[auto] 1/3 抓取市场数据 regions={_regions} platforms={_platforms} ...")
    crawl_report = crawl_runner.run_once(regions=_regions, platforms=_platforms, limit=limit)
    crawl_counts = crawl_report.get("counts", {})
    print(f"[auto]   candidates={crawl_counts.get('candidates')} "
          f"queue_pending={crawl_counts.get('queue_pending')}")

    print(f"[auto] 2/3 消费机会队列（最多生成 {max_generate} 个）...")
    generated: list[dict] = []
    for i in range(max_generate):
        queue = oq.load_queue(QUEUE_PATH)
        if oq.pop_next_pending(queue) is None:
            print("[auto]   队列无更多 pending，停止")
            break
        gen_job_id = f"{base_job}-{i+1:02d}"
        # 取消费前的 feature_key 以写入 report（runner 内部会消费并回写状态）
        pending = oq.pop_next_pending(queue)
        res = _generate_one(gen_job_id)
        res["feature_key"] = pending.get("feature_key") if pending else None
        res["queue_id"] = pending.get("queue_id") if pending else None
        generated.append(res)
        status = "ok" if res.get("qa_passed") and res.get("build_passed") else "fail"
        print(f"[auto]   生成 {gen_job_id} feature={res['feature_key']} → {status}")

    report = {
        "auto_job_id": base_job,
        "generated_at": _now_iso(),
        "crawl_summary": {
            "crawl_stats": crawl_report.get("crawl_stats"),
            "dedup_stats": crawl_report.get("dedup_stats"),
            "feature_stats": crawl_report.get("feature_stats"),
            "queue_stats": crawl_report.get("queue_stats"),
        },
        "max_generate": max_generate,
        "generated_jobs": generated,
        "data_source": "opportunity_queue",
        "source": "crawl_generated_opportunity",
    }
    print("[auto] 3/3 写 auto-report.json")
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUTS_DIR / f"{base_job}-auto-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[auto] 完成：{report_path}")
    return report


def main():
    parser = argparse.ArgumentParser(description="auto 主流程：抓取 → 机会队列 → 生成小程序")
    parser.add_argument("--job-id", default=None)
    parser.add_argument("--regions", default="", help="逗号分隔，如 CN,US")
    parser.add_argument("--platforms", default="", help="逗号分隔，如 app_store,google_play")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-generate", type=int, default=1)
    args = parser.parse_args()
    run_auto(job_id=args.job_id, regions=args.regions, platforms=args.platforms,
             limit=args.limit, max_generate=args.max_generate)


if __name__ == "__main__":
    main()

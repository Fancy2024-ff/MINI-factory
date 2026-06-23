"""scripts/crawl_opportunities.py — 正式机会抓取脚本（日常/排查/定时任务入口）。

只做参数编排 + 摘要打印，抓取逻辑全部委托 core.opportunity.crawl_runner.run_once，
不复制实现。Windows / PowerShell 友好。

用法：
    python scripts/crawl_opportunities.py --preset quick --dry-run
    python scripts/crawl_opportunities.py --preset cn --limit 20
    python scripts/crawl_opportunities.py --preset global --limit 20
    python scripts/crawl_opportunities.py --regions CN,US --platforms app_store --entry-types top_free
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 确保从仓库根可 import core.*
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Windows 控制台 UTF-8（避免中文 GBK 报错）
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from core.opportunity import crawl_runner
from core.opportunity import crawl_config as cfg

# 预设：地区/平台/类目/入口组合（None 表示用 crawl_config 默认）。
PRESETS: dict[str, dict] = {
    "cn": {
        "regions": ["CN"], "platforms": ["app_store"],
        "entry_types": [cfg.TOP_FREE, cfg.TOP_GROSSING, cfg.SEARCH],
    },
    "global": {
        "regions": ["CN", "US", "JP", "KR", "TW", "HK", "SG", "IN", "ID", "BR"],
        "platforms": ["app_store", "google_play"], "entry_types": None,
    },
    "asia": {
        "regions": ["CN", "JP", "KR", "TW", "HK", "SG", "ID"],
        "platforms": ["app_store", "google_play"], "entry_types": None,
    },
    "quick": {
        "regions": ["US"], "platforms": ["app_store"], "categories": ["photo"],
        "entry_types": [cfg.TOP_FREE], "limit": 5,
    },
    "top": {
        "regions": None, "platforms": ["app_store", "google_play"],
        "entry_types": [cfg.TOP_FREE, cfg.TOP_GROSSING],
    },
    "search": {
        "regions": None, "platforms": ["app_store", "google_play"],
        "entry_types": [cfg.SEARCH],
    },
}


def _csv(v: str) -> list[str] | None:
    items = [x.strip() for x in (v or "").split(",") if x.strip()]
    return items or None


def resolve_args(args) -> dict:
    """把 preset + 显式参数合并成 run_once 的关键字参数。显式参数覆盖 preset。"""
    base = dict(PRESETS.get(args.preset, {})) if args.preset else {}
    out = {
        "regions": base.get("regions"),
        "platforms": base.get("platforms"),
        "categories": base.get("categories"),
        "entry_types": base.get("entry_types"),
        "limit": base.get("limit"),
        "dry_run": args.dry_run,
        "date_str": args.date,
    }
    # 显式参数覆盖 preset
    if _csv(args.regions) is not None:
        out["regions"] = [r.upper() for r in _csv(args.regions)]
    if _csv(args.platforms) is not None:
        out["platforms"] = _csv(args.platforms)
    if _csv(args.categories) is not None:
        out["categories"] = _csv(args.categories)
    if _csv(args.entry_types) is not None:
        out["entry_types"] = _csv(args.entry_types)
    if args.limit is not None:
        out["limit"] = args.limit
    return out


def _print_summary(report: dict) -> None:
    s = report.get("summary", {})
    c = report.get("counts", {})
    fs = report.get("feature_stats", {})
    print("-" * 56)
    print(f"  tasks: success={s.get('success')} failed={s.get('failed')} "
          f"skipped={s.get('skipped')} cached={s.get('cached')}")
    print(f"  candidates       = {c.get('candidates')}")
    print(f"  features         = {c.get('features_total')}")
    print(f"  recommended      = {c.get('features_recommended')}")
    print(f"  queue_pending    = {c.get('queue_pending')}")
    top_templates = fs.get("top_templates", {})
    if top_templates:
        dist = ", ".join(f"{k}:{v}" for k, v in top_templates.items())
        print(f"  top_templates    = {dist}")
    if not report.get("dry_run"):
        from core.opportunity.crawl_runner import OPP_DIR
        print("  输出文件:")
        for name in ("candidate-pool.json", "feature-opportunities.json",
                     "opportunity-queue.json", "crawl-report.json"):
            print(f"    {OPP_DIR / name}")
    else:
        print("  dry-run：未写盘")
    print("-" * 56)


def _warn_if_empty(report: dict) -> None:
    if report.get("counts", {}).get("queue_pending", 0) > 0:
        return
    print("WARNING: queue_pending = 0，没有可生产机会。可能原因：")
    print("   - rating filter：search 候选评分低于阈值（scoring-config.min_rating）")
    print("   - category keyword 没命中：该类目关键词未匹配到可拆功能")
    print("   - processed-apps 已过滤：feature 已生产或超重试上限")
    print("   - 数据源无结果：抓取为空 / 地区+入口组合未返回 App")


def main():
    parser = argparse.ArgumentParser(description="正式机会抓取脚本（委托 crawl_runner.run_once）")
    parser.add_argument("--preset", choices=sorted(PRESETS.keys()), default=None,
                        help="预设：cn / global / asia / quick / top / search")
    parser.add_argument("--regions", default="", help="逗号分隔，覆盖 preset，如 CN,US,JP")
    parser.add_argument("--platforms", default="", help="逗号分隔，如 app_store,google_play")
    parser.add_argument("--categories", default="", help="逗号分隔，如 photo,entertainment")
    parser.add_argument("--entry-types", default="", help="逗号分隔，如 top_free,top_grossing,search")
    parser.add_argument("--limit", type=int, default=None, help="每请求条数")
    parser.add_argument("--max-tasks", type=int, default=None, help="本轮最大任务数（防爆刷）")
    parser.add_argument("--date", default=None, help="YYYYMMDD；默认今天")
    parser.add_argument("--dry-run", action="store_true", help="不写盘，仅执行与汇总")
    args = parser.parse_args()

    if args.max_tasks is not None:
        cfg.CRAWL_PARAMS["max_tasks_per_run"] = args.max_tasks

    params = resolve_args(args)
    label = args.preset or "custom"
    print(f"[crawl-opportunities] preset={label} dry_run={params['dry_run']}")
    print(f"  regions={params['regions']} platforms={params['platforms']} "
          f"categories={params['categories']} entry_types={params['entry_types']} limit={params['limit']}")

    report = crawl_runner.run_once(**params)
    _print_summary(report)
    _warn_if_empty(report)


if __name__ == "__main__":
    main()

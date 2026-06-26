"""core.opportunity.crawl_runner — 执行一次机会抓取（capability-domain 编排）。

流程：遍历 平台×地区×类目×入口(entry_type) → 合规限速抓取（复用 scrapers）→
合并候选池 → 功能拆解 → 排序 → 生成队列 → 写盘所有产物 + crawl-report。

入口（entry_type）：top_free / top_grossing 是真实榜单；search 是关键词搜索。
合规抓取：限速 / jitter / timeout / 退避重试 / snapshot 缓存 / 最大任务数 / 统一 UA /
失败降级（不死循环），单请求级生效（见 fetch_policy）。不做代理池/账号绕封。

入口：python -m core.opportunity.crawl_runner --mode once [--dry-run]
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from core.opportunity import crawl_config as cfg
from core.opportunity import fetch_policy
from core.opportunity.candidate_pool import build_candidate_pool
from core.opportunity.feature_extraction import extract_all
from core.opportunity.ranking import rank_features
from core.opportunity.opportunity_queue import build_queue
from core.opportunity.opportunity_brief import build_briefs, brief_stats
from core.opportunity import processed_apps

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OPP_DIR = DATA_DIR / "opportunity"
SNAP_DIR = OPP_DIR / "snapshots"
SCORING_CONFIG = OPP_DIR / "scoring-config.json"
PROCESSED_PATH = OPP_DIR / "processed-apps.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_list(value) -> list[str] | None:
    """把 'a,b' 或 ['a','b'] 统一成 ['a','b']；空/None 返回 None（让调用方走默认）。

    防御 worker 误传字符串导致 for x in 'app_store' 按字符遍历的 bug。
    只负责"字符串→列表、空→None"，不负责填默认。
    """
    if value is None:
        return None
    if isinstance(value, str):
        items = [v.strip() for v in value.split(",") if v.strip()]
        return items or None
    if isinstance(value, (list, tuple)):
        items = [str(v).strip() for v in value if str(v).strip()]
        return items or None
    return None


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_scoring_config() -> dict:
    if SCORING_CONFIG.exists():
        try:
            return json.loads(SCORING_CONFIG.read_text(encoding="utf-8-sig"))
        except Exception:
            pass
    return {
        "weights": {},  # 空则用 ranking.DEFAULT_WEIGHTS
        "filters": {"min_rating": 3.8, "skip_processed_features": True, "max_retry_count": 2},
    }


def _appinfo_to_records(apps, platform: str, region: str, category: str,
                        entry_type: str, keywords: list[str]) -> list[dict]:
    """把 scraper 的 AppInfo 列表转成 candidate_pool 原始记录（带真实抓取上下文）。

    rank 语义随 entry_type 区分：榜单(top_free/top_grossing)=榜单名次，search=搜索位置。
    keyword 写真实命中关键词（search 用传入关键词；榜单无关键词则用 category 标签）。
    """
    is_ranking = entry_type in (cfg.TOP_FREE, cfg.TOP_GROSSING)
    kw_list = keywords if (entry_type == cfg.SEARCH and keywords) else [category]
    records = []
    for rank, a in enumerate(apps, start=1):
        records.append({
            "source": platform,
            "app_id": getattr(a, "app_id", "") or "",
            "name": getattr(a, "name", "") or "",
            "developer": getattr(a, "developer", "") or "",
            "region": region,
            "category": getattr(a, "category", "") or category,
            "entry_type": entry_type,
            "keywords": list(kw_list),
            "rank": rank,
            "rank_kind": "ranking" if is_ranking else "search_position",
            "downloads": getattr(a, "downloads", 0) or 0,
            "rating": getattr(a, "rating", 0) or 0.0,
            "review_count": getattr(a, "review_count", 0) or 0,
            "description": getattr(a, "description", "") or "",
            "features": list(getattr(a, "features", []) or []),
            "monetization": getattr(a, "monetization", "") or "unknown",
        })
    return records


def _fetch_with_retry(fetch_fn: Callable, *, params: dict, report_task: dict) -> list:
    """经 fetch_policy 退避重试抓取；失败降级返回空列表（不抛、不死循环）。"""
    attempts = {"n": 0, "last": ""}

    def _do():
        attempts["n"] += 1
        return fetch_fn(**params)

    def _on_err(msg: str):
        attempts["last"] = msg

    try:
        apps = fetch_policy.with_retry(_do, on_error=_on_err)
        report_task["status"] = "success"
        report_task["count"] = len(apps)
        report_task["attempts"] = attempts["n"]
        return apps
    except Exception:  # noqa: BLE001 — 全部重试失败，降级
        report_task["status"] = "failed"
        report_task["error"] = attempts["last"][:200]
        report_task["attempts"] = attempts["n"]
        return []


def _snapshot_path(date_str: str, platform: str, region: str, category: str, entry_type: str) -> Path:
    return SNAP_DIR / date_str / f"{platform}-{region.lower()}-{category}-{entry_type}.json"


def run_once(
    regions: list[str] | None = None,
    platforms: list[str] | None = None,
    categories: list[str] | None = None,
    entry_types: list[str] | None = None,
    limit: int | None = None,
    date_str: str | None = None,
    dry_run: bool = False,
    appstore_fetch: Callable | None = None,
    googleplay_fetch: Callable | None = None,
) -> dict:
    """执行一次抓取并写盘全部产物。返回 crawl-report dict。

    任务维度 = 平台 × 地区 × 类目 × 入口(entry_type)。
    scraper 可注入（appstore_fetch/googleplay_fetch），测试用 mock，不打真实网络。
    dry_run=True 时不写盘，只返回 report（仍会执行抓取与处理）。
    """
    date_str = date_str or datetime.now().strftime("%Y%m%d")
    # 防御性归一化：worker crawl 路径可能透传字符串（如 'app_store'），
    # 不归一化会被 for x in str 按字符遍历成 0 任务、队列写空。
    regions = _as_list(regions)
    # 地区大小写归一：REGION_SUPPORT 键为大写，CLI/auto 路径均 upper，保持一致避免静默跳过。
    if regions is not None:
        regions = [r.upper() for r in regions]
    platforms = _as_list(platforms)
    categories = _as_list(categories)
    entry_types = _as_list(entry_types)
    platforms = platforms or cfg.PLATFORMS
    categories = categories or cfg.CATEGORIES
    entry_types = entry_types or cfg.ENTRY_TYPES
    limit = limit or cfg.CRAWL_PARAMS["per_request_limit"]
    max_tasks = cfg.CRAWL_PARAMS["max_tasks_per_run"]
    use_cache = cfg.CRAWL_PARAMS["use_cache"]

    if appstore_fetch is None:
        from core.opportunity.scrapers.appstore import fetch_ai_apps_appstore as appstore_fetch
    if googleplay_fetch is None:
        from core.opportunity.scrapers.googleplay import fetch_ai_apps_googleplay as googleplay_fetch

    report = {
        "date": date_str,
        "started_at": _now_iso(),
        "dry_run": dry_run,
        "params": {"limit": limit, "max_tasks_per_run": max_tasks, "use_cache": use_cache,
                   "entry_types": entry_types},
        "data_source_capability": cfg.capability_summary(),
        "tasks": [],
        "summary": {"success": 0, "failed": 0, "skipped": 0, "cached": 0, "tasks": 0},
    }
    all_records: list[dict] = []
    task_count = 0

    for platform in platforms:
        for region, region_status in cfg.regions_for_platform(platform, regions):
            if task_count >= max_tasks:
                break
            for category in categories:
                if task_count >= max_tasks:
                    break
                keywords = cfg.keywords_for_category(category)
                for entry_type in entry_types:
                    if task_count >= max_tasks:
                        break
                    task = {"platform": platform, "region": region, "category": category,
                            "entry_type": entry_type, "status": "pending"}

                    # 地区不支持 → 跳过并记录原因
                    if region_status == cfg.UNSUPPORTED:
                        task["status"] = "skipped"
                        task["reason"] = cfg.skip_reason(platform, region)
                        report["tasks"].append(task)
                        report["summary"]["skipped"] += 1
                        continue
                    # 入口不支持（如 GP top_grossing）→ 显式跳过，不静默
                    if cfg.entry_type_status(platform, entry_type) == cfg.UNSUPPORTED:
                        task["status"] = "skipped"
                        task["reason"] = cfg.entry_skip_reason(platform, entry_type)
                        report["tasks"].append(task)
                        report["summary"]["skipped"] += 1
                        continue
                    # App Store 榜单按 category→genre 真实生效；无映射则标 unsupported，不假装成功。
                    is_ranking = entry_type in (cfg.TOP_FREE, cfg.TOP_GROSSING)
                    if platform == "app_store" and is_ranking:
                        genre = cfg.appstore_genre(category)
                        if not genre:
                            task["status"] = "skipped"
                            task["reason"] = f"App Store 类目 {category} 无 genre 映射，榜单不可用"
                            report["tasks"].append(task)
                            report["summary"]["skipped"] += 1
                            continue
                        task["requested_category"] = category
                        task["actual_genre_id"] = genre
                        task["rank_kind"] = "ranking"

                    snap = _snapshot_path(date_str, platform, region, category, entry_type)
                    if use_cache and not dry_run and snap.exists():
                        try:
                            cached = json.loads(snap.read_text(encoding="utf-8-sig"))
                            all_records.extend(cached)
                            task["status"] = "cached"
                            task["count"] = len(cached)
                            report["tasks"].append(task)
                            report["summary"]["cached"] += 1
                            task_count += 1
                            continue
                        except Exception:
                            pass  # 缓存损坏则正常抓取

                    task_count += 1
                    if platform == "app_store":
                        params = {"category": category, "limit": limit, "country": region.lower(),
                                  "entry_type": entry_type, "keywords": keywords}
                        apps = _fetch_with_retry(appstore_fetch, params=params, report_task=task)
                    else:
                        params = {"category": category, "limit": limit, "country": region.lower(),
                                  "entry_type": entry_type, "keywords": keywords}
                        apps = _fetch_with_retry(googleplay_fetch, params=params, report_task=task)

                    records = _appinfo_to_records(apps, platform, region, category, entry_type, keywords)
                    all_records.extend(records)
                    if not dry_run and records:
                        _write_json(snap, records)

                    report["tasks"].append(task)
                    report["summary"]["success" if task["status"] == "success" else "failed"] += 1
                    fetch_policy.pace()  # 任务间合规间隔（单请求级已在 scraper 内 pace）
    report["summary"]["tasks"] = task_count
    return _finalize_run(report, all_records, task_count, date_str, dry_run)


def _finalize_run(report: dict, all_records: list[dict], task_count: int, date_str: str, dry_run: bool) -> dict:
    """处理候选池→功能拆解→排序→队列，写盘并补全 report（含运营可读统计）。"""
    scoring = load_scoring_config()
    weights = scoring.get("weights") or None
    filters = scoring.get("filters", {})

    candidates = build_candidate_pool(all_records)
    candidates_by_key = {c["canonical_key"]: c for c in candidates}
    features = extract_all(candidates)
    recommended = [f for f in features if f.get("production_recommended", True)]
    unsupported = [f for f in features if not f.get("production_recommended", True)]
    ranked = rank_features(
        features, candidates_by_key,
        weights=weights,
        min_rating=filters.get("min_rating", 0.0),
    )
    processed = processed_apps.load_processed(PROCESSED_PATH)
    # 机会简报：在 ranked 之后、queue 之前生成（briefs 驱动队列的 produce/review 过滤）。
    briefs = build_briefs(ranked, candidates_by_key, date_str=date_str)
    queue = build_queue(
        ranked, processed,
        max_retry_count=filters.get("max_retry_count", 2),
        skip_processed=filters.get("skip_processed_features", True),
        date_str=date_str,
        briefs=briefs,
    )

    # 队列过滤统计：被 processed / 超重试跳过的数量
    skipped_processed = sum(
        1 for f in ranked if processed_apps.is_processed(processed, f.get("feature_key", ""))
    )
    skipped_retry = sum(
        1 for f in ranked
        if processed_apps.retry_count(processed, f.get("feature_key", "")) > filters.get("max_retry_count", 2)
    )
    # 模板分布
    top_templates: dict[str, int] = {}
    for f in recommended:
        t = f.get("selected_template", "") or "unknown"
        top_templates[t] = top_templates.get(t, 0) + 1

    s = report["summary"]
    report["finished_at"] = _now_iso()
    report["crawl_stats"] = {
        "total_tasks": len(report["tasks"]),
        "fetched_tasks": s["success"],
        "skipped_tasks": s["skipped"],
        "cached_tasks": s["cached"],
        "failed_tasks": s["failed"],
    }
    report["dedup_stats"] = {
        "raw_records": len(all_records),
        "unique_apps": len(candidates),
        "merged_duplicates": max(0, len(all_records) - len(candidates)),
    }
    report["feature_stats"] = {
        "total_features": len(features),
        "recommended_features": len(recommended),
        "unsupported_features": len(unsupported),
        "top_templates": dict(sorted(top_templates.items(), key=lambda kv: kv[1], reverse=True)),
    }
    report["queue_stats"] = {
        "pending": len(queue),
        "skipped_processed": skipped_processed,
        "skipped_retry_exceeded": skipped_retry,
    }
    _bstats = brief_stats(briefs)
    report["brief_stats"] = _bstats
    # 兼容旧字段（测试/CLI 仍读 counts）
    report["counts"] = {
        "raw_records": len(all_records),
        "candidates": len(candidates),
        "features_total": len(features),
        "features_recommended": len(ranked),
        "queue_pending": len(queue),
        "briefs_total": _bstats["total"],
        "briefs_produce": _bstats["produce"],
        "briefs_review": _bstats["review"],
        "briefs_skip": _bstats["skip"],
    }

    if not dry_run:
        _write_json(OPP_DIR / "market-snapshot.json", {"date": date_str, "records": all_records})
        _write_json(OPP_DIR / "candidate-pool.json", candidates)
        _write_json(OPP_DIR / "feature-opportunities.json", features)
        _write_json(OPP_DIR / "opportunity-briefs.json", briefs)
        _write_json(OPP_DIR / "opportunity-queue.json", queue)
        _write_json(OPP_DIR / "crawl-report.json", report)
        if not PROCESSED_PATH.exists():
            _write_json(PROCESSED_PATH, processed)

    return report


def main():
    parser = argparse.ArgumentParser(description="机会抓取 runner")
    parser.add_argument("--mode", choices=["once"], default="once")
    parser.add_argument("--regions", default="", help="逗号分隔，如 CN,US,JP；空则用默认集")
    parser.add_argument("--platforms", default="", help="逗号分隔，如 app_store,google_play")
    parser.add_argument("--entry-types", default="", help="逗号分隔，如 top_free,search；空则全部")
    parser.add_argument("--categories", default="", help="逗号分隔，如 photo,entertainment；空则用默认集")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--date", default=None, help="YYYYMMDD；默认今天")
    parser.add_argument("--dry-run", action="store_true", help="不写盘，仅执行与汇总")
    args = parser.parse_args()

    regions = [r.strip().upper() for r in args.regions.split(",") if r.strip()] or None
    platforms = [p.strip() for p in args.platforms.split(",") if p.strip()] or None
    entry_types = [e.strip() for e in args.entry_types.split(",") if e.strip()] or None
    categories = [c.strip() for c in args.categories.split(",") if c.strip()] or None

    report = run_once(
        regions=regions, platforms=platforms, entry_types=entry_types, categories=categories,
        limit=args.limit, date_str=args.date, dry_run=args.dry_run,
    )
    s = report["summary"]
    c = report.get("counts", {})
    print(f"[crawl] dry_run={report['dry_run']} tasks={s['tasks']} success={s['success']} "
          f"failed={s['failed']} skipped={s['skipped']} cached={s['cached']}")
    print(f"[crawl] candidates={c.get('candidates')} features={c.get('features_total')} "
          f"recommended={c.get('features_recommended')} queue_pending={c.get('queue_pending')}")
    if args.dry_run:
        print("[crawl] dry-run：未写盘")


if __name__ == "__main__":
    main()

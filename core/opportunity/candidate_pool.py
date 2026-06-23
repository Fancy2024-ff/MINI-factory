"""core.opportunity.candidate_pool — 候选 App 标准化 + 去重合并（正式版）。

把多平台/多地区/多类目/多入口抓到的原始 App 记录合并成统一候选池。

canonical_key（去重主键，最终版）：
  - App Store：source + 稳定 ID（trackId/bundleId），即 `app_store:<id>`
  - Google Play：source + appId/package name，即 `google_play:<package>`
  - 无稳定 ID 才 fallback：`<source>:name:<normalized_name>:<developer>`
  跨平台同一逻辑 App 用各自平台 ID，不强行合并（避免误并）。

去重区分三种情况：
  1. 同一 App 跨地区重复出现 → 合并，regions/per_region_ranks/region_entries 累积
  2. 同一 App 在不同榜单/搜索入口重复出现 → 合并，entry_types/seen_in 累积
  3. 真正不同 App 但名字相近 → 因 ID 不同而 canonical_key 不同，不误并

合并后保留：appear_count / best_rank / regions / categories / entry_types /
  keywords / per_region_ranks / region_entries（per-region details）/ seen_in。

排序聚合信号（build_candidate_pool）：(appear_count, rating, downloads) 降序——
  出现越广（多地区+多入口）、评分越高、量级越大者排前。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_name(name: str) -> str:
    """归一化 App 名用于无 ID 兜底去重：小写、去标点、压空白。"""
    n = (name or "").strip().lower()
    n = re.sub(r"[^\w一-鿿]+", " ", n)  # 保留中英文与数字
    return re.sub(r"\s+", " ", n).strip()


def canonical_key(record: dict) -> str:
    """计算候选的 canonical_key（最终版去重主键）。

    App Store 用 `app_store:<trackId/bundleId>`；Google Play 用 `google_play:<package>`；
    无稳定 ID 时 fallback `<source>:name:<normalized_name>:<developer>`。
    """
    source = (record.get("source") or "").strip()
    app_id = (record.get("app_id") or "").strip()
    if source and app_id:
        return f"{source}:{app_id}"
    name = normalize_name(record.get("name", ""))
    dev = normalize_name(record.get("developer", ""))
    return f"{source}:name:{name}:{dev}"


def _empty_candidate(key: str, record: dict) -> dict:
    source = record.get("source") or ""
    app_id = record.get("app_id") or ""
    now = _now_iso()
    return {
        "canonical_key": key,
        "source_ids": {"app_store": "", "google_play": ""},
        "name": record.get("name", ""),
        "name_cn": record.get("name_cn", "") or "",
        "developer": record.get("developer", "") or "",
        "sources": [],
        "regions": [],
        "categories": [],
        "entry_types": [],
        "keywords": [],
        "best_rank": None,
        "appear_count": 0,
        # --- provenance（可追溯各地区原始信息）---
        # region_entries: 每条来源的细粒度记录（平台/地区/入口/类目/关键词/名次）
        "region_entries": [],
        # per_region_ranks: {region: 该地区见过的最佳名次}
        "per_region_ranks": {},
        # seen_in: {platform/region/entry_type 组合标识} 去重集合（列表形式持久化）
        "seen_in": [],
        "downloads": record.get("downloads", 0) or 0,
        "rating": record.get("rating", 0) or 0.0,
        # rating_available 区分「真低分 0」与「数据源无评分」（榜单 RSS 无评分）。
        "rating_available": bool((record.get("rating", 0) or 0) > 0),
        "review_count": record.get("review_count", 0) or 0,
        "description": record.get("description", "") or "",
        "features": list(record.get("features", []) or []),
        "monetization": record.get("monetization", "") or "unknown",
        "first_seen_at": now,
        "last_seen_at": now,
    }


def _merge_unique(target: list, values) -> None:
    for v in values if isinstance(values, (list, tuple, set)) else [values]:
        if v and v not in target:
            target.append(v)


def merge_record(pool: dict[str, dict], record: dict) -> dict:
    """把一条原始抓取记录合并进 pool（以 canonical_key 为键），返回该候选。

    record 约定字段：source, app_id, name, name_cn, developer, region,
    category, entry_type, keyword(s), rank, downloads, rating, review_count,
    description, features, monetization。
    """
    key = canonical_key(record)
    cand = pool.get(key)
    if cand is None:
        cand = _empty_candidate(key, record)
        pool[key] = cand

    source = record.get("source") or ""
    app_id = record.get("app_id") or ""
    if source in ("app_store", "google_play") and app_id and not cand["source_ids"].get(source):
        cand["source_ids"][source] = app_id

    _merge_unique(cand["sources"], source)
    _merge_unique(cand["regions"], record.get("region"))
    _merge_unique(cand["categories"], record.get("category"))
    _merge_unique(cand["entry_types"], record.get("entry_type"))
    kws = record.get("keywords") or record.get("keyword")
    _merge_unique(cand["keywords"], kws)

    rank = record.get("rank")
    if isinstance(rank, int) and rank > 0:
        cand["best_rank"] = rank if cand["best_rank"] is None else min(cand["best_rank"], rank)

    # --- provenance：保留各地区/入口的原始可追溯信息 ---
    region = record.get("region") or ""
    entry_type = record.get("entry_type") or ""
    platform = source
    cand["region_entries"].append({
        "platform": platform,
        "region": region,
        "entry_type": entry_type,
        "category": record.get("category") or "",
        "keywords": list(record.get("keywords") or ([record["keyword"]] if record.get("keyword") else [])),
        "rank": rank if isinstance(rank, int) and rank > 0 else None,
        "rank_kind": record.get("rank_kind") or "",
    })
    # seen_in：平台/地区/入口 组合去重标识
    combo = f"{platform}:{region}:{entry_type}"
    _merge_unique(cand["seen_in"], combo)
    # per_region_ranks：该地区见过的最佳名次
    if region and isinstance(rank, int) and rank > 0:
        prev = cand["per_region_ranks"].get(region)
        cand["per_region_ranks"][region] = rank if prev is None else min(prev, rank)

    # 取信号最大值（多地区取最强热度）
    cand["downloads"] = max(cand["downloads"], record.get("downloads", 0) or 0)
    cand["rating"] = max(cand["rating"], record.get("rating", 0) or 0.0)
    cand["review_count"] = max(cand["review_count"], record.get("review_count", 0) or 0)
    # 只要任一来源带到正评分，就标记评分可用（区分缺失与真 0 分）。
    if (record.get("rating", 0) or 0) > 0:
        cand["rating_available"] = True

    # 补全可读字段（首个非空优先保留）
    if not cand["name_cn"] and record.get("name_cn"):
        cand["name_cn"] = record["name_cn"]
    if not cand["developer"] and record.get("developer"):
        cand["developer"] = record["developer"]
    if len(record.get("description", "") or "") > len(cand["description"]):
        cand["description"] = record["description"]
    _merge_unique(cand["features"], record.get("features") or [])
    if cand["monetization"] in ("", "unknown") and record.get("monetization"):
        cand["monetization"] = record["monetization"]

    cand["appear_count"] += 1
    cand["last_seen_at"] = _now_iso()
    return cand


def build_candidate_pool(records: list[dict]) -> list[dict]:
    """把原始抓取记录列表合并成候选池列表，按热度（appear_count, rating）排序。"""
    pool: dict[str, dict] = {}
    for rec in records:
        merge_record(pool, rec)
    candidates = list(pool.values())
    candidates.sort(
        key=lambda c: (c["appear_count"], c["rating"], c["downloads"]),
        reverse=True,
    )
    return candidates

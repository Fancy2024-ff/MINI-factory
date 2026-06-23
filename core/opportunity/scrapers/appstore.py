"""
App Store data scraper（机会发现：仅使用 Apple 自身公开源）。

入口（entry_type）：
- search：iTunes Search API（Apple 公开，关键词搜索，非榜单；best_rank 是搜索结果位置）。
- top_free / top_grossing：Apple RSS 榜单（Apple 公开，真实热门排名；best_rank 是榜单名次）。

数据源边界：只走 Apple 自身公开源（iTunes Search API + Apple RSS）。
不使用任何第三方榜单/评论数据源（已移除七麦 Qimai）。
关键词来自 crawl_config（单一事实源）。所有请求经 fetch_policy（统一 UA / timeout / pace / retry）。
"""

from __future__ import annotations

from core.opportunity import crawl_config as cfg
from core.opportunity import fetch_policy
from core.shared.models import AppInfo, AppSource

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
# Apple RSS 榜单（免费，无需 key）。feed 类型：topfreeapplications / topgrossingapplications。
# genre URL：按类目真实生效，避免不同类目抓到同一批全站榜单。
APPLE_RSS_URL = "https://itunes.apple.com/{country}/rss/{feed}/limit={limit}/genre={genre}/json"
_RSS_FEED = {cfg.TOP_FREE: "topfreeapplications", cfg.TOP_GROSSING: "topgrossingapplications"}


class AppStoreGenreUnsupported(Exception):
    """category 无 Apple genre 映射，榜单入口不可用（由 crawl_runner 标 unsupported）。"""


def fetch_ai_apps_appstore(
    category: str = "ai",
    limit: int = 50,
    country: str = "us",
    entry_type: str = cfg.SEARCH,
    keywords: list[str] | None = None,
) -> list[AppInfo]:
    """抓取 App Store 数据（仅 Apple 自身源）。

    entry_type=search → iTunes Search（关键词）；top_free/top_grossing → Apple RSS 榜单（按 genre）。
    keywords 为空时从 crawl_config 取该 category 的关键词（单一事实源）。
    """
    if entry_type in (cfg.TOP_FREE, cfg.TOP_GROSSING):
        return _fetch_via_rss(entry_type, limit, country, category)

    terms = keywords or cfg.keywords_for_category(category)
    return _fetch_via_itunes(terms, limit, country)


def appstore_rss_url(entry_type: str, limit: int, country: str, category: str) -> str:
    """构造 Apple RSS 榜单 URL（含 genre）。无 genre 映射抛 AppStoreGenreUnsupported。"""
    genre = cfg.appstore_genre(category)
    if not genre:
        raise AppStoreGenreUnsupported(f"App Store 类目 {category} 无 genre 映射，榜单不可用")
    return APPLE_RSS_URL.format(country=country, feed=_RSS_FEED[entry_type], limit=limit, genre=genre)


def _fetch_via_itunes(search_terms: list[str], limit: int, country: str) -> list[AppInfo]:
    """iTunes Search API（免费）。每个关键词请求之间 pace，单请求级限速。"""
    if not search_terms:
        return []
    seen_ids: set[str] = set()
    apps: list[AppInfo] = []
    per_term_limit = max(10, limit // len(search_terms))

    for idx, term in enumerate(search_terms):
        if len(apps) >= limit:
            break
        if idx > 0:
            fetch_policy.pace()  # 多关键词循环：每次请求之间也限速
        try:
            data = fetch_policy.with_retry(
                lambda: fetch_policy.get_json(
                    ITUNES_SEARCH_URL,
                    params={"term": term, "country": country, "media": "software", "limit": per_term_limit},
                )
            )
        except Exception as e:  # noqa: BLE001
            print(f"[iTunes] Search failed for '{term}' ({country}): {e}")
            continue

        for item in data.get("results", []):
            app_id = item.get("bundleId", "") or str(item.get("trackId", ""))
            if not app_id or app_id in seen_ids:
                continue
            seen_ids.add(app_id)
            rating_count = item.get("userRatingCount", 0) or 0
            apps.append(AppInfo(
                name=item.get("trackName", ""),
                app_id=app_id,
                source=AppSource.APP_STORE,
                category=item.get("primaryGenreName", ""),
                description=item.get("description", "")[:500],
                downloads=rating_count * 50,
                rating=float(item.get("averageUserRating", 0) or 0),
                review_count=rating_count,
                features=_extract_features(item.get("description", "")),
                developer=item.get("artistName", ""),
            ))
    apps.sort(key=lambda a: a.downloads, reverse=True)
    return apps[:limit]


def _fetch_via_rss(entry_type: str, limit: int, country: str, category: str) -> list[AppInfo]:
    """Apple RSS 榜单（top_free / top_grossing），按 category→genre 真实生效。

    best_rank = 榜单名次。无 genre 映射抛 AppStoreGenreUnsupported（不假装成功）。
    """
    url = appstore_rss_url(entry_type, limit, country, category)
    data = fetch_policy.with_retry(lambda: fetch_policy.get_json(url))
    entries = (data.get("feed", {}) or {}).get("entry", []) or []
    if isinstance(entries, dict):
        entries = [entries]

    apps: list[AppInfo] = []
    for item in entries:
        name = _rss_label(item.get("im:name"))
        app_id = _rss_app_id(item)
        if not app_id:
            continue
        apps.append(AppInfo(
            name=name,
            app_id=app_id,
            source=AppSource.APP_STORE,
            category=_rss_label(item.get("category", {}).get("attributes", {}).get("label", "")) if isinstance(item.get("category"), dict) else "",
            description=_rss_label(item.get("summary", "")),
            downloads=0,
            rating=0.0,
            developer=_rss_label(item.get("im:artist")),
        ))
    return apps[:limit]


def _rss_label(node) -> str:
    if isinstance(node, dict):
        return node.get("label", "") or ""
    return node or ""


def _rss_app_id(item: dict) -> str:
    """从 RSS entry 提取 App ID（id 节点的 im:id 属性，或 URL 末段）。"""
    idnode = item.get("id", {})
    if isinstance(idnode, dict):
        attrs = idnode.get("attributes", {}) or {}
        if attrs.get("im:id"):
            return str(attrs["im:id"])
        label = idnode.get("label", "") or ""
        if "/id" in label:
            return label.rsplit("/id", 1)[-1].split("?")[0]
    return ""


def _get_search_terms(category: str) -> list[str]:
    """[兼容 fallback] 旧关键词表。主路径用 crawl_config.keywords_for_category。"""
    return cfg.keywords_for_category(category)


def _extract_features(description: str) -> list[str]:
    features = []
    for line in description.split("\n"):
        line = line.strip()
        if line.startswith(("•", "-", "✓", "✔", "★", "·")) and len(line) > 5:
            features.append(line.lstrip("•-✓✔★· "))
            if len(features) >= 5:
                break
    return features

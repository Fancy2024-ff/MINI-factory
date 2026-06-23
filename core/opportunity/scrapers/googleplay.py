"""
Google Play data scraper（机会发现：Google Play 数据源）。

入口（entry_type）：
- search：google-play-scraper search（关键词；best_rank = 搜索结果位置）。
- top_free：google-play-scraper collection 榜单（若库支持；best_rank = 榜单名次）。
- top_grossing：v1 暂不稳定支持，由 crawl_config 标 unsupported，crawl_runner 显式跳过。

country 真实生效：search / collection / SensorTower 都使用传入 country，不写死 US。
关键词来自 crawl_config（单一事实源）。

限制说明：google-play-scraper 第三方库不暴露自定义 User-Agent（底层自带 UA），
故本平台的 UA 统一策略仅作用于 SensorTower 等 httpx 直连请求；库请求依赖其默认行为。
"""

from __future__ import annotations

from core.runtime.config import SENSORTOWER_API_KEY
from core.opportunity import crawl_config as cfg
from core.opportunity import fetch_policy
from core.shared.models import AppInfo, AppSource

try:
    from google_play_scraper import search as gp_search
    HAS_GP_SCRAPER = True
except ImportError:
    HAS_GP_SCRAPER = False

try:
    from google_play_scraper import collection as gp_collection  # type: ignore
    HAS_GP_COLLECTION = True
except ImportError:
    HAS_GP_COLLECTION = False


def fetch_ai_apps_googleplay(
    category: str = "ai",
    limit: int = 50,
    country: str = "us",
    entry_type: str = cfg.SEARCH,
    keywords: list[str] | None = None,
) -> list[AppInfo]:
    """抓取 Google Play 数据。country 真实生效（不写死 US）。"""
    if SENSORTOWER_API_KEY:
        st_results = _fetch_via_sensortower(category, limit, country)
        if st_results:
            return st_results

    if entry_type == cfg.TOP_FREE and HAS_GP_COLLECTION:
        results = _fetch_top_free(category, limit, country)
        if results:
            return results

    if HAS_GP_SCRAPER:
        terms = keywords or cfg.keywords_for_category(category)
        return _fetch_via_scraper(terms, limit, country)

    return []


def _lang_for_country(country: str) -> str:
    """地区 → 语言（粗映射，影响 Google Play 返回内容地域性）。"""
    return {
        "us": "en", "jp": "ja", "kr": "ko", "tw": "zh-TW", "hk": "zh-HK",
        "sg": "en", "in": "en", "id": "id", "br": "pt",
    }.get(country.lower(), "en")


def _fetch_via_scraper(search_terms: list[str], limit: int, country: str) -> list[AppInfo]:
    """google-play-scraper search。country/lang 真实传入，每关键词请求间 pace。"""
    if not search_terms:
        return []
    lang = _lang_for_country(country)
    seen_ids: set[str] = set()
    apps: list[AppInfo] = []
    per_term_limit = max(10, limit // len(search_terms))

    for idx, term in enumerate(search_terms):
        if len(apps) >= limit:
            break
        if idx > 0:
            fetch_policy.pace()
        try:
            results = gp_search(term, lang=lang, country=country.lower(), n_hits=per_term_limit)
        except Exception as e:  # noqa: BLE001
            print(f"[GooglePlay] Search failed for '{term}' ({country}): {e}")
            continue
        for item in results:
            app_id = item.get("appId", "")
            if not app_id or app_id in seen_ids:
                continue
            seen_ids.add(app_id)
            apps.append(_to_appinfo(item, default_category="ai"))
    apps.sort(key=lambda a: a.downloads, reverse=True)
    return apps[:limit]


def _fetch_top_free(category: str, limit: int, country: str) -> list[AppInfo]:
    """google-play-scraper collection 榜单（top_free）。库不支持时返回空，由上层降级。"""
    try:
        results = gp_collection(
            collection="TOP_FREE",
            category=_map_category(category),
            country=country.lower(),
            lang=_lang_for_country(country),
            n_hits=limit,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[GooglePlay] TOP_FREE collection failed ({country}): {e}")
        return []
    apps = []
    for item in results:
        app_id = item.get("appId", "")
        if app_id:
            apps.append(_to_appinfo(item, default_category=category))
    return apps[:limit]


def _to_appinfo(item: dict, default_category: str) -> AppInfo:
    return AppInfo(
        name=item.get("title", ""),
        app_id=item.get("appId", ""),
        source=AppSource.GOOGLE_PLAY,
        category=item.get("genre", default_category),
        description=(item.get("description", "") or "")[:500],
        downloads=_parse_installs(item.get("installs", "0")),
        rating=float(item.get("score", 0) or 0),
        developer=item.get("developer", "") or "",
        features=_extract_features(item.get("description", "") or ""),
    )


def _parse_installs(installs_str) -> int:
    if isinstance(installs_str, int):
        return installs_str
    try:
        return int(str(installs_str).replace(",", "").replace("+", "").strip())
    except (ValueError, TypeError):
        return 0


def _get_search_terms(category: str) -> list[str]:
    """[兼容 fallback] 主路径用 crawl_config.keywords_for_category。"""
    return cfg.keywords_for_category(category)


def _extract_features(description: str) -> list[str]:
    features = []
    for line in description.split("\n"):
        line = line.strip()
        if line.startswith(("•", "-", "✓", "✔", "★", "·", "►")) and len(line) > 5:
            features.append(line.lstrip("•-✓✔★·► "))
            if len(features) >= 5:
                break
    return features


def _fetch_via_sensortower(category: str, limit: int, country: str) -> list[AppInfo]:
    """SensorTower API。country 真实传入（大写）。"""
    try:
        data = fetch_policy.get_json(
            "https://api.sensortower.com/v1/android/rankings/get_top_apps",
            params={"auth_token": SENSORTOWER_API_KEY, "category": _map_category(category),
                    "country": country.upper(), "limit": limit},
        )
        apps = []
        for item in data:
            apps.append(AppInfo(
                name=item.get("name", ""),
                app_id=item.get("app_id", ""),
                source=AppSource.GOOGLE_PLAY,
                category=category,
                description=item.get("description", ""),
                downloads=item.get("downloads_estimate", 0),
                rating=float(item.get("rating", 0) or 0),
            ))
        return apps
    except Exception as e:  # noqa: BLE001
        print(f"[SensorTower] API fetch failed ({country}): {e}")
        return []


def _map_category(category: str) -> str:
    return {"ai": "PRODUCTIVITY", "photo": "PHOTOGRAPHY", "education": "EDUCATION",
            "utilities": "TOOLS", "entertainment": "ENTERTAINMENT"}.get(category, "PRODUCTIVITY")

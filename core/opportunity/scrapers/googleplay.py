"""
Google Play data scraper（机会发现：仅使用 Google Play 自身公开页面，直爬实现）。

数据源边界：只走 Google Play 自身公开可访问页面（store.google.com / play.google.com），
本项目自己用 httpx + BeautifulSoup 直爬，**不依赖 google-play-scraper 第三方库**，
**不使用 SensorTower 等第三方榜单源**。

入口（entry_type）：
- search：Google Play 搜索结果页（关键词；best_rank = 搜索结果位置）。country/hl 真实生效。
- top_free：Google Play 排行榜页（榜单名次）。直爬可稳定取到时启用。
- top_grossing：当前直爬不稳定，明确 unsupported（见 GP_TOP_GROSSING_REASON），不伪装完成。

直爬说明：Google Play 前端是动态渲染，公开 HTML 里 App 信息以
`/store/apps/details?id=<package>` 链接 + 邻近文本形式出现。我们解析锚点提取 package
与展示名，按出现顺序作为 rank。解析失败/被限流时降级返回空（由 crawl_runner 记 failed）。
"""

from __future__ import annotations

import re
from urllib.parse import quote

from bs4 import BeautifulSoup

from core.opportunity import crawl_config as cfg
from core.opportunity import fetch_policy
from core.shared.models import AppInfo, AppSource

GP_SEARCH_URL = "https://play.google.com/store/search"
# top_grossing 直爬不稳定：Google Play 榜单页强依赖动态渲染，公开 HTML 难稳定取榜单名次。
GP_TOP_GROSSING_REASON = "Google Play top_grossing 直爬不稳定，公开页面无稳定榜单结构，标记 unsupported"

_DETAILS_RE = re.compile(r"/store/apps/details\?id=([a-zA-Z0-9._]+)")


def _lang_for_country(country: str) -> str:
    """地区 → 界面语言（hl），影响返回内容地域性。"""
    return {
        "us": "en", "jp": "ja", "kr": "ko", "tw": "zh-TW", "hk": "zh-HK",
        "sg": "en", "in": "en", "id": "id", "br": "pt",
    }.get(country.lower(), "en")


def fetch_ai_apps_googleplay(
    category: str = "ai",
    limit: int = 50,
    country: str = "us",
    entry_type: str = cfg.SEARCH,
    keywords: list[str] | None = None,
) -> list[AppInfo]:
    """抓取 Google Play 数据（仅 Google Play 自身页面，httpx+bs4 直爬）。

    country / hl 真实生效，不写死 US。top_grossing 抛 unsupported（由上层标记跳过）。
    """
    if entry_type == cfg.TOP_GROSSING:
        # 不伪装完成：直接抛，crawl_runner 据此标 failed/unsupported 并记原因。
        raise GooglePlayUnsupportedEntry(GP_TOP_GROSSING_REASON)

    terms = keywords or cfg.keywords_for_category(category)
    return _fetch_via_search(terms, limit, country)


class GooglePlayUnsupportedEntry(Exception):
    """Google Play 不支持的入口（如 top_grossing 直爬不稳定）。"""


def _fetch_via_search(search_terms: list[str], limit: int, country: str) -> list[AppInfo]:
    """直爬 Google Play 搜索结果页。每个关键词请求之间 pace（单请求级限速）。"""
    if not search_terms:
        return []
    hl = _lang_for_country(country)
    gl = country.lower()
    seen: set[str] = set()
    apps: list[AppInfo] = []
    per_term = max(5, limit // len(search_terms))

    for idx, term in enumerate(search_terms):
        if len(apps) >= limit:
            break
        if idx > 0:
            fetch_policy.pace()
        url = f"{GP_SEARCH_URL}?q={quote(term)}&c=apps&hl={hl}&gl={gl}"
        try:
            html = fetch_policy.with_retry(lambda: fetch_policy.get_text(url))
        except Exception as e:  # noqa: BLE001
            print(f"[GooglePlay] search failed for '{term}' ({country}): {type(e).__name__}")
            continue
        for app in _parse_search_html(html, per_term):
            pkg = app.app_id
            if not pkg or pkg in seen:
                continue
            seen.add(pkg)
            apps.append(app)
    return apps[:limit]


def _parse_search_html(html: str, limit: int) -> list[AppInfo]:
    """从搜索页 HTML 解析 App：details 链接拿 package，锚点文本/aria-label 拿展示名。"""
    soup = BeautifulSoup(html or "", "html.parser")
    out: list[AppInfo] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        m = _DETAILS_RE.search(a["href"])
        if not m:
            continue
        pkg = m.group(1)
        if pkg in seen:
            continue
        # 展示名：锚点内文本，或子节点 title/aria-label
        name = (a.get("aria-label") or a.get_text(" ", strip=True) or "").strip()
        if not name:
            node = a.find(attrs={"title": True})
            name = (node.get("title") if node else "") or ""
        name = name.strip()
        if not name or len(name) > 80:
            # 跳过空名/过长聚合文本（多为非应用卡片）
            continue
        seen.add(pkg)
        out.append(AppInfo(
            name=name,
            app_id=pkg,
            source=AppSource.GOOGLE_PLAY,
            category="",
            description="",
            downloads=0,
            rating=0.0,
            developer="",
        ))
        if len(out) >= limit:
            break
    return out

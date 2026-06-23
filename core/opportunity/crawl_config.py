"""core.opportunity.crawl_config — 抓取地区/平台/类目/关键词/节奏配置（单一事实源）。

设计原则：
- region 支持状态显式登记（supported / appstore_only / unsupported），不静默失败。
- CN：App Store 中国区可抓；Google Play 在 CN 不可用，显式标 unsupported，不硬爬。
- 抓取节奏参数集中在此（限速/jitter/timeout/retry/间隔/上限），合规低频，
  不做代理池/账号绕封。
"""

from __future__ import annotations

# --- 地区支持状态 ---------------------------------------------------------
# 每个地区记录在各平台的可抓状态，crawl-report 据此写 success/skip/unsupported。
SUPPORTED = "supported"
UNSUPPORTED = "unsupported"  # 平台在该地区不可用/不稳定，跳过且记录原因

REGION_SUPPORT: dict[str, dict[str, str]] = {
    "CN": {"app_store": SUPPORTED, "google_play": UNSUPPORTED},
    "US": {"app_store": SUPPORTED, "google_play": SUPPORTED},
    "JP": {"app_store": SUPPORTED, "google_play": SUPPORTED},
    "KR": {"app_store": SUPPORTED, "google_play": SUPPORTED},
    "TW": {"app_store": SUPPORTED, "google_play": SUPPORTED},
    "HK": {"app_store": SUPPORTED, "google_play": SUPPORTED},
    "SG": {"app_store": SUPPORTED, "google_play": SUPPORTED},
    "IN": {"app_store": SUPPORTED, "google_play": SUPPORTED},
    "ID": {"app_store": SUPPORTED, "google_play": SUPPORTED},
    "BR": {"app_store": SUPPORTED, "google_play": SUPPORTED},
}

# Google Play 在中国大陆不可用/数据不稳定，显式记录跳过原因（不硬爬）。
GOOGLE_PLAY_UNSUPPORTED_REASON = (
    "Google Play 在 CN 不可用/数据不稳定，第一版不硬爬，CN 以 App Store 中国区为主"
)

# 第一版默认地区集（含 CN）。
DEFAULT_APP_STORE_REGIONS = ["CN", "US", "JP", "KR", "TW", "HK", "SG", "IN", "ID", "BR"]
DEFAULT_GOOGLE_PLAY_REGIONS = ["US", "JP", "KR", "TW", "HK", "SG", "IN", "ID", "BR"]

PLATFORMS = ["app_store", "google_play"]

# --- 抓取入口类型 ---------------------------------------------------------
# 区分「榜单」与「搜索」：产品主线是从热门榜单发现机会，search 仅作补充信号。
TOP_FREE = "top_free"
TOP_GROSSING = "top_grossing"
SEARCH = "search"
ENTRY_TYPES = [TOP_FREE, TOP_GROSSING, SEARCH]

# 各平台对 entry_type 的支持能力（v1）。unsupported 的入口显式跳过并记录，不静默。
# App Store：Apple RSS 提供 top_free/top_grossing 榜单；search 走 iTunes Search（均 Apple 自身源）。
# Google Play：自研 httpx+bs4 直爬 search 稳定；榜单页（top_free/top_grossing）动态渲染难稳定直爬，
#   标 unsupported，不伪装完成（原因见 crawl-report）。
PLATFORM_ENTRY_SUPPORT: dict[str, dict[str, str]] = {
    "app_store": {TOP_FREE: SUPPORTED, TOP_GROSSING: SUPPORTED, SEARCH: SUPPORTED},
    "google_play": {TOP_FREE: UNSUPPORTED, TOP_GROSSING: UNSUPPORTED, SEARCH: SUPPORTED},
}

GOOGLE_PLAY_TOP_GROSSING_REASON = (
    "Google Play 榜单页动态渲染，自研直爬无稳定榜单结构，top_grossing 标 unsupported"
)
GOOGLE_PLAY_TOP_FREE_REASON = (
    "Google Play 榜单页动态渲染，自研直爬无稳定榜单结构，top_free 标 unsupported；search 入口可用"
)

# --- 类目 / 关键词 --------------------------------------------------------
# 抓取面向「可拆成小程序的轻量能力」，类目复用 scrapers 已支持的 category。
CATEGORIES = ["photo", "ai", "entertainment", "utilities"]

# App Store category -> Apple genre id（榜单 RSS 按类目真实生效，避免全站同榜）。
# 6008 Photo & Video / 6016 Entertainment / 6002 Utilities / 6017 Education /
# 6007 Productivity（ai 类暂映射到 Productivity，说明见下）。
APP_STORE_GENRE: dict[str, str] = {
    "photo": "6008",
    "entertainment": "6016",
    "utilities": "6002",
    "education": "6017",
    "ai": "6007",  # App Store 无独立 AI 榜，映射到 Productivity(6007)
    "productivity": "6007",
}

# 每个类目的搜索关键词（scrapers 内部也有 term map，此处作为可复盘记录）。
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "photo": ["AI photo editor", "AI avatar", "background remover", "photo enhancer", "老照片修复"],
    "ai": ["AI writing", "AI translate", "AI summarize", "文案生成"],
    "entertainment": ["meme maker", "sticker maker", "祝福视频", "搞笑视频"],
    "utilities": ["poster maker", "cover maker", "海报生成", "封面"],
}

# --- 抓取节奏（合规低频，可持续，可复盘）---------------------------------
CRAWL_PARAMS = {
    "per_request_limit": 20,        # 单次请求条数上限
    "request_timeout": 15,          # 单请求超时（秒）
    "min_interval_seconds": 1.5,    # 任务（平台×地区×类目）间最小间隔
    "jitter_seconds": 1.0,          # 随机 jitter 上限，错峰
    "max_retries": 3,               # 指数退避重试次数
    "retry_base_delay": 2.0,        # 退避基数（秒）：base * 2**attempt
    "max_tasks_per_run": 60,        # 单次抓取最大任务数，防爆刷
    "user_agent": "MiniAppFactory-OpportunityCrawler/1.0 (+contact: ops@miniforge.local)",
    "use_cache": True,              # 命中当日 snapshot 则跳过请求
}


def regions_for_platform(platform: str, requested: list[str] | None = None) -> list[tuple[str, str]]:
    """返回 (region, status) 列表。requested 为空用默认集。

    status ∈ {supported, unsupported}；unsupported 由调用方跳过并记录原因。
    """
    if platform == "app_store":
        base = requested or DEFAULT_APP_STORE_REGIONS
    elif platform == "google_play":
        base = requested or DEFAULT_GOOGLE_PLAY_REGIONS
    else:
        return []
    out: list[tuple[str, str]] = []
    for r in base:
        status = REGION_SUPPORT.get(r, {}).get(platform, UNSUPPORTED)
        out.append((r, status))
    return out


def skip_reason(platform: str, region: str) -> str:
    if platform == "google_play" and region == "CN":
        return GOOGLE_PLAY_UNSUPPORTED_REASON
    return f"{platform} 在地区 {region} 不在支持列表，跳过"


def entry_type_status(platform: str, entry_type: str) -> str:
    """返回某平台对某 entry_type 的支持状态（supported/unsupported）。"""
    return PLATFORM_ENTRY_SUPPORT.get(platform, {}).get(entry_type, UNSUPPORTED)


def entry_skip_reason(platform: str, entry_type: str) -> str:
    if platform == "google_play" and entry_type == TOP_GROSSING:
        return GOOGLE_PLAY_TOP_GROSSING_REASON
    if platform == "google_play" and entry_type == TOP_FREE:
        return GOOGLE_PLAY_TOP_FREE_REASON
    return f"{platform} 暂不支持入口 {entry_type}，跳过"


def keywords_for_category(category: str) -> list[str]:
    """关键词单一事实源：scraper 不再自己决定搜什么，由此处提供。"""
    return CATEGORY_KEYWORDS.get(category, CATEGORY_KEYWORDS.get("ai", []))


def appstore_genre(category: str) -> str | None:
    """App Store category → Apple genre id；无映射返回 None（榜单入口据此标 unsupported）。"""
    return APP_STORE_GENRE.get(category)


def capability_summary() -> dict:
    """数据源能力说明（写入 crawl-report，给运营/老板看懂）。"""
    return {
        "app_store": {
            "regions_supported": [r for r in DEFAULT_APP_STORE_REGIONS
                                  if REGION_SUPPORT.get(r, {}).get("app_store") == SUPPORTED],
            "cn": "supported",
            "entry_types": {k: v for k, v in PLATFORM_ENTRY_SUPPORT["app_store"].items()},
            "category_genre_map": dict(APP_STORE_GENRE),
        },
        "google_play": {
            "regions_supported": [r for r in DEFAULT_GOOGLE_PLAY_REGIONS
                                  if REGION_SUPPORT.get(r, {}).get("google_play") == SUPPORTED],
            "cn": "unsupported",
            "cn_reason": GOOGLE_PLAY_UNSUPPORTED_REASON,
            "entry_types": {k: v for k, v in PLATFORM_ENTRY_SUPPORT["google_play"].items()},
        },
    }

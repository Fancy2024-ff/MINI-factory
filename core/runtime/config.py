"""core.runtime.config — 全局配置（单一事实源）。

所有路径、密钥、外部服务地址从这里读，不允许各模块各自 os.getenv 散落。
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Paths — PROJECT_ROOT = repo 根（core/runtime/config.py -> parents[2]）
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
APPS_DIR = DATA_DIR / "apps"
PRDS_DIR = DATA_DIR / "prds"
PROJECTS_DIR = DATA_DIR / "projects"
REPORTS_DIR = DATA_DIR / "reports"

# LLM
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "")
LLM_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-4-6")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))

# Data sources：仅使用 App Store / Google Play 自身公开源，不接第三方榜单数据源
# （已移除 QIMAI / SENSORTOWER）。抓取实现见 core/opportunity/scrapers。

# Image generation provider（图片生成中转站；真实 key 只存 env，绝不入代码/产物/前端）。
# 仅后端 core.integrations.image_generation 使用；小程序前端只经 apps/api 调用，
# 不接触 endpoint / key。
IMAGE_GENERATION_ENDPOINT = os.getenv("IMAGE_GENERATION_ENDPOINT", "")
IMAGE_GENERATION_API_KEY = os.getenv("IMAGE_GENERATION_API_KEY", "")
IMAGE_GENERATION_PROVIDER = os.getenv("IMAGE_GENERATION_PROVIDER", "nano-banana")
IMAGE_GENERATION_TIMEOUT_SECONDS = int(os.getenv("IMAGE_GENERATION_TIMEOUT_SECONDS", "60"))

# 生成产物前端的运行时模式（codegen 注入进 src/config/api.ts）。
# - GENERATION_MODE=mock（默认）：生成的小程序走本地 mock 闭环，不依赖外部服务。
# - GENERATION_MODE=api：生成的小程序经 GENERATED_APP_API_BASE 调 apps/api 的真实生成接口。
# GENERATED_APP_API_BASE 必须是 https 绝对域名（微信小程序 uni.request 不支持相对路径，
# 且需加入小程序后台 request 合法域名）。仅当 mode=api 时校验。
GENERATION_MODE = os.getenv("GENERATION_MODE", "mock")
GENERATED_APP_API_BASE = os.getenv("GENERATED_APP_API_BASE", "")

# 激励广告（rewarded video ad）配置：下载高清/去水印结果前的变现门槛。
# codegen 注入进生成小程序的 src/config/ads.ts。未配置时门槛禁用、运行时诚实提示，
# 不硬编码业务真实广告位。adUnitId 形如 adunit-xxxxxxxx（微信流量主后台创建）。
REWARDED_AD_UNIT_ID = os.getenv("REWARDED_AD_UNIT_ID", "")

# NOTE: 不再有 GENERATOR_URL / GENERATOR_API_KEY。
# miniapp 生成的唯一执行真源是 Python core/generator/codegen.py，主链路不调用
# Node generator HTTP 服务（该服务已从正式部署移除，仅作 vitest/Node 兼容工具）。

# Telegram auto-deploy
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "")
# Telegram WebApp 入口 URL（指向部署好的 /tg 页面）。配置后 bot 显示「打开 MiniForge」
# WebApp 按钮；未配置则优雅降级为纯文本/普通按钮。须 https（Telegram WebApp 要求）。
TELEGRAM_WEBAPP_URL = os.getenv("TELEGRAM_WEBAPP_URL", "")
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "")
CLOUDFLARE_PROJECT_NAME = os.getenv("CLOUDFLARE_PROJECT_NAME", "miniforge-app")
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")

# WebApp frontend LLM (used by deployed mini-app)
WEBAPP_LLM_BASE_URL = os.getenv("WEBAPP_LLM_BASE_URL", "https://api.deepseek.com")
WEBAPP_LLM_API_KEY = os.getenv("WEBAPP_LLM_API_KEY", "")
WEBAPP_LLM_MODEL = os.getenv("WEBAPP_LLM_MODEL", "deepseek-chat")

# Mini-program platforms
WECHAT_APPID = os.getenv("WECHAT_APPID", "")
WECHAT_SECRET = os.getenv("WECHAT_SECRET", "")
ALIPAY_APPID = os.getenv("ALIPAY_APPID", "")
DOUYIN_APPID = os.getenv("DOUYIN_APPID", "")

# ── 告警系统（Claude E 任务 2）──────────────────────────────────
# 告警发往的 Telegram chat（复用 TELEGRAM_BOT_TOKEN）。空 = 只写本地日志，不发 TG。
ALERT_TELEGRAM_CHAT_ID = os.getenv("ALERT_TELEGRAM_CHAT_ID", "")
# 同一 alert_key 冷却期（秒）：冷却期内同类告警不重复发。
ALERT_COOLDOWN_SECONDS = int(os.getenv("ALERT_COOLDOWN_SECONDS", "1800"))
# 期望常驻 worker 数：active < 此值 → 部分掉线告警。
ALERT_EXPECTED_WORKERS = int(os.getenv("ALERT_EXPECTED_WORKERS", "2"))
# worker 掉线判定超时（秒）：last_seen 早于 now-该值 视为掉线。
# 必须 >> 心跳间隔(60s)，取 3 倍=180，避免「还没到下一个心跳点」被误判掉线。
ALERT_WORKER_TIMEOUT_SECONDS = int(os.getenv("ALERT_WORKER_TIMEOUT_SECONDS", "180"))
# API 看门狗轮询间隔（秒）：兜底检测「全部 worker 掉线」。
ALERT_API_POLL_SECONDS = int(os.getenv("ALERT_API_POLL_SECONDS", "120"))
# 恢复确认次数：连续 N 次检测到恢复才发「已恢复」，防抖动刷屏。
ALERT_RECOVERY_CONFIRMATIONS = int(os.getenv("ALERT_RECOVERY_CONFIRMATIONS", "2"))

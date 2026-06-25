"""core.publisher.deployed_apps — 汇总「已上架的功能页」清单。

TG 上是「1 个合集站 + N 个功能页」模型，不是 N 个独立小程序。本模块把
内置功能页 + 工厂生成的功能页合并成统一清单，供提交中心列出、预览、配广告。

每条：{route, title, icon, source, preview_url}（preview_url 需站点已部署才有）。
"""

from __future__ import annotations

import json
from pathlib import Path

# 内置功能页（写死在 TG 站 TgHome/route）。route 即天然 key。
BUILTIN_FEATURES = [
    {"route": "/tg/ai-image", "title": "AI 图片生成", "icon": "🖼", "source": "builtin"},
    {"route": "/tg/avatar", "title": "AI 头像", "icon": "🧑‍🎨", "source": "builtin"},
    {"route": "/tg/sticker", "title": "表情包工厂", "icon": "😄", "source": "builtin"},
    {"route": "/tg/pet-talk", "title": "宠物说话", "icon": "🐾", "source": "builtin"},
    {"route": "/tg/bg-remove", "title": "背景去除", "icon": "✂️", "source": "builtin"},
]


def _load_telegram_webapp_url(telegram_auth_path: Path) -> str:
    """读 platform-auth/telegram.json 的 webapp_url；未部署/缺失返回空串。"""
    path = Path(telegram_auth_path)
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    return (data.get("webapp_url") or data.get("deploy_url") or "").rstrip("/")


def _load_generated_features(registry_path: Path) -> list[dict]:
    """读 features.generated.json，转成 {route,title,icon,source} 清单。"""
    path = Path(registry_path)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig") or "[]")
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for f in data:
        if not isinstance(f, dict):
            continue
        fid = f.get("id")
        if not fid:
            continue
        out.append({
            "route": f"/tg/gen/{fid}",
            "title": f.get("title") or fid,
            "icon": f.get("icon") or "✨",
            "source": "generated",
        })
    return out


def list_deployed_features(telegram_auth_path: Path, registry_path: Path) -> list[dict]:
    """已上架功能页清单：内置 + 生成，合并去重（按 route），补 preview_url。

    站点未部署（无 telegram.json/webapp_url）→ 返回空列表（视为尚未上架）。
    """
    webapp_url = _load_telegram_webapp_url(telegram_auth_path)
    if not webapp_url:
        return []

    seen: set[str] = set()
    merged: list[dict] = []
    for feat in [*BUILTIN_FEATURES, *_load_generated_features(registry_path)]:
        route = feat["route"]
        if route in seen:
            continue
        seen.add(route)
        merged.append({**feat, "preview_url": webapp_url + route})
    return merged

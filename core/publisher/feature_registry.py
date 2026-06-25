"""core.publisher.feature_registry — 工厂产物 → 合集功能配置项。

职责：把抓到的 app + classifier 选择，转成合集 registry 的一条配置，
做 schema/白名单/能力兼容校验，append 到 features.generated.json（同 id 跳过）。
task 白名单是「已用真实后端验证过名副其实」的集合（设计 §5 铁律）。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from core.opportunity.classifier import template_to_ability_task

ABILITY_WHITELIST = {"text2img", "img2img"}
TASK_WHITELIST = {"generate_image", "background_remove", "watermark_remove"}

_ICON_BY_ABILITY = {"text2img": "🖼", "img2img": "✂️"}


def _slug(s: str) -> str:
    """转 url-safe slug。纯非 ASCII 输入（如全中文）清洗后为空，
    用原串的稳定短哈希兜底，保证不同输入得到不同 id（避免 id 塌缩、路由冲突）。"""
    original = s or ""
    slug = re.sub(r"[^a-z0-9]+", "-", original.lower()).strip("-")
    if slug:
        return slug
    digest = hashlib.sha1(original.encode("utf-8")).hexdigest()[:8]
    return f"feature-{digest}"


def build_feature_config(feature_key: str, best_app: dict, selection: dict) -> dict:
    """由 feature_key + app + classifier selection 构造一条 feature 配置。"""
    template = selection.get("selected_template", "")
    ability, task = template_to_ability_task(template)
    title = best_app.get("name_cn") or best_app.get("name") or "新功能"
    subtitle = (best_app.get("description_cn") or best_app.get("description") or title)[:40]
    if ability == "img2img":
        inp = {"imageRequired": True, "textRequired": False,
               "acceptedTypes": ["image/png", "image/jpeg", "image/webp"]}
        params = {"task": task, "outputMode": "edited_image"}
        ui = {"uploadLabel": "上传图片", "submitLabel": "开始处理", "resultTitle": title}
    else:
        inp = {"imageRequired": False, "textRequired": True}
        params = {"promptTemplate": "{input}", "outputMode": "generated_image"}
        ui = {"textPlaceholder": "描述你想要的画面", "submitLabel": "立即生成", "resultTitle": title}
    return {
        "id": _slug(feature_key),
        "title": title,
        "icon": _ICON_BY_ABILITY.get(ability, "✨"),
        "ability": ability,
        "task": task,
        "subtitle": subtitle,
        "input": inp,
        "params": params,
        "ui": ui,
        "source": {"type": "factory"},
    }


_REQUIRED = ["id", "title", "icon", "ability", "task", "subtitle", "input", "params", "ui"]


def validate_feature(feat: dict) -> tuple[bool, str]:
    """校验一条 feature 配置。返回 (ok, reason)。reason 为空表示通过。"""
    for k in _REQUIRED:
        if k not in feat or feat[k] in (None, ""):
            return False, f"missing field: {k}"
    if not re.fullmatch(r"[a-z0-9-]+", feat["id"]):
        return False, "id not url-safe"
    if feat["ability"] not in ABILITY_WHITELIST:
        return False, f"ability not in whitelist: {feat['ability']}"
    if feat["task"] not in TASK_WHITELIST:
        return False, f"task not in whitelist: {feat['task']}"
    if not feat.get("ui", {}).get("submitLabel"):
        return False, "missing ui.submitLabel"
    inp = feat.get("input", {})
    if feat["ability"] == "img2img" and not inp.get("imageRequired"):
        return False, "img2img requires input.imageRequired=true"
    if feat["ability"] == "text2img" and not inp.get("textRequired"):
        return False, "text2img requires input.textRequired=true"
    return True, ""


def append_feature(registry_path: Path, feat: dict) -> bool:
    """append 一条 feature 到 generated registry。同 id 已存在则跳过返回 False。"""
    registry_path = Path(registry_path)
    if registry_path.exists():
        data = json.loads(registry_path.read_text(encoding="utf-8") or "[]")
    else:
        data = []
    if any(f.get("id") == feat["id"] for f in data):
        return False
    data.append(feat)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return True

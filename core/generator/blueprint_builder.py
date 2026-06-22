"""core.generator.blueprint_builder — 模板蓝图构建（template config -> blueprint）。

定位（最终架构 capability-domain）：
  介于「模板配置（template.json）」与「代码生成（codegen）」之间的一层。
  template.json 是模板的静态事实源（题材身份、输入字段、结果契约、传播/解锁钩子、
  mock 样例）；blueprint 把它和具体 App 数据（app/prd）合成为 codegen 可直接消费、
  也可写进生成项目供运行时读取的结构化蓝图。

职责：
  build_template_blueprint(template, app, prd_json) -> dict
    1. 读取对应模板的 template.json
    2. 校验基础字段
    3. 合成生成蓝图（结合 app_name / 平台等）
    4. 返回结构化 dict（不写文件）

降级策略：
  - 5 个 viral 模板缺 template.json -> 直接失败（不静默降级，保证传播型质量）
  - base / ai-tool / ai-image / ai-chat 等兜底模板缺配置 -> 返回 fallback blueprint

约束：
  - 不依赖 LLM、不写文件、只返回 dict
  - 业务规则留在 core/generator，runner 只编排
  - 唯一生成执行真源仍是 codegen.py，由它调用本模块
"""

from __future__ import annotations

import json
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent / "src" / "templates"

# 5 个传播型模板：缺 template.json 必须失败，不允许 fallback。
VIRAL_TEMPLATES = {
    "avatar-viral",
    "sticker-viral",
    "pet-talk-viral",
    "funny-video-viral",
    "blessing-video-viral",
}

# generation.ts / result.vue 支持的 previewType（与前端对齐，单一事实源在此登记）。
SUPPORTED_PREVIEW_TYPES = {
    "avatar", "stickerPack", "petVideo", "funnyStoryboard", "blessingCard",
    "image", "text",
}

# --- template.json schema（单一事实源，GeneratorQA 与 codegen 共用）---
# top-level 必需键
REQUIRED_CONFIG_FIELDS = (
    "id", "name_cn", "category", "preview_type",
    "input_fields", "share_hooks", "unlock_hooks", "mock_examples",
)
# input_fields 每项必需键
REQUIRED_INPUT_FIELD_KEYS = ("id", "label", "type", "required", "placeholder")
# input_fields.type 允许值
ALLOWED_INPUT_TYPES = {"text", "textarea", "image", "select"}
# 必须非空的列表字段
NON_EMPTY_LIST_FIELDS = ("input_fields", "share_hooks", "unlock_hooks", "mock_examples")
# 注：pages / supported_platforms / growth_angles / compliance_notes 不强制校验
# （pages 由实际模板目录决定、平台清单允许后续扩展），属已知边界。


class BlueprintError(ValueError):
    """模板配置缺失或非法时抛出（viral 模板不静默降级）。"""


def load_template_config(template: str) -> dict | None:
    """读取并校验模板 template.json。不存在返回 None；存在但非法抛 BlueprintError。"""
    cfg_path = TEMPLATES_DIR / template / "template.json"
    if not cfg_path.exists():
        return None
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    except Exception as e:
        raise BlueprintError(f"模板配置非法 JSON: {cfg_path} ({e})")
    _validate_config(template, cfg)
    return cfg


def _validate_config(template: str, cfg: dict) -> None:
    """校验 template.json：必需键、id 一致性、preview_type、非空列表、input field 结构。"""
    missing = [k for k in REQUIRED_CONFIG_FIELDS if k not in cfg]
    if missing:
        raise BlueprintError(f"{template}/template.json 缺少字段: {', '.join(missing)}")
    if cfg["id"] != template:
        raise BlueprintError(f"{template}/template.json id={cfg['id']!r} 与目录名不一致")
    if cfg["preview_type"] not in SUPPORTED_PREVIEW_TYPES:
        raise BlueprintError(
            f"{template}/template.json preview_type={cfg['preview_type']!r} "
            f"不在 generation.ts 支持范围 {sorted(SUPPORTED_PREVIEW_TYPES)}"
        )
    for field in NON_EMPTY_LIST_FIELDS:
        if not cfg.get(field):
            raise BlueprintError(f"{template}/template.json {field} 不能为空")
    for f in cfg["input_fields"]:
        miss = [k for k in REQUIRED_INPUT_FIELD_KEYS if k not in f]
        if miss:
            raise BlueprintError(
                f"{template}/template.json input_field {f.get('id', '?')} 缺少键: {', '.join(miss)}"
            )
        if f["type"] not in ALLOWED_INPUT_TYPES:
            raise BlueprintError(
                f"{template}/template.json input_field {f['id']} type={f['type']!r} "
                f"不在允许集合 {sorted(ALLOWED_INPUT_TYPES)}"
            )


def _fallback_blueprint(template: str, app: dict, prd_json: dict) -> dict:
    """兜底模板（base/ai-*）的安全默认蓝图：通用文本结果 + 通用传播钩子。"""
    app_name = app.get("name_cn") or app.get("name") or "小程序"
    return {
        "template_id": template,
        "app_name": app_name,
        "preview_type": "text",
        "input_fields": [
            {"id": "text", "label": "输入内容", "type": "textarea",
             "required": False, "placeholder": "请输入内容 / 主题 / 一句话..."},
        ],
        "pages": ["index", "form", "result", "profile"],
        "result_contract": ["text"],
        "share_hooks": ["看看我用它生成的结果", "一键生成，分享解锁完整高清结果"],
        "unlock_hooks": ["分享解锁高清无水印结果", "分享解锁更多模板"],
        "growth_angles": ["通用工具型分享", "结果页内置分享入口"],
        "compliance_notes": ["生成内容需符合平台规范"],
        "mock_examples": [{
            "title": "生成结果",
            "preview_type": "text",
            "preview_data": {"text": "这是一段示例生成结果。"},
            "share_title": "看看我用它生成的结果",
            "share_copy": "一键生成，分享解锁完整高清结果",
            "unlock_hint": "分享解锁高清无水印结果 + 解锁更多模板",
        }],
        "source_template_config": None,
        "is_fallback": True,
    }


def build_template_blueprint(template: str, app: dict, prd_json: dict) -> dict:
    """由模板配置 + App 数据合成生成蓝图。

    - viral 模板缺 template.json -> BlueprintError（不静默降级）
    - 兜底模板缺 template.json -> fallback blueprint
    """
    cfg = load_template_config(template)
    if cfg is None:
        if template in VIRAL_TEMPLATES:
            raise BlueprintError(
                f"传播型模板 {template} 缺少 template.json，拒绝静默降级。"
                f"请补 {TEMPLATES_DIR / template / 'template.json'}。"
            )
        return _fallback_blueprint(template, app, prd_json)

    app_name = app.get("name_cn") or app.get("name") or cfg["name_cn"]
    result_contract = [f.get("id") for f in cfg.get("result_fields", []) if f.get("id")]

    return {
        "template_id": cfg["id"],
        "app_name": app_name,
        "preview_type": cfg["preview_type"],
        "input_fields": cfg["input_fields"],
        "pages": cfg.get("pages", []),
        "result_contract": result_contract,
        "share_hooks": cfg["share_hooks"],
        "unlock_hooks": cfg["unlock_hooks"],
        "growth_angles": cfg.get("growth_angles", []),
        "compliance_notes": cfg.get("compliance_notes", []),
        "mock_examples": cfg["mock_examples"],
        "source_template_config": cfg,
        "is_fallback": False,
    }

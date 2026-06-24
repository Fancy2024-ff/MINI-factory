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

# 模板能力分类合法值（事实源在 template.json，此处登记可选集）。
TEMPLATE_STATUSES = {"core_runnable", "honest_preview"}
GENERATION_BACKENDS = {"template_api", "honest_fallback"}

# 模板能力字段（从 template.json 注入到 blueprint，供 codegen / 前端 / QA 统一读取）。
# 注意：blueprint.fallback_mode 表示「该模板是否诚实兜底（无真实生成）」，
# 与 blueprint.is_fallback（blueprint 是否用了兜底配置）是两件事，不要混淆。
CAPABILITY_FIELDS = (
    "template_status", "status_label", "generation_backend",
    "real_generation", "fallback_mode", "result_identity",
    "boundary_note", "qa_expectation", "frontend_badge",
)


def _capability_from_config(cfg: dict) -> dict:
    """从 template.json 抽取模板能力字段；缺省给安全默认（按通用工具型兜底）。"""
    real_generation = bool(cfg.get("real_generation", False))
    return {
        "template_status": cfg.get("template_status")
        or ("core_runnable" if real_generation else "honest_preview"),
        "status_label": cfg.get("status_label")
        or ("核心可跑通" if real_generation else "诚实预览"),
        "generation_backend": cfg.get("generation_backend")
        or ("template_api" if real_generation else "honest_fallback"),
        "real_generation": real_generation,
        "fallback_mode": bool(cfg.get("fallback_mode", not real_generation)),
        "result_identity": cfg.get("result_identity") or cfg.get("description", ""),
        "boundary_note": cfg.get("boundary_note", ""),
        "qa_expectation": cfg.get("qa_expectation", ""),
        "frontend_badge": cfg.get("frontend_badge")
        or cfg.get("status_label")
        or ("核心可跑通" if real_generation else "诚实预览"),
    }


# --- 传播闭环（growth_loop）结构化事实源（P0-2）---
# template.json.growth_loop 是「这套模板带不带传播机制」的单一事实源，
# 比 share_hooks / unlock_hooks 更明确：分享 CTA / 解锁 / 水印 / 去水印 / 品牌露出 /
# 下载导出 / 能力真实度都用结构化布尔+文案表达，供 codegen / 生成产物 / 前端 / QA 统一消费。
# capability_mode 与能力字段对齐：real <-> real_generation=true；fallback_preview <-> 诚实预览。
GROWTH_LOOP_REQUIRED_KEYS = (
    "has_share_cta", "share_cta_label", "share_title", "share_copy",
    "has_unlock", "unlock_type", "unlock_hint",
    "has_watermark", "watermark_label", "remove_watermark_supported",
    "brand_exposure", "brand_label",
    "download_supported", "export_supported", "export_label",
    "capability_mode", "capability_note",
)
GROWTH_LOOP_CAPABILITY_MODES = {"real", "fallback_preview"}


def _generic_growth_loop(cfg: dict) -> dict:
    """通用兜底 growth_loop（base/ai-* 等非 viral 模板）。

    通用模板不能冒充 viral 模板：capability_mode 跟随 real_generation，
    文案保持通用、不带题材化传播话术。
    """
    real_generation = bool(cfg.get("real_generation", False))
    return {
        "has_share_cta": True,
        "share_cta_label": "分享结果",
        "share_title": cfg.get("share_title") or "看看我用它生成的结果",
        "share_copy": "一键生成，分享解锁完整高清结果",
        "has_unlock": True,
        "unlock_type": "share_to_unlock",
        "unlock_hint": "分享解锁高清无水印结果",
        "has_watermark": True,
        "watermark_label": "MiniForge 水印",
        "remove_watermark_supported": True,
        "remove_watermark_condition": "分享后解锁去水印结果",
        "brand_exposure": True,
        "brand_label": "MiniForge 出品 · 结果附小程序码",
        "download_supported": bool(real_generation),
        "export_supported": bool(real_generation),
        "export_label": "导出结果" if real_generation else "导出入口已预留",
        "capability_mode": "real" if real_generation else "fallback_preview",
        "capability_note": cfg.get("boundary_note")
        or ("真实生成结果，分享解锁去水印。" if real_generation
            else "通用预览结果，非题材化真实生成。"),
        "result_layer_logic": "结果页展示生成结果 + 含水印预览，分享 CTA 引导传播，解锁后去水印。",
    }


def _growth_loop_from_config(template: str, cfg: dict) -> dict:
    """取模板的 growth_loop 结构化事实源。

    - 显式 growth_loop（viral 模板）：原样透传（已在 _validate_config 校验完整性）。
    - 无显式 growth_loop（ai-image / 兜底）：按能力字段派生通用 growth_loop，
      但不冒充 viral 模板（capability_mode 跟随真实能力、文案通用）。
    """
    gl = cfg.get("growth_loop")
    if isinstance(gl, dict) and gl:
        return gl
    return _generic_growth_loop(cfg)


def growth_loop_for_template(template: str) -> dict:
    """按模板名取 growth_loop 事实源（供 growth 文档生成消费，单一事实源）。

    - viral 模板（VIRAL_TEMPLATES）：load/校验出错必须 re-raise BlueprintError，
      不允许 generic fallback——否则单一事实源坏掉时增长文档会继续产出通用闭环、掩盖错误。
    - 非 viral / 未知模板：缺配置或校验失败时回退通用 growth_loop（文档主链路稳定优先）。
    """
    if template in VIRAL_TEMPLATES:
        # viral 模板：不吞错。load_template_config 内部对坏配置/缺 growth_loop 会抛 BlueprintError。
        cfg = load_template_config(template)
        if cfg is None:
            raise BlueprintError(
                f"传播型模板 {template} 缺少 template.json，拒绝静默降级。"
            )
        return _growth_loop_from_config(template, cfg)
    # 非 viral：缺配置/坏配置都回退通用闭环，不阻断文档主链路。
    try:
        cfg = load_template_config(template)
    except BlueprintError:
        return _generic_growth_loop({})
    if cfg is None:
        return _generic_growth_loop({})
    return _growth_loop_from_config(template, cfg)



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
    # viral 模板必须带结构化 growth_loop 事实源（P0-2，不允许只靠 share_hooks）。
    if template in VIRAL_TEMPLATES:
        _validate_growth_loop(template, cfg)


def _validate_growth_loop(template: str, cfg: dict) -> None:
    """校验 viral 模板的 growth_loop 结构化传播闭环事实源。

    - 必须存在且为 dict；
    - 必须含 GROWTH_LOOP_REQUIRED_KEYS 全部键；
    - capability_mode 必须是 real / fallback_preview 之一；
    - 与能力字段对齐：real_generation=true 的核心模板不得标 fallback_preview；
      诚实预览型（funny/blessing）必须是 fallback_preview，不得冒充 real。
    """
    gl = cfg.get("growth_loop")
    if not isinstance(gl, dict) or not gl:
        raise BlueprintError(
            f"传播型模板 {template}/template.json 缺少结构化 growth_loop 事实源（P0-2）"
        )
    miss = [k for k in GROWTH_LOOP_REQUIRED_KEYS if k not in gl]
    if miss:
        raise BlueprintError(
            f"{template}/template.json growth_loop 缺少键: {', '.join(miss)}"
        )
    mode = gl.get("capability_mode")
    if mode not in GROWTH_LOOP_CAPABILITY_MODES:
        raise BlueprintError(
            f"{template}/template.json growth_loop.capability_mode={mode!r} "
            f"不在 {sorted(GROWTH_LOOP_CAPABILITY_MODES)}"
        )
    real_generation = bool(cfg.get("real_generation", False))
    if real_generation and mode != "real":
        raise BlueprintError(
            f"{template}/template.json real_generation=true 但 growth_loop.capability_mode={mode!r}，"
            f"核心可跑通模板必须为 real（口径冲突）"
        )
    if not real_generation and mode != "fallback_preview":
        raise BlueprintError(
            f"{template}/template.json real_generation=false 但 growth_loop.capability_mode={mode!r}，"
            f"诚实预览型模板必须为 fallback_preview（不得冒充真实生成）"
        )
    _validate_download_gate(template, gl)


# download_gate（激励广告下载门槛）允许值。
DOWNLOAD_GATE_TYPES = {"rewarded_ad", "none"}
DOWNLOAD_GATE_REQUIRED_KEYS = (
    "enabled", "gate_type", "required_for",
    "gate_label", "reward_label", "unavailable_hint", "close_hint",
)
DOWNLOAD_GATE_REQUIRED_FOR_VALUES = {"download", "remove_watermark", "export"}
# 视频边界型模板：gate 文案不得宣称「下载/生成视频」，只能导出脚本/卡片预览。
_VIDEO_BOUNDARY_TEMPLATES = {"funny-video-viral", "blessing-video-viral"}
_FORBIDDEN_VIDEO_GATE_PHRASES = ("下载视频", "下载祝福视频", "生成视频", "真实视频", "视频已生成")


def _validate_download_gate(template: str, gl: dict) -> None:
    """校验 growth_loop.download_gate（存在才校验；它是 P0-2 广告门槛事实源）。

    - 结构完整、gate_type / required_for 合法；
    - 视频边界型（funny/blessing）的 gate 文案不得宣称下载/生成视频（不伪装真实视频）。
    """
    gate = gl.get("download_gate")
    if gate is None:
        return  # download_gate 为可选；缺省视为无广告门槛
    if not isinstance(gate, dict):
        raise BlueprintError(f"{template}/template.json growth_loop.download_gate 必须是对象")
    miss = [k for k in DOWNLOAD_GATE_REQUIRED_KEYS if k not in gate]
    if miss:
        raise BlueprintError(
            f"{template}/template.json download_gate 缺少键: {', '.join(miss)}"
        )
    if gate.get("gate_type") not in DOWNLOAD_GATE_TYPES:
        raise BlueprintError(
            f"{template}/template.json download_gate.gate_type={gate.get('gate_type')!r} "
            f"不在 {sorted(DOWNLOAD_GATE_TYPES)}"
        )
    rf = gate.get("required_for")
    if not isinstance(rf, list) or any(x not in DOWNLOAD_GATE_REQUIRED_FOR_VALUES for x in rf):
        raise BlueprintError(
            f"{template}/template.json download_gate.required_for={rf!r} "
            f"只能取 {sorted(DOWNLOAD_GATE_REQUIRED_FOR_VALUES)}"
        )
    if template in _VIDEO_BOUNDARY_TEMPLATES:
        blob = f"{gate.get('gate_label', '')} {gate.get('reward_label', '')}"
        hit = [p for p in _FORBIDDEN_VIDEO_GATE_PHRASES if p in blob]
        if hit:
            raise BlueprintError(
                f"{template}/template.json download_gate 文案不得宣称视频下载/生成: {hit}"
                f"（视频边界型只能导出脚本/卡片预览）"
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
        # 兜底模板（base/ai-*）默认通用文本预览：标为 honest_preview，不冒充真实生成。
        "template_status": "honest_preview",
        "status_label": "通用预览",
        "generation_backend": "honest_fallback",
        "real_generation": False,
        "fallback_mode": True,
        "result_identity": "通用文本结果",
        "boundary_note": "通用兜底模板：当前仅提供通用文本预览，非题材化真实生成。",
        "qa_expectation": "兜底模板，无强制题材分类要求。",
        "frontend_badge": "通用预览",
        # 通用兜底 growth_loop：保证前端/QA 始终能读到结构化传播闭环，但不冒充 viral。
        "growth_loop": {
            "has_share_cta": True,
            "share_cta_label": "分享结果",
            "share_title": "看看我用它生成的结果",
            "share_copy": "一键生成，分享解锁完整高清结果",
            "has_unlock": True,
            "unlock_type": "share_to_unlock",
            "unlock_hint": "分享解锁高清无水印结果",
            "has_watermark": True,
            "watermark_label": "MiniForge 水印",
            "remove_watermark_supported": True,
            "remove_watermark_condition": "分享后解锁去水印结果",
            "brand_exposure": True,
            "brand_label": "MiniForge 出品 · 结果附小程序码",
            "download_supported": False,
            "export_supported": False,
            "export_label": "导出入口已预留",
            "capability_mode": "fallback_preview",
            "capability_note": "通用兜底模板：当前仅提供通用预览，非题材化真实生成。",
            "result_layer_logic": "结果页展示通用文本结果 + 含水印预览，分享 CTA 引导传播，解锁后去水印。",
        },
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
        "growth_loop": _growth_loop_from_config(template, cfg),
        **_capability_from_config(cfg),
    }

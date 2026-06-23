"""core.qa.generator_qa — 生成器 / 模板配置质量验证（GeneratorQA / TemplateQA）。

职责：
  校验「模板配置 -> blueprint -> codegen 产物」这条链路的结构与契约质量，独立于
  EngineeringQA（构建）/ GrowthQA（传播闭环）/ ComplianceQA（合规）。

两类检查：
  1. 模板配置级（不依赖生成产物）：
     - 5 个 viral 模板 template.json 都存在、JSON 合法
     - id == 目录名
     - preview_type 被 generation.ts/result.vue 支持
     - input_fields / share_hooks / unlock_hooks / mock_examples 非空
     - blueprint_builder 能为 5 个模板成功合成 blueprint
     - 模板能力分类正确（core_runnable vs honest_preview）：
       avatar/sticker/pet-talk = core_runnable + template_api + real_generation + 非 fallback；
       funny/blessing = honest_preview + honest_fallback + 非 real + fallback_mode；
       funny/blessing 文案不得宣称「视频已生成」；pet-talk 不得被归为 honest_preview。
  2. 生成产物级（传入 miniapp_dir 时）：
     - 含 src/config/blueprint.json（或等价配置），且含模板能力字段
     - 无 __APP_ token 残留
     - generation.ts 支持 blueprint 驱动（loadBlueprint + generateFromBlueprint）

约束：业务规则在 core，runner 只编排；不依赖 LLM。
"""

from __future__ import annotations

import json
from pathlib import Path

from core.generator.blueprint_builder import (
    CAPABILITY_FIELDS,
    SUPPORTED_PREVIEW_TYPES,
    VIRAL_TEMPLATES,
    build_template_blueprint,
)

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "generator" / "src" / "templates"

# 5 套传播型模板的固定能力分类（P0-1 收口事实表，QA 据此校验，不允许漂移）。
#   核心可跑通：真实链路跑通（template_api + real_generation）。
#   诚实边界型：只产出预览（honest_fallback + fallback_mode），不伪装真实视频。
EXPECTED_CLASSIFICATION = {
    "avatar-viral": "core_runnable",
    "sticker-viral": "core_runnable",
    "pet-talk-viral": "core_runnable",
    "funny-video-viral": "honest_preview",
    "blessing-video-viral": "honest_preview",
}

# 诚实边界型模板产出/文案里禁止出现的误导措辞（伪装成完整视频能力）。
_MISLEADING_VIDEO_FRAGMENTS = (
    "视频已生成",
    "完整视频已生成",
    "完整视频生成成功",
    "视频生成成功",
    "已生成完整视频",
)


_FRONTEND_FORBIDDEN_FRAGMENTS = (
    "IMAGE_GENERATION_API_KEY",
    "IMAGE_GENERATION_ENDPOINT",
    "Authorization",
    "Bearer ",
    "api_key",
    "access_token",
    "provider_key",
)

# 用于校验生成项目的最小 app/prd（GeneratorQA 不跑生成，只在需要时合成 blueprint）。
_SAMPLE_APP = {"name": "QA Sample", "name_cn": "质检样例", "description_cn": "GeneratorQA 校验用样例。"}
_SAMPLE_PRD = {"target_platforms": ["wechat"]}


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8-sig")
    except Exception:
        return ""


def _check_template_config(template: str, checks: dict, issues: list[str]) -> None:
    """校验单个模板的 template.json + blueprint 合成。"""
    cfg_path = TEMPLATES_DIR / template / "template.json"
    key = f"template_config:{template}"
    if not cfg_path.exists():
        checks[key] = False
        issues.append(f"{template}/template.json 不存在")
        return

    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    except Exception as e:
        checks[key] = False
        issues.append(f"{template}/template.json JSON 非法: {e}")
        return

    ok = True
    if cfg.get("id") != template:
        ok = False
        issues.append(f"{template}/template.json id={cfg.get('id')!r} 与目录名不一致")
    if cfg.get("preview_type") not in SUPPORTED_PREVIEW_TYPES:
        ok = False
        issues.append(f"{template}/template.json preview_type={cfg.get('preview_type')!r} 不受支持")
    if not cfg.get("input_fields"):
        ok = False
        issues.append(f"{template}/template.json input_fields 为空")
    if not cfg.get("share_hooks"):
        ok = False
        issues.append(f"{template}/template.json share_hooks 为空")
    if not cfg.get("unlock_hooks"):
        ok = False
        issues.append(f"{template}/template.json unlock_hooks 为空")
    if not cfg.get("mock_examples"):
        ok = False
        issues.append(f"{template}/template.json mock_examples 为空")

    # blueprint 合成
    if ok:
        try:
            bp = build_template_blueprint(template, _SAMPLE_APP, _SAMPLE_PRD)
            if bp["template_id"] != template or not bp["preview_type"]:
                ok = False
                issues.append(f"{template} blueprint 合成结果异常")
        except Exception as e:
            ok = False
            issues.append(f"{template} blueprint 合成失败: {e}")

    # 模板签名页：template.json.pages 里 base 没有的页（题材身份页）必须有真实 .vue。
    # base 通用页 = index/form/result/profile；其余即签名页（gallery/pack/upload/clip/greeting…）。
    _BASE_PAGES = {"index", "form", "result", "profile"}
    signature_pages = [p for p in (cfg.get("pages") or []) if p not in _BASE_PAGES]
    for page in signature_pages:
        vue = TEMPLATES_DIR / template / "src" / "pages" / page / f"{page}.vue"
        if not vue.exists():
            ok = False
            issues.append(f"{template} 签名页缺失: src/pages/{page}/{page}.vue（题材身份页必须存在）")

    # 模板能力分类（P0-1 收口）：字段齐全 + 分类与 EXPECTED_CLASSIFICATION 一致。
    if not _check_capability_classification(template, cfg, issues):
        ok = False

    checks[key] = ok


def _check_capability_classification(template: str, cfg: dict, issues: list[str]) -> bool:
    """校验单个模板的能力字段齐全且分类正确。返回是否通过。

    口径（固定，不允许漂移）：
      - 5 个能力字段（template_status/generation_backend/real_generation/
        fallback_mode/boundary_note）必须存在。
      - 核心可跑通：core_runnable + template_api + real_generation=True + fallback_mode=False。
      - 诚实边界型：honest_preview + honest_fallback + real_generation=False + fallback_mode=True，
        且文案不得宣称「视频已生成」。
      - pet-talk 必须是 core_runnable（不得被归为 honest_preview）。
    """
    ok = True
    required = ("template_status", "generation_backend", "real_generation",
                "fallback_mode", "boundary_note")
    missing = [k for k in required if k not in cfg]
    if missing:
        issues.append(f"{template}/template.json 缺少能力字段: {', '.join(missing)}")
        return False

    expected_status = EXPECTED_CLASSIFICATION.get(template)
    if expected_status and cfg.get("template_status") != expected_status:
        ok = False
        issues.append(
            f"{template} template_status={cfg.get('template_status')!r}，应为 {expected_status!r}"
        )

    if expected_status == "core_runnable":
        if cfg.get("generation_backend") != "template_api":
            ok = False
            issues.append(f"{template} 核心模板 generation_backend 应为 template_api")
        if cfg.get("real_generation") is not True:
            ok = False
            issues.append(f"{template} 核心模板 real_generation 应为 true")
        if cfg.get("fallback_mode") is not False:
            ok = False
            issues.append(f"{template} 核心模板 fallback_mode 应为 false")
    elif expected_status == "honest_preview":
        if cfg.get("generation_backend") != "honest_fallback":
            ok = False
            issues.append(f"{template} 边界模板 generation_backend 应为 honest_fallback")
        if cfg.get("real_generation") is not False:
            ok = False
            issues.append(f"{template} 边界模板 real_generation 应为 false")
        if cfg.get("fallback_mode") is not True:
            ok = False
            issues.append(f"{template} 边界模板 fallback_mode 应为 true")
        # 诚实边界型不得用「视频已生成」类误导文案。只扫用户可见文案字段
        # （description + mock_examples 的 title/share/ unlock），不扫 QA/边界说明本身。
        for frag in _MISLEADING_VIDEO_FRAGMENTS:
            if frag in _user_facing_copy(cfg):
                ok = False
                issues.append(f"{template} 出现误导文案「{frag}」（诚实边界型不得宣称视频已生成）")
    return ok


def _user_facing_copy(cfg: dict) -> str:
    """汇总模板里会展示给用户的文案（不含 QA/边界等内部说明），用于误导文案扫描。"""
    parts = [cfg.get("description", ""), cfg.get("name_cn", "")]
    for ex in cfg.get("mock_examples", []) or []:
        parts += [ex.get("title", ""), ex.get("share_title", ""),
                  ex.get("share_copy", ""), ex.get("unlock_hint", "")]
        pd = ex.get("preview_data") or {}
        if isinstance(pd, dict):
            parts += [str(v) for v in pd.values()]
    return " ".join(p for p in parts if p)




def _check_generated_project(miniapp_dir: Path, checks: dict, issues: list[str]) -> None:
    """校验生成产物：blueprint.json / 无 token 残留 / generation.ts blueprint 驱动。"""
    src = miniapp_dir / "src"

    bp_path = src / "config" / "blueprint.json"
    bp_ok = bp_path.exists()
    bp_data: dict = {}
    if bp_ok:
        try:
            bp_data = json.loads(bp_path.read_text(encoding="utf-8-sig"))
            bp_ok = bool(bp_data.get("template_id")) and bp_data.get("preview_type") in SUPPORTED_PREVIEW_TYPES
        except Exception as e:
            bp_ok = False
            issues.append(f"生成项目 blueprint.json 非法: {e}")
    checks["generated_blueprint_exists"] = bp_ok
    if not bp_path.exists():
        issues.append("生成项目缺少 src/config/blueprint.json")

    # blueprint.json 必须含模板能力字段（template_status/generation_backend/
    # real_generation/fallback_mode/boundary_note 等），供前端/QA 统一读取。
    bp_cap_ok = True
    if bp_path.exists() and bp_data:
        bp_missing = [k for k in CAPABILITY_FIELDS if k not in bp_data]
        if bp_missing:
            bp_cap_ok = False
            issues.append(f"生成项目 blueprint.json 缺少能力字段: {', '.join(bp_missing)}")
    elif not bp_path.exists():
        bp_cap_ok = False
    checks["generated_blueprint_capability_fields"] = bp_cap_ok

    # 无 __APP_ token 残留
    no_residue = True
    for f in miniapp_dir.rglob("*"):
        if f.is_file() and f.suffix in (".vue", ".json", ".ts", ".md", ".html"):
            if "node_modules" in str(f) or "dist" in str(f):
                continue
            if "__APP_" in _read(f):
                no_residue = False
                issues.append(f"生成项目残留 token: {f.relative_to(miniapp_dir)}")
                break
    checks["generated_no_token_residue"] = no_residue

    no_frontend_secret = True
    for f in miniapp_dir.rglob("*"):
        if f.is_file() and f.suffix in (".vue", ".json", ".ts", ".md", ".html"):
            if "node_modules" in str(f) or "dist" in str(f):
                continue
            text = _read(f)
            if any(fragment in text for fragment in _FRONTEND_FORBIDDEN_FRAGMENTS):
                no_frontend_secret = False
                issues.append(f"生成项目残留 provider 凭证片段: {f.relative_to(miniapp_dir)}")
                break
    checks["generated_no_provider_secret_residue"] = no_frontend_secret

    # generation.ts 必须是 blueprint 驱动
    svc_txt = _read(src / "services" / "generation.ts")
    svc_ok = bool(svc_txt) and "loadBlueprint" in svc_txt and "generateFromBlueprint" in svc_txt
    checks["generation_blueprint_driven"] = svc_ok
    if not svc_ok:
        issues.append("generation.ts 缺少 blueprint 驱动入口（loadBlueprint/generateFromBlueprint）")

    api_mode_ok = bool(svc_txt) and "callRealApi" in svc_txt and "GENERATION_MODE" in svc_txt and "IMAGE_GENERATION_PATH" in svc_txt
    checks["generation_api_mode_path"] = api_mode_ok
    if not api_mode_ok:
        issues.append("generation.ts 缺少真实 API 链路路径（callRealApi/GENERATION_MODE/IMAGE_GENERATION_PATH）")


def run_generator_qa(miniapp_dir: Path | None = None) -> dict:
    """运行 GeneratorQA。传入 miniapp_dir 时附加生成产物级检查。"""
    issues: list[str] = []
    checks: dict = {}

    # 1. 模板配置级（5 个 viral 模板）
    for template in sorted(VIRAL_TEMPLATES):
        _check_template_config(template, checks, issues)

    # 2. 生成产物级（可选）
    if miniapp_dir is not None:
        _check_generated_project(miniapp_dir, checks, issues)

    passed = all(checks.values())
    return {"passed": passed, "checks": checks, "issues": issues}

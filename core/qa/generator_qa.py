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
    # ai-image 也是核心可跑通（template_api 真实出图），纳入 P0-1 分类事实表。
    "ai-image": "core_runnable",
}

# P0-1 配置级 + overlay 文案扫描范围：5 套 viral + ai-image。
# 注意：run_generator_qa 据此遍历，确保 checks 里能看到 template_config:ai-image
# 与 overlay_copy:ai-image（之前只扫 VIRAL_TEMPLATES，ai-image 漏扫）。
CLASSIFIED_TEMPLATES = tuple(sorted(VIRAL_TEMPLATES | {"ai-image"}))

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

    # 输入字段诚实性（P0-1）：image 输入若文案宣称「上传照片/图」驱动生成，
    # 但链路并不真正上传/消费图片，必须显式标 drives_generation:false，否则视为不一致。
    if not _check_input_upload_honesty(template, cfg, issues):
        ok = False

    # 用户可见文案诚实性（P0-1 收口）：扫 overlay Vue 页（不只 template.json），
    # 防止页面冒充上传驱动 / 视频生成，而数据层早已诚实。
    # 单独登记 overlay_copy:<template>，让 checks 显式可见每个模板的页面扫描结果。
    overlay_ok = _check_overlay_vue_copy(template, cfg, issues)
    checks[f"overlay_copy:{template}"] = overlay_ok
    if not overlay_ok:
        ok = False

    checks[key] = ok


# 宣称「上传图片驱动生成」的文案信号（label / placeholder 命中即视为承诺了上传）。
_UPLOAD_CLAIM_FRAGMENTS = ("上传照片", "上传宠物照片", "上传原图", "上传图片", "上传一张")

# 占位/诚实修饰：命中其一即视为已诚实声明「图片仅占位、不参与生成」。
_PLACEHOLDER_QUALIFIERS = ("占位", "不参与生成", "仅作", "本地占位")

# 视频能力误导文案（core_runnable 但 video_supported=false 的 pet-talk 等不得出现）。
_VIDEO_CLAIM_FRAGMENTS = ("生成视频", "视频生成", "完整视频", "高清视频", "说话视频", "生成说话视频")

# 上传驱动生成的 CTA 文案（drives_generation:false 的 image 字段页面不得出现）。
_UPLOAD_CTA_FRAGMENTS = ("上传照片生成", "上传图片处理", "上传照片，生成", "上传图片，处理",
                         "上传照片 生成", "上传宠物照片，生成")

# 用户可见属性（其值会展示给用户，必须纳入文案扫描）。
_VISIBLE_ATTRS = (
    "placeholder", "title", "alt", "aria-label",
    "label", "value", "confirm-text", "cancel-text", "content",
)
# CTA 类元素：其文本是主行动按钮，裸上传/视频文案危害最大，单独从严。
_CTA_TAGS = ("button",)


def _extract_vue_segments(vue_text: str) -> list[tuple[str, str]]:
    """抽取 Vue 用户可见文案，返回 [(kind, text)] 段列表（按节点/属性切分，不合并成一坨）。

    kind:
      - "cta"  : <button> 等行动元素文本（裸上传/视频文案危害最大，从严）。
      - "attr" : 用户可见属性值（placeholder/title/alt/aria-label/label/...）。
      - "text" : 普通文本节点 / 文本插值 {{ ... }}。
      - "toast": <script> 内 title:'...'（showToast/showModal 等用户可见提示）。
    去 HTML 注释，避免把"口径说明注释"当展示文案。按段返回是为了让"占位修饰"
    判定落到同一文本节点/同一属性，而不是整页有"占位"就放过所有"上传照片"。
    """
    import re

    segments: list[tuple[str, str]] = []
    text = re.sub(r"<!--.*?-->", " ", vue_text, flags=re.DOTALL)
    tmpl_m = re.search(r"<template>(.*?)</template>", text, flags=re.DOTALL)
    tmpl = tmpl_m.group(1) if tmpl_m else ""

    # 1) CTA 元素文本（<button ...>文本</button>，文本里可能含 {{ }}）。
    for tag in _CTA_TAGS:
        for m in re.finditer(rf"<{tag}\b[^>]*>(.*?)</{tag}>", tmpl, flags=re.DOTALL):
            inner = re.sub(r"<[^>]+>", " ", m.group(1))
            if inner.strip():
                segments.append(("cta", inner))

    # 2) 用户可见属性值（静态 attr="..." / attr='...'，以及绑定 :attr="'...'"）。
    for attr in _VISIBLE_ATTRS:
        for m in re.finditer(rf'\b{attr}\s*=\s*"([^"]*)"', tmpl):
            segments.append(("attr", m.group(1)))
        for m in re.finditer(rf"\b{attr}\s*=\s*'([^']*)'", tmpl):
            segments.append(("attr", m.group(1)))
        # 绑定属性：取绑定表达式里的字符串字面量（:placeholder="cond ? '上传图片' : '...'"）。
        for m in re.finditer(rf"(?::|v-bind:){attr}\s*=\s*\"([^\"]*)\"", tmpl):
            for lit in re.findall(r"'([^']*)'", m.group(1)):
                segments.append(("attr", lit))

    # 3) 普通文本节点：标签替换成换行后逐段保留（保留 {{ }} 文本插值）。
    no_tags = re.sub(r"<[^>]+>", "\n", tmpl)
    for line in no_tags.splitlines():
        s = line.strip()
        if s:
            segments.append(("text", s))

    # 4) <script> 内用户可见提示（title:'...'）。
    for m in re.finditer(r"title:\s*['\"]([^'\"]+)['\"]", text):
        segments.append(("toast", m.group(1)))

    return segments


def _extract_vue_visible_text(vue_text: str) -> str:
    """兼容旧接口：把所有可见段拼成一坨（仅用于"任意段命中即违规"的无条件禁令）。"""
    return " ".join(t for _, t in _extract_vue_segments(vue_text))


def _check_overlay_vue_copy(template: str, cfg: dict, issues: list[str]) -> bool:
    """扫描该模板 overlay 下所有 *.vue 的用户可见文案，按能力分类施加诚实规则。

    规则：
      - core_runnable 但 video_supported=false（如 pet-talk）：页面不得出现
        "生成视频/视频生成/完整视频/高清视频/说话视频"等动态视频误导文案（任意段命中即违规）。
      - honest_preview（funny/blessing）：同样不得宣称"视频已生成"类完成文案。
      - 任一 image 输入字段 drives_generation=false：
          * CTA（button）文本里出现"上传照片/图/...”一律违规（主行动按钮从严，
            即便另起一段写了"占位"也不放过——按钮文案本身在误导）；
          * 非 CTA 文本节点/属性出现"上传照片/图"，必须在【同一段】带占位修饰，
            否则违规（不再整页有"占位"就放过所有上传文案）；
          * 命中显式上传驱动短语（_UPLOAD_CTA_FRAGMENTS）一律违规。
    """
    tpl_dir = TEMPLATES_DIR / template / "src" / "pages"
    if not tpl_dir.exists():
        return True  # 该模板无 overlay 页（如纯配置模板），跳过。

    status = cfg.get("template_status")
    video_supported = _template_video_supported(cfg)
    # 是否存在「不驱动生成」的 image 字段（上传仅占位）。
    has_placeholder_image = any(
        f.get("type") == "image" and f.get("drives_generation", True) is False
        for f in (cfg.get("input_fields") or [])
    )

    ok = True
    for vue in sorted(tpl_dir.rglob("*.vue")):
        segments = _extract_vue_segments(_read(vue))
        whole = " ".join(t for _, t in segments)
        rel = vue.relative_to(TEMPLATES_DIR / template)

        # 1) 视频能力误导：非真实动态视频模板（video_supported=false 或 honest_preview）。
        #    任意可见段命中即违规（视频文案没有"占位"可豁免一说）。
        if (status == "core_runnable" and not video_supported) or status == "honest_preview":
            for frag in _VIDEO_CLAIM_FRAGMENTS:
                if frag in whole:
                    ok = False
                    issues.append(
                        f"{template} 页面 {rel} 出现视频误导文案「{frag}」"
                        f"（该模板不产出真实动态视频，用户可见文案不得宣称生成视频）"
                    )

        # 1b) honest_preview 还要拦"视频已生成"类完成文案。
        if status == "honest_preview":
            for frag in _MISLEADING_VIDEO_FRAGMENTS:
                if frag in whole:
                    ok = False
                    issues.append(f"{template} 页面 {rel} 出现误导完成文案「{frag}」")

        # 2) 上传驱动文案：image 字段仅占位时按段判定，占位修饰必须同段。
        if has_placeholder_image:
            for kind, seg in segments:
                # 显式上传驱动短语：任何段命中都违规。
                for frag in _UPLOAD_CTA_FRAGMENTS:
                    if frag in seg:
                        ok = False
                        issues.append(
                            f"{template} 页面 {rel} 文案「{frag}」暗示上传图片驱动生成，"
                            f"但该模板图片仅占位（drives_generation=false），需去除上传驱动暗示"
                        )
                # 裸"上传照片/图"：CTA 一律禁（按钮文案本身在误导）；
                # 其它段必须【同段】带占位修饰才放过。
                for frag in _UPLOAD_CLAIM_FRAGMENTS:
                    if frag not in seg:
                        continue
                    if kind == "cta":
                        ok = False
                        issues.append(
                            f"{template} 页面 {rel} 行动按钮(CTA)出现「{frag}」，"
                            f"主按钮不得用上传图片文案（图片仅占位，不参与生成）"
                        )
                    elif not _seg_has_qualifier(seg):
                        ok = False
                        issues.append(
                            f"{template} 页面 {rel} 文案「{frag}」所在段缺少占位说明，"
                            f"图片仅占位需在同一处标注（如『占位，可选 / 不参与生成』）"
                        )
    return ok


def _seg_has_qualifier(seg_text: str) -> bool:
    """同一段（文本节点/属性）内是否带占位修饰。占位豁免必须落到同段，不看整页。"""
    return any(q in seg_text for q in _PLACEHOLDER_QUALIFIERS)


def _template_video_supported(cfg: dict) -> bool:
    """该模板是否支持真实动态视频。pet-talk 类核心模板产出静态预览/封面，视为 false。

    口径：preview_type=petVideo 的核心模板默认 video_supported=false（与后端
    template_generation 返回的 video_supported=False 对齐）；其余非视频题材不涉及。
    """
    if cfg.get("video_supported") is False:
        return False
    if cfg.get("preview_type") == "petVideo":
        return False
    return True



def _check_input_upload_honesty(template: str, cfg: dict, issues: list[str]) -> bool:
    """扫 image 类输入字段：宣称上传照片/图但未标 drives_generation:false 即不一致。

    当前真实链路是 prompt 驱动（不上传/不消费图片）。若某 image 字段文案让用户以为
    「上传照片才能生成」，又没有诚实标注该字段不参与生成，就是冒充照片驱动生成，必须失败。
    """
    ok = True
    for f in cfg.get("input_fields") or []:
        if f.get("type") != "image":
            continue
        text = f"{f.get('label', '')} {f.get('placeholder', '')}"
        claims_upload = any(frag in text for frag in _UPLOAD_CLAIM_FRAGMENTS)
        # 真正参与生成（drives_generation 非 False）却宣称上传 = 冒充照片驱动。
        if claims_upload and f.get("drives_generation", True) is not False:
            ok = False
            issues.append(
                f"{template} input_field {f.get('id', '?')} 文案宣称上传图片驱动生成，"
                f"但链路未上传/消费图片，需标 drives_generation:false 或改为占位文案"
            )
    return ok


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

    # 1. 模板配置级 + overlay 文案级：5 套 viral + ai-image（CLASSIFIED_TEMPLATES）。
    #    确保 checks 含 template_config:ai-image / overlay_copy:ai-image，不再漏扫。
    for template in CLASSIFIED_TEMPLATES:
        _check_template_config(template, checks, issues)

    # 2. 生成产物级（可选）
    if miniapp_dir is not None:
        _check_generated_project(miniapp_dir, checks, issues)

    passed = all(checks.values())
    return {"passed": passed, "checks": checks, "issues": issues}

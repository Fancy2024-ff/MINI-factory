"""core.qa.growth_qa — 增长/裂变交付质量验证。

职责：
  1. 增长产物齐全（growth-plan.md / share-strategy.md / viral-score.json）；
  2. growth/share 文档含必要裂变要素（分享钩子、激励、裂变回环、去水印）；
  3. 生成的小程序代码本身含传播链路：分享 CTA、解锁/裂变机制、品牌露出位；
  4. 传播闭环产品化分层（P0-2）：区分「只有文档 / 有传播设计 / 结果页真接入」——
     blueprint.growth_loop -> generation.ts 消费 -> result.vue 展示，三层都到位才算产品化。
规则版 v1。
"""

from __future__ import annotations

import json
from pathlib import Path

# 生成代码中传播链路信号（命中即视为该传播位已预留）
_SHARE_CTA = ["分享", "share", "转发", "晒"]
_UNLOCK_HOOK = ["解锁", "unlock", "邀请", "invite", "去水印", "watermark", "高清"]
_RESULT_PAGE = ["result", "gallery", "pack", "clip", "greeting", "preview", "结果", "作品"]

# 视频边界型模板（必须诚实标注 preview / fallback，不得冒充真实视频生成）
_VIDEO_PREVIEW_TEMPLATES = {"funny-video-viral", "blessing-video-viral"}
# 核心可跑通模板（必须为 real，不得被标成 fallback_preview）
_CORE_RUNNABLE_TEMPLATES = {"avatar-viral", "sticker-viral", "pet-talk-viral"}


def _scan_generated(miniapp_dir: Path, words: list[str]) -> bool:
    """扫描生成项目的页面（目录名 + 源码），命中任一关键词即返回 True。"""
    pages = miniapp_dir / "src" / "pages"
    if not pages.exists():
        return False
    lowered = [w.lower() for w in words]
    for vue in pages.rglob("*.vue"):
        # 页面路由名本身也是信号（如 pages/result/result.vue 即结果页）
        haystack = vue.parent.name.lower()
        try:
            haystack += " " + vue.read_text(encoding="utf-8-sig").lower()
        except Exception:
            pass
        if any(w in haystack for w in lowered):
            return True
    return False


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8-sig")
    except Exception:
        return ""


def _check_generation_flow(miniapp_dir: Path, checks: dict, issues: list[str]) -> None:
    """检查生成项目的交互闭环结构（generation service / result / form / 模板感知）。

    用结构关键词判断（mockGenerate / GeneratedResult / shareTitle 等），
    不只扫中文，避免英文文案模板漏判。
    """
    src = miniapp_dir / "src"
    service = src / "services" / "generation.ts"
    result_page = src / "pages" / "result" / "result.vue"
    form_page = src / "pages" / "form" / "form.vue"
    tmpl_cfg = src / "config" / "template.ts"

    service_txt = _read(service)
    result_txt = _read(result_page)
    form_txt = _read(form_page)
    tmpl_txt = _read(tmpl_cfg)

    # 1. 统一生成服务存在且定义核心契约（生成入口 + GeneratedResult）。
    #    允许 api/mock 双模式：入口函数名仍为 mockGenerate（form 调用约定），
    #    但不再把「必须 mock」当通过条件——真实链路由 api_contract 单独校验。
    has_entry = "mockGenerate" in service_txt or "generateFromBlueprint" in service_txt
    service_ok = bool(service_txt) and has_entry and "GeneratedResult" in service_txt
    checks["generation_service_exists"] = service_ok
    if not service_ok:
        issues.append("缺少统一生成服务 src/services/generation.ts（生成入口 / GeneratedResult）")

    # 1b. 真实 API 契约：服务能在 api 模式调用后端生成接口（不强制 mock 主导）。
    api_contract_ok = bool(service_txt) and "callRealApi" in service_txt and (
        "GENERATION_MODE" in service_txt
        and ("TEMPLATE_GENERATION_PATH" in service_txt or "IMAGE_GENERATION_PATH" in service_txt)
    )
    checks["generation_api_contract"] = api_contract_ok
    if not api_contract_ok:
        issues.append("generation.ts 缺少真实 API 契约（callRealApi/GENERATION_MODE/生成接口路径）")

    # 2. 结果页存在
    checks["result_page_exists"] = bool(result_txt)
    if not result_txt:
        issues.append("缺少结果页 src/pages/result/result.vue")

    # 3. 结果页含分享 CTA + 解锁钩子 + 水印/去水印逻辑
    result_share = ("open-type=\"share\"" in result_txt) or ("shareTitle" in result_txt) or ("分享" in result_txt)
    result_unlock = ("unlock" in result_txt.lower()) or ("解锁" in result_txt) or ("unlockHint" in result_txt)
    result_watermark = ("watermark" in result_txt.lower()) or ("水印" in result_txt)
    checks["result_has_share_cta"] = result_share
    checks["result_has_unlock_hook"] = result_unlock
    checks["result_has_watermark"] = result_watermark
    if not result_share:
        issues.append("结果页缺少分享 CTA")
    if not result_unlock:
        issues.append("结果页缺少解锁钩子（unlock/解锁/unlockHint）")
    if not result_watermark:
        issues.append("结果页缺少水印/去水印逻辑（watermark/水印）")

    # 4. form 调用 generation service
    form_calls = "mockGenerate" in form_txt
    checks["form_calls_generation"] = form_calls
    if not form_calls:
        issues.append("form 页未调用 mockGenerate")

    # 5. 模板感知 mock：服务含 SELECTED_TEMPLATE/template 分支 + shareTitle/shareCopy/unlockHint/watermarkEnabled
    template_aware = ("SELECTED_TEMPLATE" in service_txt or "SELECTED_TEMPLATE" in tmpl_txt) and (
        "switch" in service_txt or "template" in service_txt.lower()
    )
    contract_fields = all(
        k in service_txt for k in ("shareTitle", "shareCopy", "unlockHint", "watermarkEnabled")
    )
    checks["generation_template_aware"] = template_aware and contract_fields
    if not (template_aware and contract_fields):
        issues.append("生成服务缺少 template-aware mock 逻辑或结果契约字段")


def _check_growth_loop_productization(miniapp_dir: Path, checks: dict, issues: list[str]) -> None:
    """传播闭环产品化分层检查（P0-2 核心）。

    区分三层：
      1. 只有文档：blueprint 无 growth_loop -> growth_loop_in_blueprint=False（未产品化）；
      2. 有传播设计：blueprint 有 growth_loop，但 generation.ts/result.vue 没消费/展示
         -> generation_consumes_growth_loop / result_displays_growth_loop=False（设计存在但产品层未接入）；
      3. 真接入：blueprint + generation.ts + result.vue 三层都到位 -> 全 True。

    并按模板能力诚实度校验：
      - funny/blessing：result/blueprint 必须出现 fallback_preview / preview mode 文案；
      - avatar/sticker/pet-talk：不得被标成 fallback_preview。
    """
    src = miniapp_dir / "src"
    blueprint_path = src / "config" / "blueprint.json"
    service_txt = _read(src / "services" / "generation.ts")
    result_txt = _read(src / "pages" / "result" / "result.vue")

    bp: dict = {}
    try:
        if blueprint_path.exists():
            bp = json.loads(blueprint_path.read_text(encoding="utf-8-sig"))
    except Exception:
        bp = {}
    gl = bp.get("growth_loop") if isinstance(bp, dict) else None
    gl = gl if isinstance(gl, dict) else {}

    # 第 1 层：blueprint 含结构化 growth_loop
    gl_in_bp = bool(gl)
    checks["growth_loop_in_blueprint"] = gl_in_bp
    if not gl_in_bp:
        issues.append("传播闭环未产品化：blueprint.json 缺少 growth_loop 结构（仅文档层）")

    # 第 2 层：generation.ts 消费 growth_loop（GeneratedResult 透传字段）
    consumes = (
        "growthLoop" in service_txt
        and "capabilityMode" in service_txt
        and "removeWatermarkSupported" in service_txt
    )
    checks["generation_consumes_growth_loop"] = consumes
    if not consumes:
        issues.append("传播设计存在但产品层未接入：generation.ts 未消费 growth_loop（growthLoop/capabilityMode/removeWatermarkSupported）")

    # 第 3 层：result.vue 展示传播闭环各状态
    r_growth = ("growthLoop" in result_txt) or ("传播闭环" in result_txt) or ("Growth Loop" in result_txt)
    r_share = ("shareCtaLabel" in result_txt) or ("分享 CTA" in result_txt) or ("open-type=\"share\"" in result_txt)
    r_unlock = ("hasUnlock" in result_txt) or ("unlockHint" in result_txt) or ("解锁机制" in result_txt)
    r_watermark = ("watermarkLabel" in result_txt) or ("水印" in result_txt)
    r_remove = ("removeWatermarkSupported" in result_txt) or ("去水印" in result_txt)
    r_brand = ("brandExposure" in result_txt) or ("brandLabel" in result_txt) or ("品牌露出" in result_txt)
    r_export = ("exportSupported" in result_txt) or ("exportLabel" in result_txt) or ("导出" in result_txt)
    r_capability = ("capabilityMode" in result_txt) or ("当前能力" in result_txt) or ("isPreviewMode" in result_txt)

    checks["result_displays_growth_loop"] = r_growth
    checks["result_displays_share_cta"] = r_share
    checks["result_displays_unlock"] = r_unlock
    checks["result_displays_watermark"] = r_watermark
    checks["result_displays_remove_watermark"] = r_remove
    checks["result_displays_brand"] = r_brand
    checks["result_displays_export"] = r_export
    checks["capability_mode_visible"] = r_capability

    if not r_growth:
        issues.append("结果页未展示传播闭环（result.vue 缺少 growthLoop / 传播闭环区域）")
    if not r_share:
        issues.append("结果页未展示分享 CTA（shareCtaLabel/分享 CTA）")
    if not r_unlock:
        issues.append("结果页未展示解锁机制（unlockHint/解锁机制）")
    if not r_watermark:
        issues.append("结果页未展示水印（watermarkLabel/水印）")
    if not r_remove:
        issues.append("结果页未展示去水印状态（removeWatermark/去水印）")
    if not r_brand:
        issues.append("结果页未展示品牌露出（brandExposure/品牌露出）")
    if not r_export:
        issues.append("结果页未展示下载/导出状态（exportSupported/导出）")
    if not r_capability:
        issues.append("结果页未展示能力模式（capabilityMode/当前能力/预览模式）")

    # 诚实度：视频边界型必须出现 fallback_preview / preview mode 文案
    template_id = bp.get("template_id", "") if isinstance(bp, dict) else ""
    is_video_preview = template_id in _VIDEO_PREVIEW_TEMPLATES or gl.get("capability_mode") == "fallback_preview"
    fallback_visible = (
        "fallback_preview" in result_txt
        or "preview mode" in result_txt.lower()
        or "预览模式" in result_txt
        or "honest fallback" in result_txt
    )
    if template_id in _VIDEO_PREVIEW_TEMPLATES:
        checks["fallback_preview_visible_for_video_templates"] = fallback_visible
        if not fallback_visible:
            issues.append(f"视频边界型模板 {template_id} 结果页缺少 fallback/preview 诚实标注（疑似伪装真实视频）")
        # 视频边界型不得在事实源里被标成 real
        if gl and gl.get("capability_mode") == "real":
            checks["video_template_not_faked_real"] = False
            issues.append(f"视频边界型模板 {template_id} 的 growth_loop.capability_mode 被标成 real（伪装真实视频）")
        else:
            checks["video_template_not_faked_real"] = True
    elif is_video_preview:
        # 兜底/通用 preview 模式也要可见
        checks["fallback_preview_visible_for_video_templates"] = fallback_visible

    # 核心模板不得被标成 fallback_preview
    if template_id in _CORE_RUNNABLE_TEMPLATES:
        not_faked = gl.get("capability_mode") != "fallback_preview"
        checks["core_template_not_downgraded"] = not_faked
        if not not_faked:
            issues.append(f"核心可跑通模板 {template_id} 被标成 fallback_preview（能力口径错误）")


def _check_rewarded_ad_loop(output_dir: Path, miniapp_dir: Path, checks: dict, issues: list[str]) -> None:
    """检查激励广告下载闭环（P0-2 商业化可验收 + 漏斗埋点）。

    覆盖：blueprint 的 download_gate、ads.ts 配置、result.vue 走广告解锁而非直接下载、
    导出能力（图/视频/文本预览）、视频边界型不伪装视频、mock 构建 effective=fallback_preview、
    analytics 埋点存在且被调用。
    """
    src = miniapp_dir / "src"
    result_txt = _read(src / "pages" / "result" / "result.vue")
    service_txt = _read(src / "services" / "generation.ts")
    analytics_txt = _read(src / "services" / "analytics.ts")
    ads_txt = _read(src / "config" / "ads.ts")

    bp: dict = {}
    try:
        bp_path = src / "config" / "blueprint.json"
        if bp_path.exists():
            bp = json.loads(bp_path.read_text(encoding="utf-8-sig"))
    except Exception:
        bp = {}
    gl = bp.get("growth_loop") if isinstance(bp, dict) else None
    gl = gl if isinstance(gl, dict) else {}
    gate = gl.get("download_gate") if isinstance(gl, dict) else None
    gate = gate if isinstance(gate, dict) else {}
    template_id = bp.get("template_id", "") if isinstance(bp, dict) else ""

    # 1. blueprint 含 download_gate（viral 模板必须有）。
    gate_in_bp = bool(gate)
    checks["rewarded_ad_gate_in_blueprint"] = gate_in_bp
    if not gate_in_bp:
        issues.append("blueprint.json 缺少 growth_loop.download_gate（激励广告门槛事实源）")

    # 2. ads.ts 配置存在（REWARDED_AD_UNIT_ID / REWARDED_AD_ENABLED 注入点）。
    ad_config_present = "REWARDED_AD_UNIT_ID" in ads_txt and "REWARDED_AD_ENABLED" in ads_txt
    checks["rewarded_ad_config_present"] = ad_config_present
    if not ad_config_present:
        issues.append("缺少 src/config/ads.ts 广告位配置（REWARDED_AD_UNIT_ID/REWARDED_AD_ENABLED）")

    # 3. result.vue 经激励广告解锁，不直接下载。
    uses_unlock = "requestRewardedAdUnlock" in result_txt
    checks["result_uses_rewarded_ad_unlock"] = uses_unlock
    if not uses_unlock:
        issues.append("result.vue 未调用 requestRewardedAdUnlock（下载未经激励广告门槛）")

    # 4. result.vue 根据广告门槛拦截下载（isRewardedAdRequired / adUnlocked / downloadUnlocked）。
    blocks_before_ad = ("isRewardedAdRequired" in result_txt) and (
        "adUnlocked" in result_txt or "downloadUnlocked" in result_txt or "isRewardedAdRequired" in result_txt
    )
    checks["result_blocks_download_before_ad"] = blocks_before_ad
    if not blocks_before_ad:
        issues.append("result.vue 未在广告完成前拦截下载（缺 isRewardedAdRequired/adUnlocked 判断）")

    # 5. result.vue 埋点（trackGrowthEvent）+ analytics 模块存在。
    tracks_events = ("trackGrowthEvent" in result_txt or "trackGrowthEvent" in service_txt) and bool(analytics_txt)
    checks["result_tracks_growth_events"] = tracks_events
    if not tracks_events:
        issues.append("缺少下载漏斗埋点（analytics.trackGrowthEvent 未接入 result.vue/generation.ts）")

    # 6. 导出能力：图 / 视频 / 文本预览三类保存路径在 result.vue 中存在。
    checks["export_supports_remote_image"] = "saveImageToPhotosAlbum" in result_txt
    checks["export_supports_remote_video"] = "saveVideoToPhotosAlbum" in result_txt
    checks["export_supports_text_preview"] = "setClipboardData" in result_txt
    if "saveImageToPhotosAlbum" not in result_txt:
        issues.append("result.vue 缺少图片保存路径（saveImageToPhotosAlbum）")
    if "saveVideoToPhotosAlbum" not in result_txt:
        issues.append("result.vue 缺少视频保存路径（saveVideoToPhotosAlbum）")
    if "setClipboardData" not in result_txt:
        issues.append("result.vue 缺少文本预览导出路径（setClipboardData）")

    # 7. 视频边界型不伪装视频：gate 文案不得出现下载/真实视频，required_for 不含 download。
    no_video_claim = True
    if template_id in _VIDEO_PREVIEW_TEMPLATES:
        blob = f"{gate.get('gate_label', '')} {gate.get('reward_label', '')} {gl.get('export_label', '')}"
        forbidden = ["下载视频", "下载祝福视频", "生成视频", "真实视频", "视频已生成"]
        if any(p in blob for p in forbidden):
            no_video_claim = False
            issues.append(f"视频边界型 {template_id} download_gate 文案宣称视频下载/生成（伪装真实视频）")
        if "download" in (gate.get("required_for") or []):
            no_video_claim = False
            issues.append(f"视频边界型 {template_id} download_gate.required_for 不应含 download")
    checks["no_video_claim_for_preview_templates"] = no_video_claim

    # 8. mock 构建下 effective summary 必须 fallback_preview（generator-source.json）。
    gen_source: dict = {}
    try:
        gs_path = output_dir / "generator-source.json"
        if gs_path.exists():
            gen_source = json.loads(gs_path.read_text(encoding="utf-8-sig"))
    except Exception:
        gen_source = {}
    mode = gen_source.get("generation_mode", "")
    eff = gen_source.get("effective_growth_loop_summary") or {}
    if mode and mode != "api" and gen_source.get("real_generation") is True:
        eff_preview = eff.get("capability_mode") == "fallback_preview"
        checks["mock_runtime_effective_preview_visible"] = eff_preview
        if not eff_preview:
            issues.append("mock 构建下核心模板 effective_growth_loop_summary 未降级为 fallback_preview")


def run_growth_qa(output_dir: Path, miniapp_dir: Path | None = None) -> dict:
    """检查 growth 产物完整性、关键要素，以及生成代码的传播+交互闭环。"""
    issues: list[str] = []
    checks: dict = {}

    growth_plan = output_dir / "growth-plan.md"
    share_strategy = output_dir / "share-strategy.md"
    viral_score = output_dir / "viral-score.json"

    # 1. 产物存在性
    checks["growth_plan_exists"] = growth_plan.exists()
    checks["share_strategy_exists"] = share_strategy.exists()
    checks["viral_score_exists"] = viral_score.exists()
    if not growth_plan.exists():
        issues.append("growth-plan.md 不存在")
    if not share_strategy.exists():
        issues.append("share-strategy.md 不存在")
    if not viral_score.exists():
        issues.append("viral-score.json 不存在")

    # 2. growth-plan 关键要素
    growth_keywords_ok = True
    if growth_plan.exists():
        text = growth_plan.read_text(encoding="utf-8-sig")
        for kw in ["增长重心", "渠道", "裂变", "指标"]:
            if kw not in text:
                growth_keywords_ok = False
                issues.append(f"growth-plan.md 缺少要素: {kw}")
    else:
        growth_keywords_ok = False
    checks["growth_plan_complete"] = growth_keywords_ok

    # 3. share-strategy 关键要素（分享钩子 + 激励 + 裂变路径）
    share_keywords_ok = True
    if share_strategy.exists():
        text = share_strategy.read_text(encoding="utf-8-sig")
        for kw in ["分享钩子", "激励", "裂变", "水印"]:
            if kw not in text:
                share_keywords_ok = False
                issues.append(f"share-strategy.md 缺少要素: {kw}")
    else:
        share_keywords_ok = False
    checks["share_strategy_complete"] = share_keywords_ok

    # 4. 生成小程序代码的传播链路（分享 CTA / 解锁裂变钩子 / 可传播结果页）
    if miniapp_dir is not None:
        has_share = _scan_generated(miniapp_dir, _SHARE_CTA)
        has_unlock = _scan_generated(miniapp_dir, _UNLOCK_HOOK)
        has_result = _scan_generated(miniapp_dir, _RESULT_PAGE)
        checks["code_has_share_cta"] = has_share
        checks["code_has_unlock_hook"] = has_unlock
        checks["code_has_result_page"] = has_result
        if not has_share:
            issues.append("生成代码未发现分享 CTA（传播入口缺失）")
        if not has_unlock:
            issues.append("生成代码未发现解锁/裂变机制预留")
        if not has_result:
            issues.append("生成代码未发现可传播结果页")

        # 5. 生成项目的交互闭环结构（generation service / result / form / 模板感知）
        _check_generation_flow(miniapp_dir, checks, issues)

        # 6. 传播闭环产品化分层（P0-2）：blueprint -> generation.ts -> result.vue 三层接入
        _check_growth_loop_productization(miniapp_dir, checks, issues)

        # 7. 激励广告下载闭环（P0-2 商业化可验收 + 漏斗埋点）
        _check_rewarded_ad_loop(output_dir, miniapp_dir, checks, issues)

    passed = all(checks.values())
    return {"passed": passed, "checks": checks, "issues": issues}


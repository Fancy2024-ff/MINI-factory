"""core.qa.growth_qa — 增长/裂变交付质量验证。

职责：
  1. 增长产物齐全（growth-plan.md / share-strategy.md / viral-score.json）；
  2. growth/share 文档含必要裂变要素（分享钩子、激励、裂变回环、去水印）；
  3. 生成的小程序代码本身含传播链路：分享 CTA、解锁/裂变机制、品牌露出位。
规则版 v1。
"""

from __future__ import annotations

from pathlib import Path

# 生成代码中传播链路信号（命中即视为该传播位已预留）
_SHARE_CTA = ["分享", "share", "转发", "晒"]
_UNLOCK_HOOK = ["解锁", "unlock", "邀请", "invite", "去水印", "watermark", "高清"]
_RESULT_PAGE = ["result", "gallery", "pack", "clip", "greeting", "preview", "结果", "作品"]


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

    passed = all(checks.values())
    return {"passed": passed, "checks": checks, "issues": issues}


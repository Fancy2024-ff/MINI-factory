"""Regression guard for miniapp generation.

Canonical execution source of the miniapp project is
core/generator/codegen.py (generate_miniapp); skeleton fact source is
core/generator/src/templates/base. generate_miniapp must only copy that
template + overlay + inject app data — it must NOT re-author skeleton files.
These tests fail if generation drifts away from the template source.
"""

import json
from pathlib import Path

import pytest

from core.generator.codegen import generate_miniapp

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BASE_TEMPLATE = PROJECT_ROOT / "core" / "generator" / "src" / "templates" / "base"


@pytest.fixture
def sample_app():
    return {
        "name": "AI Writing Assistant",
        "name_cn": "AI 写作助手",
        "description_cn": "支持文章、邮件、社交文案的 AI 写作助手，提供语法纠正与翻译。",
        "features_cn": ["语法纠正", "语气调整", "翻译"],
    }


@pytest.fixture
def sample_prd():
    return {"target_platforms": ["wechat", "alipay"]}


@pytest.fixture
def generated(sample_app, sample_prd, tmp_path):
    miniapp_dir, gen_source = generate_miniapp(sample_app, sample_prd, tmp_path)
    return miniapp_dir, gen_source


def test_canonical_vite_config_ts_only(generated):
    miniapp_dir, _ = generated
    assert (miniapp_dir / "vite.config.ts").exists()
    # .mjs would silently break the build (uni is not a function).
    assert not (miniapp_dir / "vite.config.mjs").exists()


def test_manifest_and_pages_under_src(generated):
    miniapp_dir, _ = generated
    assert (miniapp_dir / "src" / "manifest.json").exists()
    assert (miniapp_dir / "src" / "pages.json").exists()
    # NOT at project root
    assert not (miniapp_dir / "manifest.json").exists()
    assert not (miniapp_dir / "pages.json").exists()


def test_key_skeleton_files_present(generated):
    miniapp_dir, _ = generated
    for rel in [
        "package.json", "tsconfig.json", "index.html", "vite.config.ts",
        "src/main.ts", "src/App.vue", "src/uni.scss", "src/utils/request.ts",
        "src/pages/index/index.vue", "src/pages/form/form.vue",
        "src/pages/result/result.vue", "src/pages/profile/profile.vue",
    ]:
        assert (miniapp_dir / rel).exists(), f"missing {rel}"


def test_no_unfilled_tokens(generated):
    """Token contract must be fully substituted — no __APP_*__ left behind."""
    miniapp_dir, _ = generated
    for f in miniapp_dir.rglob("*"):
        if f.is_file() and f.suffix in (".vue", ".json", ".ts", ".md", ".html"):
            text = f.read_text(encoding="utf-8")
            assert "__APP_" not in text, f"unfilled token in {f.relative_to(miniapp_dir)}"


def test_app_data_injected(generated, sample_app):
    miniapp_dir, _ = generated
    index = (miniapp_dir / "src" / "pages" / "index" / "index.vue").read_text(encoding="utf-8")
    assert sample_app["name_cn"] in index
    for feat in sample_app["features_cn"]:
        assert feat in index
    pkg = json.loads((miniapp_dir / "package.json").read_text(encoding="utf-8"))
    assert pkg["description"] == sample_app["description_cn"]


def test_deps_come_from_template(generated):
    """package.json deps/scripts must equal the template's — no Python-side copy."""
    miniapp_dir, _ = generated
    template_pkg = json.loads((BASE_TEMPLATE / "package.json").read_text(encoding="utf-8-sig"))
    gen_pkg = json.loads((miniapp_dir / "package.json").read_text(encoding="utf-8"))
    assert gen_pkg["devDependencies"] == template_pkg["devDependencies"]
    assert gen_pkg["dependencies"] == template_pkg["dependencies"]
    assert gen_pkg["scripts"] == template_pkg["scripts"]


def test_vite_config_matches_template_exactly(generated):
    """The build-critical config must be byte-identical to the canonical template."""
    miniapp_dir, _ = generated
    template_cfg = (BASE_TEMPLATE / "vite.config.ts").read_text(encoding="utf-8")
    gen_cfg = (miniapp_dir / "vite.config.ts").read_text(encoding="utf-8")
    assert gen_cfg == template_cfg


def test_all_generated_text_is_clean_utf8(generated):
    """No mojibake / non-UTF-8 in generated text artifacts."""
    miniapp_dir, _ = generated
    for f in miniapp_dir.rglob("*"):
        if f.is_file() and f.suffix in (".vue", ".json", ".ts", ".md", ".html"):
            raw = f.read_bytes()
            if raw[:3] == b"\xef\xbb\xbf":
                raw = raw[3:]
            text = raw.decode("utf-8")  # raises on non-UTF-8
            assert "�" not in text, f"replacement char in {f.name}"


# --- 生成项目交互闭环结构（P1） ---

def test_generation_service_present(generated):
    """生成项目必须包含统一生成服务，定义 mockGenerate + GeneratedResult 契约。"""
    miniapp_dir, _ = generated
    svc = miniapp_dir / "src" / "services" / "generation.ts"
    assert svc.exists(), "缺少 src/services/generation.ts"
    txt = svc.read_text(encoding="utf-8")
    for token in ("mockGenerate", "GeneratedResult", "shareTitle", "shareCopy",
                  "unlockHint", "watermarkEnabled"):
        assert token in txt, f"generation.ts 缺少契约 {token}"


def test_selected_template_injected(generated):
    """src/config/template.ts 必须注入真实 selected_template（默认 base）。"""
    miniapp_dir, gen_source = generated
    cfg = miniapp_dir / "src" / "config" / "template.ts"
    assert cfg.exists(), "缺少 src/config/template.ts"
    txt = cfg.read_text(encoding="utf-8")
    assert "__APP_TEMPLATE__" not in txt, "模板 token 未替换"
    assert f"'{gen_source['template']}'" in txt or f'"{gen_source["template"]}"' in txt, \
        f"template.ts 未反映 selected_template={gen_source['template']}"


def test_form_calls_generation_service(generated):
    """form 页必须调用 generation service 的 mockGenerate。"""
    miniapp_dir, _ = generated
    form = (miniapp_dir / "src" / "pages" / "form" / "form.vue").read_text(encoding="utf-8")
    assert "mockGenerate" in form, "form.vue 未调用 mockGenerate"


def test_form_is_blueprint_driven(generated):
    """form 页必须 blueprint-driven：消费 loadBlueprint().input_fields，
    渲染 options、识别 drives_generation、把字段写入 extra。"""
    miniapp_dir, _ = generated
    form = (miniapp_dir / "src" / "pages" / "form" / "form.vue").read_text(encoding="utf-8")
    assert "loadBlueprint" in form, "form.vue 未读取 blueprint"
    assert "input_fields" in form, "form.vue 未消费 blueprint.input_fields"
    assert "options" in form, "form.vue 未渲染 select 的 options"
    assert "drives_generation" in form, "form.vue 未识别占位 image（drives_generation）"
    assert "extra" in form, "form.vue 未把字段写入 extra"
    # 占位图必须显式标注不参与生成。
    assert "不参与生成" in form, "form.vue 占位 image 未标注『不参与生成』"


def test_result_page_has_share_unlock_watermark(generated):
    """result 页必须含分享 CTA + 解锁钩子 + 水印逻辑。"""
    miniapp_dir, _ = generated
    result = (miniapp_dir / "src" / "pages" / "result" / "result.vue").read_text(encoding="utf-8")
    assert "open-type=\"share\"" in result or "shareTitle" in result, "result.vue 缺少分享 CTA"
    assert "unlock" in result.lower() or "解锁" in result, "result.vue 缺少解锁钩子"
    assert "watermark" in result.lower() or "水印" in result, "result.vue 缺少水印逻辑"


def test_selected_template_reflects_overlay(sample_app, sample_prd, tmp_path):
    """指定 avatar-viral 时，template.ts 必须反映该模板（template-aware mock 依赖它）。"""
    miniapp_dir, gen_source = generate_miniapp(sample_app, sample_prd, tmp_path, template="avatar-viral")
    assert gen_source["template"] == "avatar-viral"
    cfg = (miniapp_dir / "src" / "config" / "template.ts").read_text(encoding="utf-8")
    assert "avatar-viral" in cfg


# --- blueprint 接入（v2） ---

def test_blueprint_json_generated(generated):
    """生成项目必须包含 src/config/blueprint.json，含 template_id + preview_type。"""
    miniapp_dir, _ = generated
    bp_path = miniapp_dir / "src" / "config" / "blueprint.json"
    assert bp_path.exists(), "缺少 src/config/blueprint.json"
    bp = json.loads(bp_path.read_text(encoding="utf-8"))
    assert bp.get("template_id")
    assert bp.get("preview_type")


def test_preview_type_injected(sample_app, sample_prd, tmp_path):
    """template.ts 必须注入 PREVIEW_TYPE，且与 blueprint.json 一致。"""
    miniapp_dir, _ = generate_miniapp(sample_app, sample_prd, tmp_path, template="avatar-viral")
    cfg = (miniapp_dir / "src" / "config" / "template.ts").read_text(encoding="utf-8")
    assert "PREVIEW_TYPE" in cfg
    assert "__APP_PREVIEW_TYPE__" not in cfg
    bp = json.loads((miniapp_dir / "src" / "config" / "blueprint.json").read_text(encoding="utf-8"))
    assert f"'{bp['preview_type']}'" in cfg or f'"{bp["preview_type"]}"' in cfg
    # avatar-viral 的 preview_type 应为 avatar
    assert bp["preview_type"] == "avatar"


def test_generation_service_blueprint_driven(generated):
    """generation.ts 必须支持 blueprint 驱动（loadBlueprint + generateFromBlueprint）。"""
    miniapp_dir, _ = generated
    svc = (miniapp_dir / "src" / "services" / "generation.ts").read_text(encoding="utf-8")
    assert "loadBlueprint" in svc, "generation.ts 缺少 loadBlueprint"
    assert "generateFromBlueprint" in svc, "generation.ts 缺少 generateFromBlueprint"
    assert "blueprint.json" in svc, "generation.ts 未引用 blueprint.json"



def test_generation_api_config_present(generated):
    """Generated mini-app carries a public API config for optional real image generation."""
    miniapp_dir, _ = generated
    cfg = miniapp_dir / "src" / "config" / "api.ts"
    assert cfg.exists(), "missing src/config/api.ts"
    txt = cfg.read_text(encoding="utf-8")
    assert "GENERATION_MODE" in txt
    assert "IMAGE_GENERATION_PATH" in txt
    assert "IMAGE_GENERATION_API_KEY" not in txt
    assert "IMAGE_GENERATION_ENDPOINT" not in txt


def test_generation_service_has_api_mode_path(generated):
    """generation.ts is API-first: calls apps/api for ai-image AND template models."""
    miniapp_dir, _ = generated
    txt = (miniapp_dir / "src" / "services" / "generation.ts").read_text(encoding="utf-8")
    assert "callRealApi" in txt
    assert "GENERATION_MODE" in txt
    assert "IMAGE_GENERATION_PATH" in txt
    # 题材模板（avatar/sticker/pet-talk）走 template 接口，不再仅 ai-image
    assert "TEMPLATE_GENERATION_PATH" in txt
    assert "Authorization" not in txt
    assert "Bearer " not in txt


def test_generation_service_api_template_coverage(generated):
    """真实链路覆盖 ai-image + avatar/sticker/pet-talk；视频模板走诚实 fallback。"""
    miniapp_dir, _ = generated
    txt = (miniapp_dir / "src" / "services" / "generation.ts").read_text(encoding="utf-8")
    assert "avatar-viral" in txt and "sticker-viral" in txt and "pet-talk-viral" in txt
    # 诚实预览：视频模板不伪装真实生成
    assert "honest_fallback" in txt
    assert "funny-video-viral" in txt and "blessing-video-viral" in txt


def test_generated_api_config_has_template_path(generated):
    """生成项目 config/api.ts 暴露 template 生成路径，且不含 provider 密钥。"""
    miniapp_dir, _ = generated
    cfg = (miniapp_dir / "src" / "config" / "api.ts").read_text(encoding="utf-8")
    assert "TEMPLATE_GENERATION_PATH" in cfg
    assert "/api/generation/template" in cfg
    assert "IMAGE_GENERATION_API_KEY" not in cfg
    assert "IMAGE_GENERATION_ENDPOINT" not in cfg


def test_api_config_default_is_mock_no_token_residue(generated):
    """默认（未配置 env）生成的 api.ts 必须是 mock + 空 base，且无未填 token 残留。"""
    miniapp_dir, gen_source = generated
    txt = (miniapp_dir / "src" / "config" / "api.ts").read_text(encoding="utf-8")
    assert "__API_BASE__" not in txt and "__GENERATION_MODE__" not in txt, "api.ts 残留未填注入 token"
    assert "export const API_BASE = ''" in txt
    assert "export const GENERATION_MODE: 'mock' | 'api' = 'mock'" in txt
    assert gen_source.get("generation_mode") == "mock"


def test_api_config_api_mode_injects_https_base(sample_app, sample_prd, tmp_path, monkeypatch):
    """配置 GENERATION_MODE=api + https base 时，codegen 注入真实 api 模式与绝对域名。"""
    from core.runtime import config

    monkeypatch.setattr(config, "GENERATION_MODE", "api")
    monkeypatch.setattr(config, "GENERATED_APP_API_BASE", "https://api.example.com/")
    miniapp_dir, gen_source = generate_miniapp(sample_app, sample_prd, tmp_path)
    txt = (miniapp_dir / "src" / "config" / "api.ts").read_text(encoding="utf-8")
    assert "export const API_BASE = 'https://api.example.com'" in txt, "未注入或未规范化 https base"
    assert "export const GENERATION_MODE: 'mock' | 'api' = 'api'" in txt
    assert gen_source.get("generation_mode") == "api"


def test_api_config_non_https_base_falls_back_to_mock(sample_app, sample_prd, tmp_path, monkeypatch):
    """非 https 绝对域名（真机必崩）必须回退 mock，绝不生成会失败的 api.ts。"""
    from core.runtime import config

    monkeypatch.setattr(config, "GENERATION_MODE", "api")
    monkeypatch.setattr(config, "GENERATED_APP_API_BASE", "http://api.example.com")
    miniapp_dir, gen_source = generate_miniapp(sample_app, sample_prd, tmp_path)
    txt = (miniapp_dir / "src" / "config" / "api.ts").read_text(encoding="utf-8")
    assert "export const GENERATION_MODE: 'mock' | 'api' = 'mock'" in txt
    assert "export const API_BASE = ''" in txt
    assert gen_source.get("generation_mode") == "mock"


# --- 模板能力状态收口（P0-1）---

CORE_RUNNABLE = ("avatar-viral", "sticker-viral", "pet-talk-viral")
HONEST_PREVIEW = ("funny-video-viral", "blessing-video-viral")


def _gen(template, sample_app, sample_prd, tmp_path):
    miniapp_dir, gen_source = generate_miniapp(sample_app, sample_prd, tmp_path, template=template)
    bp = json.loads((miniapp_dir / "src" / "config" / "blueprint.json").read_text(encoding="utf-8"))
    return miniapp_dir, gen_source, bp


@pytest.mark.parametrize("template", CORE_RUNNABLE)
def test_core_template_blueprint_status(template, sample_app, sample_prd, tmp_path):
    """核心模板生成后 blueprint.json 状态正确：core_runnable + template_api + real。"""
    _, gen_source, bp = _gen(template, sample_app, sample_prd, tmp_path)
    assert bp["template_status"] == "core_runnable"
    assert bp["generation_backend"] == "template_api"
    assert bp["real_generation"] is True
    assert bp["fallback_mode"] is False
    assert bp["boundary_note"]
    # generator-source.json 记录真实状态
    assert gen_source["template_status"] == "core_runnable"
    assert gen_source["real_generation"] is True
    assert gen_source["fallback_mode"] is False


@pytest.mark.parametrize("template", HONEST_PREVIEW)
def test_honest_preview_blueprint_status(template, sample_app, sample_prd, tmp_path):
    """funny/blessing 生成后 blueprint.json 是 honest_preview + fallback_mode true，
    但 blueprint_is_fallback false（它们有自己的 template.json，非兜底配置）。"""
    _, gen_source, bp = _gen(template, sample_app, sample_prd, tmp_path)
    assert bp["template_status"] == "honest_preview"
    assert bp["generation_backend"] == "honest_fallback"
    assert bp["real_generation"] is False
    assert bp["fallback_mode"] is True
    assert bp["is_fallback"] is False  # 关键区分：不是兜底配置
    assert gen_source["blueprint_is_fallback"] is False
    assert gen_source["fallback_mode"] is True
    assert gen_source["template_status"] == "honest_preview"


def test_generation_service_api_template_split(generated):
    """generation.ts: API_TEMPLATES 含三个核心模板，PREVIEW_ONLY 含 funny/blessing。"""
    miniapp_dir, _ = generated
    txt = (miniapp_dir / "src" / "services" / "generation.ts").read_text(encoding="utf-8")
    assert "const API_TEMPLATES = ['ai-image', 'avatar-viral', 'sticker-viral', 'pet-talk-viral']" in txt
    assert "funny-video-viral" in txt and "blessing-video-viral" in txt
    # 核心模板不在 PREVIEW_ONLY
    assert "PREVIEW_ONLY_TEMPLATES = ['funny-video-viral', 'blessing-video-viral']" in txt
    # API 失败显式降级标记，不静默伪装
    assert "apiFailed" in txt
    assert "fallbackReason" in txt


def test_result_page_shows_template_status(generated):
    """result.vue 展示模板真实状态（status / previewType / boundaryNote / 真实生成）。"""
    miniapp_dir, _ = generated
    result = (miniapp_dir / "src" / "pages" / "result" / "result.vue").read_text(encoding="utf-8")
    assert "previewType" in result
    assert "boundaryNote" in result
    assert "真实生成" in result
    assert "honest fallback" in result
    assert "templateStatus" in result


def test_result_page_renders_real_image_block(generated):
    """result.vue 必须有通用真实图片渲染块（hasRealImage），让 avatar/sticker/petVideo
    真实生成图可见，而不是只把真实结果存进 storage。"""
    miniapp_dir, _ = generated
    result = (miniapp_dir / "src" / "pages" / "result" / "result.vue").read_text(encoding="utf-8")
    assert "hasRealImage" in result, "result.vue 缺少通用真实图片渲染判断"
    # 通用块对 image_base64 也兜底渲染
    assert "image_base64" in result


def test_result_page_video_boundary_text_is_guarded(generated):
    """「真实视频生成是后续能力边界」文案必须被 isVideoBoundaryTemplate 守卫，
    不允许对所有非核心结果无条件展示视频边界提示；通用提示优先用 boundaryNote。"""
    miniapp_dir, _ = generated
    result = (miniapp_dir / "src" / "pages" / "result" / "result.vue").read_text(encoding="utf-8")
    assert "isVideoBoundaryTemplate" in result, "缺少视频边界型模板守卫"
    assert "funny-video-viral" in result and "blessing-video-viral" in result
    # 视频边界文案只在 isVideoBoundaryTemplate computed 内部出现，非模板顶层无条件渲染。
    assert "nonCoreHint" in result
    # 顶层 boundary-note 用 nonCoreHint，而不是写死视频文案
    assert "{{ nonCoreHint }}" in result


# --- 传播闭环 growth_loop 贯穿（P0-2）---


def test_blueprint_json_carries_growth_loop(sample_app, sample_prd, tmp_path):
    """生成 avatar-viral 后 blueprint.json 必须含完整 growth_loop。"""
    miniapp_dir, _ = generate_miniapp(sample_app, sample_prd, tmp_path, template="avatar-viral")
    bp = json.loads((miniapp_dir / "src" / "config" / "blueprint.json").read_text(encoding="utf-8"))
    assert "growth_loop" in bp, "blueprint.json 缺少 growth_loop"
    gl = bp["growth_loop"]
    for k in ("has_share_cta", "share_cta_label", "unlock_type", "watermark_label",
              "remove_watermark_supported", "brand_label", "export_label", "capability_mode"):
        assert k in gl, f"blueprint.json growth_loop 缺键 {k}"
    assert gl["capability_mode"] == "real"


def test_generation_ts_consumes_growth_loop(generated):
    """generation.ts 必须消费 growth_loop（GeneratedResult 透传字段）。"""
    miniapp_dir, _ = generated
    txt = (miniapp_dir / "src" / "services" / "generation.ts").read_text(encoding="utf-8")
    for token in ("growthLoop", "shareCtaLabel", "removeWatermarkSupported",
                  "capabilityMode", "exportSupported", "brandExposure"):
        assert token in txt, f"generation.ts 缺少 growth_loop 字段 {token}"
    # 三条路径共用的事实源映射函数
    assert "growthFields" in txt


def test_result_vue_displays_growth_loop(generated):
    """result.vue 必须展示传播闭环各状态。"""
    miniapp_dir, _ = generated
    txt = (miniapp_dir / "src" / "pages" / "result" / "result.vue").read_text(encoding="utf-8")
    assert "传播闭环" in txt or "Growth Loop" in txt
    assert "shareCtaLabel" in txt
    assert "removeWatermarkSupported" in txt
    assert "brandExposure" in txt or "brandLabel" in txt
    assert "exportSupported" in txt
    assert "capabilityMode" in txt or "isPreviewMode" in txt


def test_result_vue_export_is_real_not_placeholder_toast(generated):
    """result.vue 的导出必须是真实行为（存相册 / 复制文本），不再只是「入口已预留」toast（finding #1）。"""
    miniapp_dir, _ = generated
    txt = (miniapp_dir / "src" / "pages" / "result" / "result.vue").read_text(encoding="utf-8")
    # 真实导出能力：远程图存相册 + 文本复制剪贴板。
    assert "saveImageToPhotosAlbum" in txt, "导出未实现存相册"
    assert "downloadFile" in txt, "导出未实现下载远程图"
    assert "setClipboardData" in txt, "导出未实现文本复制"
    # handleExport 不得是「只 toast 入口已预留」的占位实现。
    assert "已保存到相册" in txt or "已复制到剪贴板" in txt


def test_result_vue_watermark_and_cta_gated_by_facts(generated):
    """result.vue 分享/解锁/水印必须由事实源字段驱动，而非永远显示（finding #6）。"""
    miniapp_dir, _ = generated
    txt = (miniapp_dir / "src" / "pages" / "result" / "result.vue").read_text(encoding="utf-8")
    # 分享 CTA 受 hasShareCta 控制。
    assert "hasShareCta" in txt
    # 解锁/去水印受 hasUnlock + removeWatermarkSupported 控制。
    assert "canRemoveWatermark" in txt or "removeWatermarkSupported" in txt
    assert "hasUnlock" in txt


def test_generation_ts_downgrades_growthloop_on_apifail(generated):
    """generation.ts 必须在 API 失败时整体降级 growthLoop（finding #2）。"""
    miniapp_dir, _ = generated
    txt = (miniapp_dir / "src" / "services" / "generation.ts").read_text(encoding="utf-8")
    assert "downgradeGrowthLoopForFallback" in txt
    # 水印初始态来自事实源 has_watermark，而非硬编码 true（finding #6）。
    assert "has_watermark !== false" in txt


def test_generation_ts_mock_runtime_local_preview(generated):
    """generation.ts 必须在 mock 运行模式下把核心模板降级为本地预览（finding #2）。"""
    miniapp_dir, _ = generated
    txt = (miniapp_dir / "src" / "services" / "generation.ts").read_text(encoding="utf-8")
    assert "buildLocalPreviewFallback" in txt, "缺少本地预览降级函数"
    assert "local_preview" in txt and "mock_preview" in txt
    # base64-only 导出降级（finding #1）。
    assert "downgradeExportForBase64Only" in txt
    # 导出能力判定纯函数（finding #3 行为级）。
    assert "classifyExportTarget" in txt and "buildExportText" in txt


def test_result_vue_export_uses_classifier(generated):
    """result.vue 导出必须走 classifyExportTarget（与单测同源），且按路径判定（finding #3）。"""
    miniapp_dir, _ = generated
    txt = (miniapp_dir / "src" / "pages" / "result" / "result.vue").read_text(encoding="utf-8")
    assert "classifyExportTarget" in txt
    # 导出按钮受真实导出路径 canExport 约束，不只看 exportSupported。
    assert "canExport" in txt


def test_gen_source_has_growth_loop_summary(generated):
    """generator-source.json（gen_source）必须含 growth_loop 摘要字段。"""
    _, gen_source = generated
    assert "growth_loop_summary" in gen_source
    summ = gen_source["growth_loop_summary"]
    for k in ("growth_loop_present", "has_share_cta", "has_unlock", "has_watermark",
              "remove_watermark_supported", "brand_exposure", "download_supported",
              "export_supported", "capability_mode"):
        assert k in summ, f"growth_loop_summary 缺键 {k}"
    # codegen_report 也带摘要
    report = gen_source["codegen_report"]
    assert "growth_loop_present" in report
    assert "capability_mode" in report


@pytest.mark.parametrize("template", CORE_RUNNABLE)
def test_core_template_growth_loop_real(template, sample_app, sample_prd, tmp_path):
    """核心模板生成后 growth_loop / 摘要 capability_mode 必须为 real。"""
    miniapp_dir, gen_source = generate_miniapp(sample_app, sample_prd, tmp_path, template=template)
    bp = json.loads((miniapp_dir / "src" / "config" / "blueprint.json").read_text(encoding="utf-8"))
    assert bp["growth_loop"]["capability_mode"] == "real"
    assert gen_source["growth_loop_summary"]["capability_mode"] == "real"


@pytest.mark.parametrize("template", HONEST_PREVIEW)
def test_video_template_growth_loop_fallback_preview(template, sample_app, sample_prd, tmp_path):
    """funny/blessing 生成后 growth_loop.capability_mode 必须为 fallback_preview（不伪装真实视频）。"""
    miniapp_dir, gen_source = generate_miniapp(sample_app, sample_prd, tmp_path, template=template)
    bp = json.loads((miniapp_dir / "src" / "config" / "blueprint.json").read_text(encoding="utf-8"))
    assert bp["growth_loop"]["capability_mode"] == "fallback_preview"
    assert gen_source["growth_loop_summary"]["capability_mode"] == "fallback_preview"


# --- P0-2 激励广告门槛 + effective/template 双摘要（finding #6 收口）---

def test_ads_config_injected(generated):
    """生成项目必须含 src/config/ads.ts，且默认（未配置）为 enabled=false + 空 id（诚实）。"""
    miniapp_dir, gen_source = generated
    ads = miniapp_dir / "src" / "config" / "ads.ts"
    assert ads.exists(), "缺少 src/config/ads.ts"
    txt = ads.read_text(encoding="utf-8")
    assert "REWARDED_AD_UNIT_ID" in txt
    assert "REWARDED_AD_ENABLED" in txt
    # 未配置 -> 空 id + false，运行时诚实提示，不假装广告可用。
    assert "REWARDED_AD_UNIT_ID = ''" in txt
    assert "'false' as string" in txt or "= false" in txt
    assert gen_source.get("rewarded_ad_enabled") is False


def test_ads_config_enabled_when_unit_id_set(sample_app, sample_prd, tmp_path, monkeypatch):
    """配置 REWARDED_AD_UNIT_ID 时，ads.ts 注入真实广告位 + enabled=true。"""
    from core.runtime import config
    monkeypatch.setattr(config, "REWARDED_AD_UNIT_ID", "adunit-abc123", raising=False)
    miniapp_dir, gen_source = generate_miniapp(sample_app, sample_prd, tmp_path, template="avatar-viral")
    txt = (miniapp_dir / "src" / "config" / "ads.ts").read_text(encoding="utf-8")
    assert "adunit-abc123" in txt
    assert "'true' as string" in txt or "= true" in txt
    assert gen_source.get("rewarded_ad_enabled") is True


@pytest.mark.parametrize("template", CORE_RUNNABLE)
def test_effective_summary_mock_downgrades_core(template, sample_app, sample_prd, tmp_path):
    """mock 构建（默认）下核心模板：template summary=real，但 effective=fallback_preview + export/download false。"""
    _, gen_source = generate_miniapp(sample_app, sample_prd, tmp_path, template=template)
    assert gen_source["generation_mode"] == "mock"
    tmpl = gen_source["template_growth_loop_summary"]
    eff = gen_source["effective_growth_loop_summary"]
    # 模板事实源仍 real（区分清楚）。
    assert tmpl["capability_mode"] == "real"
    assert tmpl["export_supported"] is True
    # 运行时有效：mock 构建不显示 real / 高清导出。
    assert eff["capability_mode"] == "fallback_preview"
    assert eff["export_supported"] is False
    assert eff["download_supported"] is False
    assert eff.get("effective_note")
    # codegen_report 也带 effective 摘要。
    assert gen_source["codegen_report"]["effective_growth_loop_summary"]["capability_mode"] == "fallback_preview"


@pytest.mark.parametrize("template", CORE_RUNNABLE)
def test_effective_summary_api_keeps_real(template, sample_app, sample_prd, tmp_path, monkeypatch):
    """api 构建（https base）下核心模板 effective 保持 real（不误降级）。"""
    from core.runtime import config
    monkeypatch.setattr(config, "GENERATION_MODE", "api")
    monkeypatch.setattr(config, "GENERATED_APP_API_BASE", "https://api.example.com")
    _, gen_source = generate_miniapp(sample_app, sample_prd, tmp_path, template=template)
    assert gen_source["generation_mode"] == "api"
    eff = gen_source["effective_growth_loop_summary"]
    assert eff["capability_mode"] == "real"
    assert eff["export_supported"] is True


def test_blueprint_carries_download_gate(sample_app, sample_prd, tmp_path):
    """生成项目 blueprint.json 必须保留 growth_loop.download_gate（运行时广告门槛事实源）。"""
    miniapp_dir, _ = generate_miniapp(sample_app, sample_prd, tmp_path, template="avatar-viral")
    bp = json.loads((miniapp_dir / "src" / "config" / "blueprint.json").read_text(encoding="utf-8"))
    gate = bp["growth_loop"].get("download_gate")
    assert gate is not None
    assert gate["gate_type"] == "rewarded_ad"
    assert "remove_watermark" in gate["required_for"]


def test_result_vue_uses_rewarded_ad_gate(generated):
    """result.vue 下载必须经激励广告门槛（requestRewardedAdUnlock），不是直接下载。"""
    miniapp_dir, _ = generated
    txt = (miniapp_dir / "src" / "pages" / "result" / "result.vue").read_text(encoding="utf-8")
    assert "requestRewardedAdUnlock" in txt
    assert "isRewardedAdRequired" in txt
    # 真实保存路径：图片 + 视频 + 文本。
    assert "saveImageToPhotosAlbum" in txt
    assert "saveVideoToPhotosAlbum" in txt
    assert "setClipboardData" in txt


def test_generation_ts_exposes_ad_gate_api(generated):
    """generation.ts 暴露广告门槛 API（requestRewardedAdUnlock/markAdUnlocked/isRewardedAdRequired）。"""
    miniapp_dir, _ = generated
    txt = (miniapp_dir / "src" / "services" / "generation.ts").read_text(encoding="utf-8")
    for fn in ("requestRewardedAdUnlock", "markAdUnlocked", "isRewardedAdRequired", "unlockAfterRewardedAd"):
        assert fn in txt, f"generation.ts 缺少 {fn}"
    # remote_video 导出分类。
    assert "remote_video" in txt


# --- P0-2 激励广告埋点 + 商业闭环摘要 ---

def test_analytics_service_copied(generated):
    """生成项目必须含 src/services/analytics.ts（下载漏斗埋点）。"""
    miniapp_dir, _ = generated
    a = miniapp_dir / "src" / "services" / "analytics.ts"
    assert a.exists(), "缺少 src/services/analytics.ts"
    txt = a.read_text(encoding="utf-8")
    assert "trackGrowthEvent" in txt
    assert "getGrowthEvents" in txt  # 单测可读事件队列


def test_result_vue_tracks_funnel_events(generated):
    """result.vue 必须埋下载漏斗事件（result_view / download_click / export_*）。"""
    miniapp_dir, _ = generated
    txt = (miniapp_dir / "src" / "pages" / "result" / "result.vue").read_text(encoding="utf-8")
    assert "trackGrowthEvent" in txt
    assert "result_view" in txt
    assert "download_click" in txt
    assert "export_start" in txt


def test_generation_ts_tracks_ad_funnel(generated):
    """generation.ts 的广告流程必须埋点（request / completed / not_configured 等）。"""
    miniapp_dir, _ = generated
    txt = (miniapp_dir / "src" / "services" / "generation.ts").read_text(encoding="utf-8")
    assert "trackGrowthEvent" in txt
    assert "rewarded_ad_request" in txt
    assert "rewarded_ad_completed" in txt
    assert "download_unlocked" in txt


def test_gen_source_has_download_gate_summary(generated):
    """generator-source.json 摘要含 download_gate 字段（dashboard 商业闭环消费）。"""
    _, gen_source = generated
    summ = gen_source["growth_loop_summary"]
    assert "download_gate_type" in summ
    assert "download_gate_required_for" in summ
    assert "rewarded_ad_enabled" in gen_source


@pytest.mark.parametrize("template", CORE_RUNNABLE)
def test_core_template_gate_requires_download(template, sample_app, sample_prd, tmp_path):
    """avatar/sticker/pet-talk 的 download_gate.required_for 含 download/remove_watermark。"""
    miniapp_dir, _ = generate_miniapp(sample_app, sample_prd, tmp_path, template=template)
    bp = json.loads((miniapp_dir / "src" / "config" / "blueprint.json").read_text(encoding="utf-8"))
    gate = bp["growth_loop"]["download_gate"]
    assert "download" in gate["required_for"]
    assert "remove_watermark" in gate["required_for"]


@pytest.mark.parametrize("template", HONEST_PREVIEW)
def test_video_template_gate_export_only(template, sample_app, sample_prd, tmp_path):
    """funny/blessing 的 download_gate.required_for 只能是 export，不含 download。"""
    miniapp_dir, _ = generate_miniapp(sample_app, sample_prd, tmp_path, template=template)
    bp = json.loads((miniapp_dir / "src" / "config" / "blueprint.json").read_text(encoding="utf-8"))
    gate = bp["growth_loop"]["download_gate"]
    assert "download" not in gate["required_for"]
    assert gate["required_for"] == ["export"]

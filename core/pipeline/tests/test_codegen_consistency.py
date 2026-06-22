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


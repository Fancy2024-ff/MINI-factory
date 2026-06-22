"""core.qa.generator_qa 回归测试。

覆盖：
  - 完整模板配置通过（5 个 viral template.json + 生成产物）
  - 缺 input_fields 失败
  - preview_type 不支持失败
  - 缺 share_hooks / unlock_hooks / mock_examples 失败
  - 生成产物级：缺 blueprint.json / 残留 token / generation.ts 非 blueprint 驱动 失败
"""

import json
from pathlib import Path

import pytest

from core.qa.generator_qa import run_generator_qa


def test_full_config_passes():
    """仓库内 5 个 viral 模板配置应通过配置级检查。"""
    result = run_generator_qa()
    assert result["passed"], result["issues"]
    for t in ("avatar-viral", "sticker-viral", "pet-talk-viral",
              "funny-video-viral", "blessing-video-viral"):
        assert result["checks"][f"template_config:{t}"] is True


def _patch_templates(monkeypatch, tmp_path):
    """把 generator_qa + blueprint_builder 的 TEMPLATES_DIR 指到临时目录。"""
    import core.qa.generator_qa as gq
    import core.generator.blueprint_builder as bb
    monkeypatch.setattr(gq, "TEMPLATES_DIR", tmp_path)
    monkeypatch.setattr(bb, "TEMPLATES_DIR", tmp_path)


def _write_cfg(tmp_path: Path, template: str, cfg: dict):
    d = tmp_path / template
    d.mkdir(parents=True, exist_ok=True)
    (d / "template.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")


def _good_cfg(template="avatar-viral"):
    return {
        "id": template,
        "name_cn": "测试",
        "category": "viral",
        "preview_type": "avatar",
        "input_fields": [{"id": "x", "label": "x", "type": "text", "required": False, "placeholder": "p"}],
        "share_hooks": ["a", "b"],
        "unlock_hooks": ["a", "b"],
        "mock_examples": [{"title": "t", "preview_type": "avatar", "preview_data": {},
                           "share_title": "s", "share_copy": "c", "unlock_hint": "u"}],
    }


def test_id_mismatch_fails(tmp_path, monkeypatch):
    """template.json id 与目录名不一致必须失败。"""
    _patch_templates(monkeypatch, tmp_path)
    for t in ("avatar-viral", "sticker-viral", "pet-talk-viral",
              "funny-video-viral", "blessing-video-viral"):
        cfg = _good_cfg(t)
        cfg["id"] = "wrong-id"
        _write_cfg(tmp_path, t, cfg)
    result = run_generator_qa()
    assert not result["passed"]
    assert any("目录名不一致" in i for i in result["issues"])


def test_missing_input_fields_fails(tmp_path, monkeypatch):
    _patch_templates(monkeypatch, tmp_path)
    for t in ("avatar-viral", "sticker-viral", "pet-talk-viral",
              "funny-video-viral", "blessing-video-viral"):
        cfg = _good_cfg(t)
        cfg["input_fields"] = []
        _write_cfg(tmp_path, t, cfg)
    result = run_generator_qa()
    assert not result["passed"]
    assert result["checks"]["template_config:avatar-viral"] is False
    assert any("input_fields" in i for i in result["issues"])


def test_unsupported_preview_type_fails(tmp_path, monkeypatch):
    _patch_templates(monkeypatch, tmp_path)
    for t in ("avatar-viral", "sticker-viral", "pet-talk-viral",
              "funny-video-viral", "blessing-video-viral"):
        cfg = _good_cfg(t)
        cfg["preview_type"] = "hologram"  # 不受支持
        _write_cfg(tmp_path, t, cfg)
    result = run_generator_qa()
    assert not result["passed"]
    assert any("preview_type" in i for i in result["issues"])


def test_missing_share_unlock_mock_fails(tmp_path, monkeypatch):
    _patch_templates(monkeypatch, tmp_path)
    for t in ("avatar-viral", "sticker-viral", "pet-talk-viral",
              "funny-video-viral", "blessing-video-viral"):
        cfg = _good_cfg(t)
        cfg["share_hooks"] = []
        cfg["unlock_hooks"] = []
        cfg["mock_examples"] = []
        _write_cfg(tmp_path, t, cfg)
    result = run_generator_qa()
    assert not result["passed"]
    issues = " ".join(result["issues"])
    assert "share_hooks" in issues
    assert "unlock_hooks" in issues
    assert "mock_examples" in issues


def _make_generated_project(miniapp_dir: Path, *, with_blueprint=True,
                            blueprint_driven=True, token_residue=False):
    src = miniapp_dir / "src"
    (src / "config").mkdir(parents=True, exist_ok=True)
    (src / "services").mkdir(parents=True, exist_ok=True)
    if with_blueprint:
        (src / "config" / "blueprint.json").write_text(
            json.dumps({"template_id": "avatar-viral", "preview_type": "avatar"}),
            encoding="utf-8",
        )
    svc = "export function mockGenerate(){}"
    if blueprint_driven:
        svc = "export function loadBlueprint(){}\nexport function generateFromBlueprint(){}\n" + svc
    (src / "services" / "generation.ts").write_text(svc, encoding="utf-8")
    if token_residue:
        (src / "config" / "leak.ts").write_text("export const X = '__APP_TEMPLATE__'", encoding="utf-8")


def test_generated_project_passes(tmp_path):
    mini = tmp_path / "mini"
    _make_generated_project(mini)
    result = run_generator_qa(miniapp_dir=mini)
    assert result["checks"]["generated_blueprint_exists"] is True
    assert result["checks"]["generated_no_token_residue"] is True
    assert result["checks"]["generation_blueprint_driven"] is True


def test_generated_missing_blueprint_fails(tmp_path):
    mini = tmp_path / "mini"
    _make_generated_project(mini, with_blueprint=False)
    result = run_generator_qa(miniapp_dir=mini)
    assert result["checks"]["generated_blueprint_exists"] is False
    assert not result["passed"]


def test_generated_token_residue_fails(tmp_path):
    mini = tmp_path / "mini"
    _make_generated_project(mini, token_residue=True)
    result = run_generator_qa(miniapp_dir=mini)
    assert result["checks"]["generated_no_token_residue"] is False
    assert not result["passed"]


def test_generated_not_blueprint_driven_fails(tmp_path):
    mini = tmp_path / "mini"
    _make_generated_project(mini, blueprint_driven=False)
    result = run_generator_qa(miniapp_dir=mini)
    assert result["checks"]["generation_blueprint_driven"] is False
    assert not result["passed"]

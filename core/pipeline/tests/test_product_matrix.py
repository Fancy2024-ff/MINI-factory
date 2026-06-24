"""6 模板产物矩阵验收（P0-1 收口最终硬化）。

用 core.generator.codegen.generate_miniapp 实际生成 6 个模板的小程序产物，
对每个产物断言「固定矩阵表」：模板状态 / 生成后端 / 真实生成 / fallback /
growth_loop.capability_mode / blueprint_is_fallback；并断言关键 runtime 标记存在、
run_generator_qa(miniapp_dir) 通过。

矩阵表是事实源——改任何一个模板的能力分类，这张表必须同步改，否则测试红。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.generator.codegen import generate_miniapp
from core.qa.generator_qa import run_generator_qa

# ── 固定验收矩阵（6 模板）─────────────────────────────────────────────
# 列：template_status, generation_backend, real_generation, fallback_mode,
#     capability_mode(growth_loop), blueprint_is_fallback
MATRIX = {
    "ai-image": {
        "template_status": "core_runnable", "generation_backend": "template_api",
        "real_generation": True, "fallback_mode": False,
        "capability_mode": "real", "blueprint_is_fallback": False,
        "preview_type": "image",
    },
    "avatar-viral": {
        "template_status": "core_runnable", "generation_backend": "template_api",
        "real_generation": True, "fallback_mode": False,
        "capability_mode": "real", "blueprint_is_fallback": False,
        "preview_type": "avatar",
    },
    "sticker-viral": {
        "template_status": "core_runnable", "generation_backend": "template_api",
        "real_generation": True, "fallback_mode": False,
        "capability_mode": "real", "blueprint_is_fallback": False,
        "preview_type": "stickerPack",
    },
    "pet-talk-viral": {
        "template_status": "core_runnable", "generation_backend": "template_api",
        "real_generation": True, "fallback_mode": False,
        "capability_mode": "real", "blueprint_is_fallback": False,
        "preview_type": "petVideo",
    },
    "funny-video-viral": {
        "template_status": "honest_preview", "generation_backend": "honest_fallback",
        "real_generation": False, "fallback_mode": True,
        "capability_mode": "fallback_preview", "blueprint_is_fallback": False,
        "preview_type": "funnyStoryboard",
    },
    "blessing-video-viral": {
        "template_status": "honest_preview", "generation_backend": "honest_fallback",
        "real_generation": False, "fallback_mode": True,
        "capability_mode": "fallback_preview", "blueprint_is_fallback": False,
        "preview_type": "blessingCard",
    },
}

_APP = {"name": "Matrix App", "name_cn": "矩阵验收", "description_cn": "6 模板矩阵验收样例。",
        "features_cn": ["生成"]}
_PRD = {"target_platforms": ["wechat"]}


@pytest.mark.parametrize("template", list(MATRIX.keys()))
def test_product_matrix(template, tmp_path):
    expected = MATRIX[template]
    out_dir = tmp_path / template
    miniapp_dir, gen_source = generate_miniapp(_APP, _PRD, out_dir, template=template)

    # 1. blueprint.json 存在且字段正确。
    bp_path = miniapp_dir / "src" / "config" / "blueprint.json"
    assert bp_path.exists(), f"{template} 缺 blueprint.json"
    bp = json.loads(bp_path.read_text(encoding="utf-8"))

    assert bp["template_status"] == expected["template_status"], template
    assert bp["generation_backend"] == expected["generation_backend"], template
    assert bp["real_generation"] is expected["real_generation"], template
    assert bp["fallback_mode"] is expected["fallback_mode"], template
    assert bp["preview_type"] == expected["preview_type"], template
    assert bp["growth_loop"]["capability_mode"] == expected["capability_mode"], template
    # funny/blessing: blueprint_is_fallback=false（有自己的 template.json）但 fallback_mode=true。
    assert bp["is_fallback"] is expected["blueprint_is_fallback"], template

    # 2. gen_source 与 blueprint 口径一致。
    assert gen_source["template_status"] == expected["template_status"], template
    assert gen_source["real_generation"] is expected["real_generation"], template
    assert gen_source["fallback_mode"] is expected["fallback_mode"], template
    assert gen_source["blueprint_is_fallback"] is expected["blueprint_is_fallback"], template

    # 3. 关键 runtime 标记存在（form/result/generation.ts）。
    form = (miniapp_dir / "src" / "pages" / "form" / "form.vue").read_text(encoding="utf-8")
    result = (miniapp_dir / "src" / "pages" / "result" / "result.vue").read_text(encoding="utf-8")
    svc = (miniapp_dir / "src" / "services" / "generation.ts").read_text(encoding="utf-8")
    # form：blueprint-driven + 走纯函数归一（主字段语义不丢，见 buildGenerateInput 单测）。
    assert "loadBlueprint" in form and "input_fields" in form and "extra" in form, template
    assert "buildGenerateInput" in form, template
    # generation.ts 导出可单测的归一纯函数。
    assert "export function buildGenerateInput" in svc, template
    # result：展示能力真实度 + 真实图渲染判断。
    assert "previewType" in result and "boundaryNote" in result, template
    assert "hasRealImage" in result, template
    # generation.ts：真实链路 + 诚实预览分流。
    assert "callRealApi" in svc and "loadBlueprint" in svc, template

    # 4. GeneratorQA（产物级）通过。
    qa = run_generator_qa(miniapp_dir=miniapp_dir)
    assert qa["passed"], (template, qa["issues"])
    assert qa["checks"]["form_blueprint_driven"] is True, template


def test_matrix_covers_all_six_templates():
    """守护：矩阵必须恰好覆盖 6 个模板（5 viral + ai-image），防止漏测。"""
    assert set(MATRIX.keys()) == {
        "ai-image", "avatar-viral", "sticker-viral", "pet-talk-viral",
        "funny-video-viral", "blessing-video-viral",
    }


def test_matrix_video_boundary_split():
    """守护矩阵核心口径：4 个 real（含 pet-talk）+ 2 个 honest_preview（funny/blessing）。"""
    real = [t for t, v in MATRIX.items() if v["real_generation"]]
    honest = [t for t, v in MATRIX.items() if not v["real_generation"]]
    assert sorted(real) == ["ai-image", "avatar-viral", "pet-talk-viral", "sticker-viral"]
    assert sorted(honest) == ["blessing-video-viral", "funny-video-viral"]
    # funny/blessing: fallback_mode=true 但 blueprint_is_fallback=false（关键区分）。
    for t in honest:
        assert MATRIX[t]["fallback_mode"] is True
        assert MATRIX[t]["blueprint_is_fallback"] is False


def test_form_contract_primary_field_not_dropped(tmp_path):
    """form contract：主字段 id 不能丢。avatar 的 primary 文本字段是 style，
    生成项目的 form 必须走 buildGenerateInput（该纯函数把 primary 也写入 extra，
    行为级证明见 generator vitest buildGenerateInput 单测）。"""
    miniapp_dir, _ = generate_miniapp(_APP, _PRD, tmp_path / "avatar", template="avatar-viral")
    bp = json.loads((miniapp_dir / "src" / "config" / "blueprint.json").read_text(encoding="utf-8"))
    # avatar 的输入字段含 style（文本），它是主字段；不得在表单路径里被排除出 extra。
    field_ids = [f.get("id") for f in bp.get("input_fields", [])]
    assert "style" in field_ids, "avatar blueprint 缺 style 字段"
    form = (miniapp_dir / "src" / "pages" / "form" / "form.vue").read_text(encoding="utf-8")
    svc = (miniapp_dir / "src" / "services" / "generation.ts").read_text(encoding="utf-8")
    assert "buildGenerateInput" in form, "form 未走归一纯函数（主字段可能被丢）"
    # 纯函数注释/实现明确「所有非 image 字段都按 id 写入 extra（含 primary）」。
    assert "export function buildGenerateInput" in svc
    assert "含 primary" in svc or "含 primary 字段" in svc

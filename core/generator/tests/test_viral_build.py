"""传播型模板「真实构建级」回归。

对 avatar-viral / sticker-viral / pet-talk-viral 三套模板：
  1. 用 core.generator.codegen.generate_miniapp 真实生成项目
  2. 跑 npm install + npm run build:mp-weixin
  3. 断言 dist/build/mp-weixin 关键产物（app.js/app.json/app.wxss + 题材签名页 .js）

构建较慢（每套 ~30-60s），默认跳过；设 RUN_BUILD_TESTS=1 启用：
    RUN_BUILD_TESTS=1 python -m pytest core/generator/tests/test_viral_build.py -v

注意：非构建级的「模板可选中 + 签名页存在 + token 填充」回归在
core/generator/src/__tests__/page-builder.test.ts（vitest）中，始终运行。
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from core.generator.codegen import generate_miniapp

RUN_BUILD = os.environ.get("RUN_BUILD_TESTS") == "1"
pytestmark = pytest.mark.skipif(not RUN_BUILD, reason="set RUN_BUILD_TESTS=1 to run real build")

# 题材模板 -> 该模板独有的签名页（base 没有），构建后应出现在 dist
VIRAL_TEMPLATES = {
    "avatar-viral": "gallery",
    "sticker-viral": "pack",
    "pet-talk-viral": "upload",
    "funny-video-viral": "clip",
    "blessing-video-viral": "greeting",
}

# 题材模板 -> 期望的 blueprint.preview_type（与 template.json / generation.ts 对齐）
VIRAL_PREVIEW_TYPES = {
    "avatar-viral": "avatar",
    "sticker-viral": "stickerPack",
    "pet-talk-viral": "petVideo",
    "funny-video-viral": "funnyStoryboard",
    "blessing-video-viral": "blessingCard",
}


def _app(name, name_cn, desc_cn, features):
    return {"name": name, "name_cn": name_cn, "description_cn": desc_cn,
            "features_cn": features, "category": "Photo & Video", "monetization": "freemium"}


@pytest.mark.parametrize("template,sig_page", list(VIRAL_TEMPLATES.items()))
def test_viral_template_real_build(template, sig_page):
    work = Path(tempfile.mkdtemp(prefix=f"viral-build-{template}-"))
    try:
        app = _app(f"{template} demo", f"{template} 演示", "传播型模板真实构建测试", ["功能一", "功能二"])
        prd = {"target_platforms": ["wechat"]}
        miniapp_dir, gen_source = generate_miniapp(app, prd, work, template=template)

        assert gen_source["template"] == template, "模板未被选中"
        assert gen_source["fallback_used"] is False
        # token 契约必须完全替换：生成项目无 __APP_ 残留（含 config/template.ts）
        for f in miniapp_dir.rglob("*"):
            if f.is_file() and f.suffix in (".vue", ".json", ".ts", ".md", ".html"):
                if "node_modules" in str(f) or "dist" in str(f):
                    continue
                assert "__APP_" not in f.read_text(encoding="utf-8-sig"), \
                    f"unfilled token in {f.relative_to(miniapp_dir)}"

        # blueprint.json 存在且 template_id / preview_type 正确
        import json as _bpjson
        bp_path = miniapp_dir / "src" / "config" / "blueprint.json"
        assert bp_path.exists(), "缺少 src/config/blueprint.json"
        bp = _bpjson.loads(bp_path.read_text(encoding="utf-8-sig"))
        assert bp["template_id"] == template, f"blueprint template_id={bp['template_id']} != {template}"
        assert bp["preview_type"] == VIRAL_PREVIEW_TYPES[template], \
            f"blueprint preview_type={bp['preview_type']} != {VIRAL_PREVIEW_TYPES[template]}"
        assert bp["is_fallback"] is False, f"{template} blueprint 不应是 fallback"
        # 签名页源码存在
        assert (miniapp_dir / "src" / "pages" / sig_page / f"{sig_page}.vue").exists()
        # 签名页已注册进 pages.json（否则不会被编译进 dist）
        import json as _json
        pages_cfg = _json.loads((miniapp_dir / "src" / "pages.json").read_text(encoding="utf-8-sig"))
        registered = {p.get("path") for p in pages_cfg.get("pages", [])}
        assert f"pages/{sig_page}/{sig_page}" in registered, \
            f"signature page {sig_page} not registered in pages.json: {registered}"

        npm = shutil.which("npm")
        assert npm, "npm not found on PATH"

        r1 = subprocess.run([npm, "install"], cwd=str(miniapp_dir),
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=300)
        assert r1.returncode == 0, f"npm install failed: {(r1.stderr or r1.stdout)[-500:]}"

        r2 = subprocess.run([npm, "run", "build:mp-weixin"], cwd=str(miniapp_dir),
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=300)
        assert r2.returncode == 0, f"build failed: {(r2.stderr or r2.stdout)[-500:]}"

        dist = miniapp_dir / "dist" / "build" / "mp-weixin"
        for art in ("app.js", "app.json", "app.wxss"):
            assert (dist / art).exists(), f"missing dist artifact {art}"
        # 题材签名页被真实编译进 dist
        assert (dist / "pages" / sig_page / f"{sig_page}.js").exists(), \
            f"signature page {sig_page} not built into dist"
    finally:
        shutil.rmtree(str(work), ignore_errors=True)

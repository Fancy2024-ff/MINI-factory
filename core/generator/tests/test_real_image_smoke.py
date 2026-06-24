"""真实 provider smoke test（默认跳过）。

仅当 RUN_REAL_IMAGE_SMOKE=1 时运行；对 avatar / sticker / pet-talk 三个核心可跑通
模板各调用一次【真实 provider】（不注入 fake generate），断言拿到 image_url 或
image_base64。没有该环境变量时整组跳过，不影响 CI / 常规测试。

前置：需配置真实 IMAGE_GENERATION_ENDPOINT + IMAGE_GENERATION_API_KEY
（见 core.runtime.config / .env）。未配置时 provider 会抛 NOT_CONFIGURED，
该用例按「环境未就绪」跳过，不算失败。

运行：
    RUN_REAL_IMAGE_SMOKE=1 python -m pytest core/generator/tests/test_real_image_smoke.py -q
"""

from __future__ import annotations

import os

import pytest

from core.generator import template_generation as tg
from core.integrations.image_generation import ImageGenerationError

RUN_REAL = os.environ.get("RUN_REAL_IMAGE_SMOKE") == "1"

pytestmark = pytest.mark.skipif(
    not RUN_REAL,
    reason="set RUN_REAL_IMAGE_SMOKE=1 (and configure provider env) to run real image smoke",
)

# provider/环境未就绪类错误：opt-in 但 provider 未配置 / 不可达 / 鉴权失败 / 超时 /
# 返回错误，均视为「环境未就绪」按 skip 处理，不当作本仓代码回归（避免 smoke 变 flaky）。
# 只有 provider 真的成功响应、却没有图片，才算真实失败。
_ENV_NOT_READY_CODES = {
    "IMAGE_GENERATION_NOT_CONFIGURED",
    "IMAGE_GENERATION_AUTH_FAILED",
    "IMAGE_GENERATION_TIMEOUT",
    "IMAGE_GENERATION_PROVIDER_FAILED",
}

# 三个核心可跑通模板 + 一个最小可用 prompt。
SMOKE_CASES = [
    ("avatar-viral", "avatar", {"prompt": "赛博朋克风格年轻人头像", "style": "cyberpunk"}),
    ("sticker-viral", "stickerPack", {"prompt": "打工人猫猫", "mood": "搞笑"}),
    ("pet-talk-viral", "petVideo", {"prompt": "主人，该喂饭啦！"}),
]


@pytest.mark.parametrize("template_id,preview_type,inp", SMOKE_CASES)
def test_real_provider_returns_image(template_id, preview_type, inp):
    """真实 provider：核心模板成功响应时必须返回 image_url 或 image_base64（真图可渲染）。

    provider 未就绪 / 不可达 / 超时 / 鉴权失败按 skip 处理（环境条件，非代码回归）。
    """
    try:
        out = tg.generate_template(template_id, inp)  # 不注入 generate -> 打真实 provider
    except ImageGenerationError as e:
        if e.code in _ENV_NOT_READY_CODES:
            pytest.skip(f"provider 环境未就绪，跳过真实 smoke: {e.code}")
        raise

    assert out["ok"] is True
    assert out["template_id"] == template_id
    assert out["preview_type"] == preview_type
    assert out["real_generation"] is True
    assert out["fallback_mode"] is False
    r = out["result"]
    # 真实结果必须带可渲染图片（url 或 base64 二者之一）。
    assert r.get("image_url") or r.get("image_base64"), (
        f"{template_id} 真实 provider 未返回 image_url / image_base64"
    )

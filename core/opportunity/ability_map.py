"""core.opportunity.ability_map — ability_type 封闭枚举 + 落地映射真源。

B(功能拆分)与 C(generator)共用的唯一真源，杜绝并行枚举。LLM 只能产 ABILITY_TYPES
内的 ability_type(超出 = schema 校验失败 → 走规则 fallback)。

铁律(§4.0)：任何"处理一张已上传的图/视频/音频"语义(image-edit/video-edit/...)
绝不映射到 text2img 文生图模板。项目里图生图真实能力只有 background_remove /
watermark_remove 两个具体 task，通用图生图无对应后端，故 buildable=false。

落地分两层(§4.1)：
- buildable      = 能否产出可渲染小程序(模板 ∈ classifier._KNOWN_TEMPLATES)
- auto_publishable = 后端 task 是否 ∈ feature_registry.TASK_WHITELIST(名副其实可自动上线)
  buildable=true 但 auto_publishable=false 的(avatar 等)入队但标 review_required，不自动上线。
"""

from __future__ import annotations

import copy

# ability_type -> 落地信息。buildable=true 的 selected_template 必须 ∈ _KNOWN_TEMPLATES，
# (ability, task) 必须与 classifier._TEMPLATE_ABILITY_TASK 一致(test_ability_map 强校验)。
ABILITY_MAP: dict[str, dict] = {
    # —— buildable=true：生成新内容语义，落 text2img/img2img ——
    "image-gen": {"selected_template": "ai-image", "ability": "text2img", "task": "generate_image",
                  "buildable": True, "auto_publishable": True,
                  "required_capabilities": ["image_generation"], "unsupported_reasons": []},
    "bg-remove": {"selected_template": "background-remover", "ability": "img2img", "task": "background_remove",
                  "buildable": True, "auto_publishable": True,
                  "required_capabilities": ["image_generation"], "unsupported_reasons": []},
    "watermark-remove": {"selected_template": "watermark-remover", "ability": "img2img", "task": "watermark_remove",
                         "buildable": True, "auto_publishable": True,
                         "required_capabilities": ["image_generation"], "unsupported_reasons": []},
    "avatar-gen": {"selected_template": "avatar-viral", "ability": "text2img", "task": "pending",
                   "buildable": True, "auto_publishable": False,
                   "required_capabilities": ["image_generation"], "unsupported_reasons": []},
    "sticker-gen": {"selected_template": "sticker-viral", "ability": "text2img", "task": "pending",
                    "buildable": True, "auto_publishable": False,
                    "required_capabilities": ["image_generation"], "unsupported_reasons": []},
    "pet-talk": {"selected_template": "pet-talk-viral", "ability": "text2img", "task": "pending",
                 "buildable": True, "auto_publishable": False,
                 "required_capabilities": ["image_generation"], "unsupported_reasons": []},
    "blessing": {"selected_template": "blessing-video-viral", "ability": "text2img", "task": "pending",
                 "buildable": True, "auto_publishable": False,
                 "required_capabilities": ["image_generation"], "unsupported_reasons": []},
    "funny-video": {"selected_template": "funny-video-viral", "ability": "text2img", "task": "pending",
                    "buildable": True, "auto_publishable": False,
                    "required_capabilities": ["image_generation"], "unsupported_reasons": []},
    "text-gen": {"selected_template": "ai-tool", "ability": "text2img", "task": "pending",
                 "buildable": True, "auto_publishable": False,
                 "required_capabilities": ["llm"], "unsupported_reasons": []},
    # —— buildable=false：处理已有素材/重能力，无后端落点，记录不入队 ——
    "image-edit": {"selected_template": "", "ability": "", "task": "",
                   "buildable": False, "auto_publishable": False,
                   "required_capabilities": ["image_edit"],
                   "unsupported_reasons": ["通用图生图无对应后端 task，仅 bg-remove/watermark-remove 可落地"]},
    "video-edit": {"selected_template": "", "ability": "", "task": "",
                   "buildable": False, "auto_publishable": False,
                   "required_capabilities": ["video_render"],
                   "unsupported_reasons": ["缺视频处理 provider", "长视频转码成本高"]},
    "audio-edit": {"selected_template": "", "ability": "", "task": "",
                   "buildable": False, "auto_publishable": False,
                   "required_capabilities": ["audio_process"],
                   "unsupported_reasons": ["缺音频处理 provider"]},
    "realtime-camera": {"selected_template": "", "ability": "", "task": "",
                        "buildable": False, "auto_publishable": False,
                        "required_capabilities": ["realtime_camera"],
                        "unsupported_reasons": ["实时/AR 相机依赖原生能力，小程序端难稳定支持"]},
    "3d-ar": {"selected_template": "", "ability": "", "task": "",
              "buildable": False, "auto_publishable": False,
              "required_capabilities": ["3d_render"],
              "unsupported_reasons": ["3D/AR 渲染重，第一阶段不做"]},
    "multi-step": {"selected_template": "", "ability": "", "task": "",
                   "buildable": False, "auto_publishable": False,
                   "required_capabilities": ["workflow"],
                   "unsupported_reasons": ["多步复杂工作流暂不可单步落地"]},
}

# 封闭枚举：LLM 只能从中选 ability_type。
ABILITY_TYPES = frozenset(ABILITY_MAP.keys())

# 可自动上线的模板集合：从真源派生，供规则 fallback 路径复用，避免"哪些可自动上线"
# 知识在多处硬编码漂移。
AUTO_PUBLISHABLE_TEMPLATES = frozenset(
    v["selected_template"] for v in ABILITY_MAP.values()
    if v["auto_publishable"] and v["selected_template"]
)


def resolve(ability_type: str) -> dict:
    """返回 ability_type 的落地信息深拷贝。越界抛 KeyError(供上游触发 fallback)。"""
    return copy.deepcopy(ABILITY_MAP[ability_type])

from core.opportunity.classifier import template_to_ability_task


def test_known_templates_map_to_ability_task():
    assert template_to_ability_task("ai-image") == ("text2img", "generate_image")
    assert template_to_ability_task("background-remover") == ("img2img", "background_remove")


def test_unknown_template_maps_to_pending():
    # 不在 v1 白名单的模板 → text2img + pending（不自动上线）
    assert template_to_ability_task("avatar-viral") == ("text2img", "pending")
    assert template_to_ability_task("nonexistent") == ("text2img", "pending")

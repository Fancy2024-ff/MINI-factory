"""core.qa 三层质检回归：growth_qa（含生成代码传播链路）+ compliance_qa（含敏感词扫描）。"""

import json
from pathlib import Path

from core.qa.growth_qa import run_growth_qa
from core.qa.compliance_qa import run_compliance_qa


def _make_growth_artifacts(output_dir: Path):
    (output_dir / "growth-plan.md").write_text(
        "# 增长计划\n## 增长重心\n## 渠道\n## 裂变\n## 指标\n", encoding="utf-8"
    )
    (output_dir / "share-strategy.md").write_text(
        "# 分享\n## 分享钩子\n## 激励\n## 裂变\n## 去水印\n", encoding="utf-8"
    )
    (output_dir / "viral-score.json").write_text(
        json.dumps({"viral_score": 80}), encoding="utf-8"
    )


def _make_miniapp_with_propagation(miniapp_dir: Path):
    """构造一个含完整交互闭环结构的生成项目（service + config + form + result）。

    P0-2 起，「完整接入」必须包含传播闭环 growth_loop 三层：
    blueprint.json.growth_loop + generation.ts 消费 + result.vue 展示。
    """
    src = miniapp_dir / "src"
    (src / "services").mkdir(parents=True, exist_ok=True)
    (src / "config").mkdir(parents=True, exist_ok=True)
    (src / "pages" / "result").mkdir(parents=True, exist_ok=True)
    (src / "pages" / "form").mkdir(parents=True, exist_ok=True)

    (src / "config" / "template.ts").write_text(
        "export const SELECTED_TEMPLATE = 'avatar-viral'\n", encoding="utf-8"
    )
    # blueprint.json：含结构化 growth_loop（capability_mode=real）
    (src / "config" / "blueprint.json").write_text(
        json.dumps({
            "template_id": "avatar-viral",
            "preview_type": "avatar",
            "growth_loop": {
                "has_share_cta": True, "share_cta_label": "分享头像",
                "share_title": "我生成了头像", "share_copy": "分享解锁",
                "has_unlock": True, "unlock_type": "share_to_unlock", "unlock_hint": "分享解锁去水印",
                "has_watermark": True, "watermark_label": "MiniForge 水印",
                "remove_watermark_supported": True, "brand_exposure": True, "brand_label": "MiniForge",
                "download_supported": True, "export_supported": True, "export_label": "下载高清头像",
                "capability_mode": "real", "capability_note": "真实生成",
                "download_gate": {
                    "enabled": True, "gate_type": "rewarded_ad", "ad_unit_id": "",
                    "required_for": ["download", "remove_watermark"],
                    "gate_label": "看广告下载高清无水印头像", "reward_label": "已解锁高清下载",
                    "unavailable_hint": "开发者未配置广告位，暂不可下载高清结果",
                    "close_hint": "看完广告后才能下载/导出高清结果",
                },
            },
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    # ads.ts + analytics.ts：广告闭环配置 + 埋点（QA 商业化检查依赖）。
    (src / "config" / "ads.ts").write_text(
        "export const REWARDED_AD_UNIT_ID = ''\n"
        "export const REWARDED_AD_ENABLED: boolean = false\n",
        encoding="utf-8",
    )
    (src / "services" / "analytics.ts").write_text(
        "export function trackGrowthEvent(name: string, payload: any = {}) { return { name, ...payload } }\n"
        "export function growthContextFromResult(r: any) { return { result_id: r && r.id } }\n",
        encoding="utf-8",
    )
    (src / "services" / "generation.ts").write_text(
        "import { SELECTED_TEMPLATE } from '../config/template'\n"
        "import { GENERATION_MODE, IMAGE_GENERATION_PATH, TEMPLATE_GENERATION_PATH } from '../config/api'\n"
        "export interface GeneratedResult { id: string; template: string; "
        "shareTitle: string; shareCopy: string; unlockHint: string; watermarkEnabled: boolean; "
        "growthLoop?: any; shareCtaLabel?: string; removeWatermarkSupported?: boolean; "
        "capabilityMode?: string; exportSupported?: boolean; brandExposure?: boolean }\n"
        "async function callRealApi(): Promise<GeneratedResult | null> {\n"
        "  if (GENERATION_MODE !== 'api') return null\n"
        "  void IMAGE_GENERATION_PATH; void TEMPLATE_GENERATION_PATH; return null\n}\n"
        "export function isRewardedAdRequired(r: any) { return !!(r && r.downloadGate && !r.adUnlocked) }\n"
        "export function markAdUnlocked(id: string) { return null }\n"
        "export function classifyExportTarget(r: any) { return { kind: 'remote_image' } }\n"
        "export async function requestRewardedAdUnlock(id: string) { return { ok: false } }\n"
        "export async function mockGenerate(input: any): Promise<GeneratedResult> {\n"
        "  const real = await callRealApi(); if (real) return real\n"
        "  switch (SELECTED_TEMPLATE) { default: return { id: 'x', template: SELECTED_TEMPLATE, "
        "shareTitle: 's', shareCopy: 'c', unlockHint: 'u', watermarkEnabled: true, "
        "growthLoop: {}, shareCtaLabel: 'l', removeWatermarkSupported: true, "
        "capabilityMode: 'real', exportSupported: true, brandExposure: true } }\n}\n",
        encoding="utf-8",
    )
    (src / "pages" / "form" / "form.vue").write_text(
        "<template><button @click=\"go\">生成</button></template>"
        "<script setup lang=\"ts\">import { mockGenerate } from '../../services/generation'\n"
        "async function go(){ await mockGenerate({}) }</script>",
        encoding="utf-8",
    )
    (src / "pages" / "result" / "result.vue").write_text(
        "<template><view>传播闭环 Growth Loop</view>"
        "<button open-type=\"share\">{{ result.shareCtaLabel }}</button>"
        "<view>解锁机制 {{ result.unlockHint }}</view>"
        "<button @click=\"u\">分享解锁高清/去水印</button>"
        "<text>watermark 水印 邀请好友 品牌露出 导出 当前能力</text>"
        "<text>{{ result.removeWatermarkSupported }} {{ result.brandExposure }} "
        "{{ result.exportSupported }} {{ result.capabilityMode }}</text></template>"
        "<script setup lang=\"ts\">import { requestRewardedAdUnlock, isRewardedAdRequired, classifyExportTarget } from '../../services/generation'\n"
        "import { trackGrowthEvent } from '../../services/analytics'\n"
        "async function u(){ if (isRewardedAdRequired(null)) await requestRewardedAdUnlock('x'); trackGrowthEvent('download_click'); uni.saveImageToPhotosAlbum({}); uni.saveVideoToPhotosAlbum({}); uni.setClipboardData({}) }</script>",
        encoding="utf-8",
    )


def test_growth_qa_passes_with_propagation_chain(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    mini = tmp_path / "mini"
    mini.mkdir()
    _make_growth_artifacts(out)
    _make_miniapp_with_propagation(mini)

    result = run_growth_qa(out, miniapp_dir=mini)
    assert result["passed"], result["issues"]
    assert result["checks"]["code_has_share_cta"] is True
    assert result["checks"]["code_has_unlock_hook"] is True
    assert result["checks"]["code_has_result_page"] is True
    # P1 新增结构检查
    assert result["checks"]["generation_service_exists"] is True
    assert result["checks"]["form_calls_generation"] is True
    assert result["checks"]["result_has_share_cta"] is True
    assert result["checks"]["result_has_unlock_hook"] is True
    assert result["checks"]["result_has_watermark"] is True
    assert result["checks"]["generation_template_aware"] is True


def test_growth_qa_fails_without_generation_service(tmp_path):
    """缺统一生成服务 / form 不调用 mockGenerate 时，GrowthQA 必须失败。"""
    out = tmp_path / "out"
    out.mkdir()
    mini = tmp_path / "mini"
    pages = mini / "src" / "pages" / "result"
    pages.mkdir(parents=True)
    # 有传播文案的结果页，但没有 generation service / form / config
    (pages / "result.vue").write_text(
        "<template><button open-type=\"share\">分享</button>"
        "<text>解锁 watermark 水印</text></template>",
        encoding="utf-8",
    )
    _make_growth_artifacts(out)

    result = run_growth_qa(out, miniapp_dir=mini)
    assert result["checks"]["generation_service_exists"] is False
    assert result["checks"]["form_calls_generation"] is False
    assert not result["passed"]
    assert any("generation" in i for i in result["issues"])


def test_growth_qa_fails_when_result_lacks_unlock_and_watermark(tmp_path):
    """有 service/form，但结果页缺解锁/水印钩子时，GrowthQA 必须失败。"""
    out = tmp_path / "out"
    out.mkdir()
    mini = tmp_path / "mini"
    _make_miniapp_with_propagation(mini)
    # 退化结果页：只剩分享，去掉解锁/水印
    (mini / "src" / "pages" / "result" / "result.vue").write_text(
        "<template><button open-type=\"share\">分享作品</button></template>"
        "<script setup lang=\"ts\"></script>",
        encoding="utf-8",
    )
    _make_growth_artifacts(out)

    result = run_growth_qa(out, miniapp_dir=mini)
    assert result["checks"]["result_has_share_cta"] is True
    assert result["checks"]["result_has_unlock_hook"] is False
    assert result["checks"]["result_has_watermark"] is False
    assert not result["passed"]


def test_growth_qa_flags_missing_propagation(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    mini = tmp_path / "mini"
    (mini / "src" / "pages" / "index").mkdir(parents=True)
    (mini / "src" / "pages" / "index" / "index.vue").write_text(
        "<template><text>纯工具，无传播位</text></template>", encoding="utf-8"
    )
    _make_growth_artifacts(out)

    result = run_growth_qa(out, miniapp_dir=mini)
    assert result["checks"]["code_has_share_cta"] is False
    assert not result["passed"]


def test_compliance_qa_detects_marketing_and_sensitive_words(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    mini = tmp_path / "mini"
    docs = mini / "docs"
    docs.mkdir(parents=True)
    (docs / "privacy-policy.md").write_text(
        "信息收集\n信息使用\n信息存储\n", encoding="utf-8"
    )
    (docs / "user-agreement.md").write_text("用户协议", encoding="utf-8")
    pkg = out / "publish-package"
    pkg.mkdir()
    (pkg / "review-notes.md").write_text("审核备注", encoding="utf-8")
    # 上架文案含过度营销词 + 敏感词
    (out / "listing-materials.json").write_text(
        json.dumps({"slogan": "全网最好用，100% 永久免费", "desc": "支持贷款理财"},
                   ensure_ascii=False),
        encoding="utf-8",
    )

    result = run_compliance_qa(mini, out)
    # 硬性合规闸通过（材料齐全），但敏感词为 warning
    assert result["passed"], result["issues"]
    assert result["checks"]["no_overmarketing_words"] is False
    assert result["checks"]["no_sensitive_words"] is False
    assert any("营销" in w for w in result["warnings"])
    assert any("敏感" in w for w in result["warnings"])


def test_compliance_qa_clean_listing_has_no_warnings(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    mini = tmp_path / "mini"
    docs = mini / "docs"
    docs.mkdir(parents=True)
    (docs / "privacy-policy.md").write_text(
        "信息收集\n信息使用\n信息存储\n", encoding="utf-8"
    )
    (docs / "user-agreement.md").write_text("用户协议", encoding="utf-8")
    pkg = out / "publish-package"
    pkg.mkdir()
    (pkg / "review-notes.md").write_text("审核备注", encoding="utf-8")
    (out / "listing-materials.json").write_text(
        json.dumps({"slogan": "帮你快速生成头像", "desc": "AI 头像生成工具"},
                   ensure_ascii=False),
        encoding="utf-8",
    )

    result = run_compliance_qa(mini, out)
    assert result["passed"]
    assert result["warnings"] == []


# --- 传播闭环产品化分层（P0-2）---

from core.generator.codegen import generate_miniapp

_GL_APP = {
    "name": "AI Avatar", "name_cn": "AI头像",
    "description_cn": "测试", "features_cn": ["多风格"],
}
_GL_PRD = {"target_platforms": ["wechat"]}


def _gen_miniapp(tmp_path, template):
    gd = tmp_path / ("gen_" + template)
    gd.mkdir()
    miniapp_dir, _ = generate_miniapp(_GL_APP, _GL_PRD, gd, template=template)
    return miniapp_dir


def test_growth_qa_growth_loop_fully_wired_passes(tmp_path):
    """真接入：blueprint + generation.ts + result.vue 三层都消费 growth_loop -> 通过。"""
    out = tmp_path / "out"
    out.mkdir()
    _make_growth_artifacts(out)
    mini = _gen_miniapp(tmp_path, "avatar-viral")

    result = run_growth_qa(out, miniapp_dir=mini)
    c = result["checks"]
    assert c["growth_loop_in_blueprint"] is True
    assert c["generation_consumes_growth_loop"] is True
    assert c["result_displays_growth_loop"] is True
    assert c["result_displays_share_cta"] is True
    assert c["result_displays_unlock"] is True
    assert c["result_displays_watermark"] is True
    assert c["result_displays_remove_watermark"] is True
    assert c["result_displays_brand"] is True
    assert c["result_displays_export"] is True
    assert c["capability_mode_visible"] is True
    assert c["core_template_not_downgraded"] is True
    assert result["passed"], result["issues"]


def test_growth_qa_doc_only_not_productized(tmp_path):
    """只有文档：result.vue 不消费 growth_loop、无 blueprint -> 标记未产品化、不通过。"""
    out = tmp_path / "out"
    out.mkdir()
    _make_growth_artifacts(out)
    # 退化迷你项目：有传播文案但无 growth_loop 结构（旧版「只有文档」形态）
    mini = tmp_path / "mini"
    pages = mini / "src" / "pages" / "result"
    pages.mkdir(parents=True)
    (pages / "result.vue").write_text(
        "<template><button open-type=\"share\">分享</button>"
        "<text>解锁 watermark 水印</text></template>",
        encoding="utf-8",
    )

    result = run_growth_qa(out, miniapp_dir=mini)
    c = result["checks"]
    assert c["growth_loop_in_blueprint"] is False
    assert c["result_displays_growth_loop"] is False
    assert not result["passed"]
    assert any("未产品化" in i or "传播闭环" in i for i in result["issues"])


def test_growth_qa_video_template_must_show_fallback_preview(tmp_path):
    """funny/blessing：结果页有 fallback/preview 标注 -> 该项通过（不伪装真实视频）。"""
    out = tmp_path / "out"
    out.mkdir()
    _make_growth_artifacts(out)
    mini = _gen_miniapp(tmp_path, "funny-video-viral")

    result = run_growth_qa(out, miniapp_dir=mini)
    c = result["checks"]
    assert c["fallback_preview_visible_for_video_templates"] is True
    assert c["video_template_not_faked_real"] is True


def test_growth_qa_video_template_faked_real_fails(tmp_path):
    """funny/blessing 的 growth_loop 被标成 real -> 视为伪装真实视频，不通过。"""
    out = tmp_path / "out"
    out.mkdir()
    _make_growth_artifacts(out)
    mini = _gen_miniapp(tmp_path, "blessing-video-viral")
    # 篡改 blueprint.json：把 capability_mode 改成 real（伪装真实视频）
    bp_path = mini / "src" / "config" / "blueprint.json"
    bp = json.loads(bp_path.read_text(encoding="utf-8"))
    bp["growth_loop"]["capability_mode"] = "real"
    bp_path.write_text(json.dumps(bp, ensure_ascii=False), encoding="utf-8")

    result = run_growth_qa(out, miniapp_dir=mini)
    assert result["checks"]["video_template_not_faked_real"] is False
    assert not result["passed"]
    assert any("伪装真实视频" in i for i in result["issues"])


def test_growth_qa_core_template_downgraded_fails(tmp_path):
    """核心模板（avatar）被标成 fallback_preview -> 能力口径错误，不通过。"""
    out = tmp_path / "out"
    out.mkdir()
    _make_growth_artifacts(out)
    mini = _gen_miniapp(tmp_path, "avatar-viral")
    bp_path = mini / "src" / "config" / "blueprint.json"
    bp = json.loads(bp_path.read_text(encoding="utf-8"))
    bp["growth_loop"]["capability_mode"] = "fallback_preview"
    bp_path.write_text(json.dumps(bp, ensure_ascii=False), encoding="utf-8")

    result = run_growth_qa(out, miniapp_dir=mini)
    assert result["checks"]["core_template_not_downgraded"] is False
    assert not result["passed"]


# --- P0-2 激励广告下载闭环 Growth QA 检查 ---

def _gen_miniapp_with_source(tmp_path, template):
    """生成 miniapp 并把 generator-source.json 落到 out（供 effective summary 检查）。"""
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    _make_growth_artifacts(out)
    gd = tmp_path / ("genx_" + template)
    gd.mkdir(parents=True, exist_ok=True)
    miniapp_dir, gen_source = generate_miniapp(_GL_APP, _GL_PRD, gd, template=template)
    (out / "generator-source.json").write_text(
        json.dumps(gen_source, ensure_ascii=False), encoding="utf-8"
    )
    return out, miniapp_dir


def test_growth_qa_rewarded_ad_loop_checks_pass(tmp_path):
    """avatar 真接入：广告闭环全部 checks 通过。"""
    out, mini = _gen_miniapp_with_source(tmp_path, "avatar-viral")
    result = run_growth_qa(out, miniapp_dir=mini)
    c = result["checks"]
    assert c["rewarded_ad_gate_in_blueprint"] is True
    assert c["rewarded_ad_config_present"] is True
    assert c["result_uses_rewarded_ad_unlock"] is True
    assert c["result_blocks_download_before_ad"] is True
    assert c["result_tracks_growth_events"] is True
    assert c["export_supports_remote_image"] is True
    assert c["export_supports_remote_video"] is True
    assert c["export_supports_text_preview"] is True
    assert c["no_video_claim_for_preview_templates"] is True
    # mock 构建：effective 必须 fallback_preview。
    assert c["mock_runtime_effective_preview_visible"] is True
    assert result["passed"], result["issues"]


def test_growth_qa_video_template_gate_no_video_claim(tmp_path):
    """funny/blessing：gate 文案不提视频下载，no_video_claim_for_preview_templates=True。"""
    for tpl in ("funny-video-viral", "blessing-video-viral"):
        out, mini = _gen_miniapp_with_source(tmp_path / tpl, tpl)
        result = run_growth_qa(out, miniapp_dir=mini)
        assert result["checks"]["no_video_claim_for_preview_templates"] is True


def test_growth_qa_video_gate_with_download_fails(tmp_path):
    """篡改 funny gate.required_for 含 download -> no_video_claim 失败、不通过。"""
    out, mini = _gen_miniapp_with_source(tmp_path, "funny-video-viral")
    bp_path = mini / "src" / "config" / "blueprint.json"
    bp = json.loads(bp_path.read_text(encoding="utf-8"))
    bp["growth_loop"]["download_gate"]["required_for"] = ["download", "export"]
    bp_path.write_text(json.dumps(bp, ensure_ascii=False), encoding="utf-8")

    result = run_growth_qa(out, miniapp_dir=mini)
    assert result["checks"]["no_video_claim_for_preview_templates"] is False
    assert not result["passed"]


def test_growth_qa_fails_when_result_skips_ad_gate(tmp_path):
    """result.vue 退化为直接下载（无 requestRewardedAdUnlock）-> 广告门槛 check 失败。"""
    out, mini = _gen_miniapp_with_source(tmp_path, "avatar-viral")
    rv = mini / "src" / "pages" / "result" / "result.vue"
    # 退化：移除广告解锁调用，直接保存。
    txt = rv.read_text(encoding="utf-8").replace("requestRewardedAdUnlock", "directDownloadNoAd")
    rv.write_text(txt, encoding="utf-8")

    result = run_growth_qa(out, miniapp_dir=mini)
    assert result["checks"]["result_uses_rewarded_ad_unlock"] is False
    assert not result["passed"]

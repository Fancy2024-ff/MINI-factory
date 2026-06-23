"""core.generator.prd_builder — PRD 生成（产品需求文档）。

落点理由：PRD 定义页面/功能/技术栈，是直接驱动代码生成的"规格"，
因此归在 generator（生成域），而非 growth（生成后的运营策略）。
runner 通过 build_prd 调用本模块。

支持两类输入（见 core.generator.feature_input）：
  - AppCandidate：把整个 App 小程序化。
  - FeatureOpportunity：从大 App 拆出一个功能做小程序——PRD 主体是「被拆出的功能」，
    父 App 仅作来源，并显式写明非目标功能 / 技术边界，避免承诺做成完整父 App。
"""

from __future__ import annotations


def build_prd(app: dict, opportunity: dict) -> tuple[str, dict]:
    """生成产品需求文档（Markdown + JSON）。feature 输入走 feature 导向 PRD。"""
    if app.get("input_type") == "feature_opportunity":
        return _build_feature_prd(app, opportunity)
    return _build_app_prd(app, opportunity)


def _build_app_prd(app: dict, opportunity: dict) -> tuple[str, dict]:
    """生成产品需求文档（Markdown + JSON）。"""
    features_md = "\n".join([f"- {f}" for f in app["features_cn"]])
    platforms_str = "、".join(opportunity["target_platforms"])

    prd_md = f"""# {app['name_cn']} 小程序 - 产品需求文档

## 产品概述

**产品名称**：{app['name_cn']}
**英文名**：{app['name']}
**产品形态**：小程序
**目标平台**：{platforms_str}
**机会评分**：{opportunity['opportunity_score']}/100

## 产品定位

将 {app['name']} 的核心功能以小程序形态提供给用户，实现即用即走、无需下载安装的轻量体验。

## 目标用户

{app['description_cn']}的目标人群，偏好在微信/支付宝/抖音生态内完成操作，不愿额外下载 App。

## 核心功能

{features_md}

## MVP 范围

首版聚焦以下功能：
1. {app['features_cn'][0]}（核心功能）
2. {app['features_cn'][1] if len(app['features_cn']) > 1 else '基础展示'}（辅助功能）
3. 用户输入表单
4. 结果展示页面
5. 历史记录（本地存储）

## 页面结构

- **首页** index：功能入口、快捷操作
- **表单页** form：用户输入核心信息
- **结果页** result：AI 处理结果展示、复制/分享
- **我的** profile：历史记录、设置

## 技术方案

- 框架：uni-app（跨端兼容微信/支付宝/抖音）
- 语言：Vue 3 + TypeScript
- 状态管理：Pinia
- API：RESTful，后端独立部署
- 存储：本地 Storage + 云端同步（Pro）

## 变现策略

- 免费版：每日 {3} 次使用额度
- Pro 版：¥{12}/月，无限使用
- 支付方式：微信支付 / 支付宝

## 开发周期

预计 {opportunity['estimated_dev_days']} 天完成 MVP。

## 风险评估

- 平台审核：需确保内容合规，不涉及敏感词
- 包大小：控制在 2MB 以内（微信主包限制）
- AI 依赖：后端 API 需保证 P95 < 2s 响应
"""

    prd_json = {
        "app_name": app["name"],
        "app_name_cn": app["name_cn"],
        "product_type": "miniapp",
        "target_platforms": opportunity["target_platforms"],
        "opportunity_score": opportunity["opportunity_score"],
        "core_features": app["features_cn"],
        "mvp_features": app["features_cn"][:2] + ["用户输入表单", "结果展示", "历史记录"],
        "pages": [
            {"path": "pages/index/index", "title": "首页", "type": "navigation"},
            {"path": "pages/form/form", "title": "表单", "type": "input"},
            {"path": "pages/result/result", "title": "结果", "type": "display"},
            {"path": "pages/profile/profile", "title": "我的", "type": "navigation"},
        ],
        "tech_stack": {
            "framework": "uni-app",
            "language": "Vue 3 + TypeScript",
            "state": "Pinia",
            "api": "RESTful",
        },
        "monetization": {"model": "freemium", "free_quota": 3, "pro_price": 12},
        "timeline_days": opportunity["estimated_dev_days"],
    }

    return prd_md, prd_json


# ── FeatureOpportunity 导向 PRD ──────────────────────────────────────────

# 模板 -> 该题材典型「非目标功能」，明确不做什么，避免承诺做成完整父 App。
_NON_GOALS_BY_TEMPLATE = {
    "ai-image": ["完整视频剪辑", "长视频时间轴", "专业字幕/特效", "批量工业级修图"],
    "avatar-viral": ["真人换脸", "证件照法律效力", "视频头像"],
    "sticker-viral": ["手绘定制表情上架微信商店", "侵权 IP 表情"],
    "pet-talk-viral": ["真实口型对齐视频生成", "长视频配音", "实时直播配音"],
    "funny-video-viral": ["复杂多轨视频剪辑", "真实成片渲染导出", "专业调色"],
    "blessing-video-viral": ["真实视频合成", "明星肖像/版权音乐", "长视频贺卡"],
    "ai-tool": ["专业排版/长文档处理", "多人协作"],
    "ai-chat": ["医疗/法律/金融专业建议", "长期记忆训练"],
}
_DEFAULT_NON_GOALS = ["超出该功能范围的复杂能力", "需要专业桌面端的重度工作流"]


def _build_feature_prd(app: dict, opportunity: dict) -> tuple[str, dict]:
    """从大 App 拆出的功能 → 小程序 PRD。主体是功能本身，不是父 App。"""
    feature_cn = app.get("feature_name_cn") or app.get("name_cn") or "AI 工具"
    feature_en = app.get("feature_name") or app.get("name") or feature_cn
    parent = app.get("parent_app_name") or "原 App"
    template = app.get("selected_template") or "ai-tool"
    platforms_str = "、".join(opportunity["target_platforms"])
    reasons = app.get("reason") or []
    reasons_md = "\n".join(f"- {r}" for r in reasons) if reasons else "- 功能轻量，适合即用即走"
    non_goals = _NON_GOALS_BY_TEMPLATE.get(template, _DEFAULT_NON_GOALS)
    non_goals_md = "\n".join(f"- 不做{g}" for g in non_goals)
    mvp = [f"使用「{feature_cn}」核心能力", "结果展示", "保存 / 分享", "历史记录（本地）"]
    mvp_md = "\n".join(f"{i+1}. {m}" for i, m in enumerate(mvp))

    prd_md = f"""# {feature_cn} 小程序 - 产品需求文档

## 产品概述
**产品名称**：{feature_cn}（独立小程序，非「{parent}」整体）
**功能英文名**：{feature_en}
**父 App 来源**：{parent}
**被拆出的功能**：{feature_cn}
**产品形态**：小程序 ｜ **目标平台**：{platforms_str}
**机会评分**：{opportunity['opportunity_score']}/100 ｜ **模板**：{template}

## 为什么适合小程序化
{reasons_md}

> 把「{parent}」中的「{feature_cn}」单独拆出，做成即点即用、无需下载的小程序，
> 聚焦单一高频场景，降低使用门槛。

## 核心用户
有「{feature_cn}」一次性 / 轻量需求、不愿为此下载完整「{parent}」的用户，
偏好在微信 / 抖音生态内即用即走。

## 核心页面
- **首页** index：功能说明 + 直接开始
- **表单页** form：采集该功能所需输入
- **结果页** result：展示生成结果 + 保存 / 分享 CTA
- **我的** profile：历史记录、设置

## MVP 功能（首版聚焦单一功能）
{mvp_md}

## 非目标功能（明确不做，避免做成完整父 App）
{non_goals_md}

## 技术边界
- 仅实现「{feature_cn}」单一功能链路，不复刻「{parent}」完整能力
- 生成能力依赖后端 API；未接入真实后端前以模板 / mock 预览呈现，不虚假承诺
- 包大小控制在 2MB 内（微信主包限制）

## 上架风险
- 不得在文案 / 名称中冒用「{parent}」品牌或暗示官方出品
- 涉及上传图片 / 人脸 / 视频的功能需提示授权、不留存、给出边界说明
- 内容需过滤违法违规与敏感词

## 增长点
- 单一功能结果可晒、可分享，天然传播
- 分享解锁高清 / 去水印 / 更多风格（见 share-strategy.md）
"""

    prd_json = {
        "app_name": feature_en,
        "app_name_cn": feature_cn,
        "product_type": "miniapp",
        "input_type": "feature_opportunity",
        "feature_key": app.get("feature_key", ""),
        "parent_app_name": parent,
        "feature_name_cn": feature_cn,
        "selected_template": template,
        "target_platforms": opportunity["target_platforms"],
        "opportunity_score": opportunity["opportunity_score"],
        "core_features": list(app.get("features_cn") or [feature_cn]),
        "mvp_features": mvp,
        "non_goals": non_goals,
        "pages": [
            {"path": "pages/index/index", "title": "首页", "type": "navigation"},
            {"path": "pages/form/form", "title": "表单", "type": "input"},
            {"path": "pages/result/result", "title": "结果", "type": "display"},
            {"path": "pages/profile/profile", "title": "我的", "type": "navigation"},
        ],
        "tech_stack": {
            "framework": "uni-app",
            "language": "Vue 3 + TypeScript",
            "state": "Pinia",
            "api": "RESTful",
        },
        "monetization": {"model": "freemium", "free_quota": 3, "pro_price": 12},
        "timeline_days": opportunity["estimated_dev_days"],
    }
    return prd_md, prd_json

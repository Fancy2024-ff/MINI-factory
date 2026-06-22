"""core.runtime.artifact_manifest — 产物清单（供 UI 展示每个产物的用途/状态/下一步）。

runner 调用 build_artifact_manifest；job_id 显式入参。
登记的产物位含：viral-score / template-selection / growth-plan / share-strategy 等。
"""

from __future__ import annotations

from pathlib import Path


def build_artifact_manifest(output_dir: Path, qa: dict, readiness: dict, job_id: str = "") -> dict:
    """Describe each artifact with purpose, status and next action for the UI."""
    qa_passed = bool(qa.get("passed"))
    dist_exists = bool(qa.get("checks", {}).get("dist_exists"))
    ready = bool(readiness.get("ready_to_submit"))

    miniapp_status = "ready" if (qa_passed and dist_exists) else "blocked"
    pkg_status = "ready" if ready else "blocked"

    items = [
        {"path": "candidate.json", "title": "候选 App", "purpose": "选中的候选应用信息",
         "status": "ready", "affects_submission": False, "next_action": "无"},
        {"path": "analysis.json", "title": "需求分析", "purpose": "需求强度评分",
         "status": "ready", "affects_submission": False, "next_action": "无"},
        {"path": "gap-check.json", "title": "覆盖检查", "purpose": "小程序平台覆盖缺口",
         "status": "ready", "affects_submission": False, "next_action": "无"},
        {"path": "opportunity-report.json", "title": "机会评分", "purpose": "综合机会评分",
         "status": "ready", "affects_submission": False, "next_action": "无"},
        {"path": "viral-score.json", "title": "传播力评分", "purpose": "Viral Score 传播力评估",
         "status": "ready", "affects_submission": False, "next_action": "无"},
        {"path": "template-selection.json", "title": "模板选择", "purpose": "题材归类与选中的模板类型",
         "status": "ready", "affects_submission": False, "next_action": "无"},
        {"path": "prd.md", "title": "PRD（可读）", "purpose": "产品需求文档",
         "status": "needs_review", "affects_submission": True, "next_action": "人工确认产品方案"},
        {"path": "prd.json", "title": "PRD（结构化）", "purpose": "结构化 PRD",
         "status": "ready", "affects_submission": False, "next_action": "无"},
        {"path": "generated/miniapp", "title": "小程序项目", "purpose": "生成的 uni-app 项目",
         "status": miniapp_status, "affects_submission": True,
         "next_action": "无" if miniapp_status == "ready" else "修复 QA/构建问题"},
        {"path": "growth-plan.md", "title": "增长计划", "purpose": "冷启动/渠道/裂变回环/指标",
         "status": "needs_review", "affects_submission": False, "next_action": "人工 review 增长打法"},
        {"path": "share-strategy.md", "title": "分享策略", "purpose": "分享钩子/激励/去水印/裂变路径",
         "status": "needs_review", "affects_submission": False, "next_action": "人工 review 分享设计"},
        {"path": "growth-qa-report.json", "title": "增长 QA", "purpose": "增长计划与分享策略完整性检查",
         "status": "ready", "affects_submission": False, "next_action": "查看 issues"},
        {"path": "compliance-qa-report.json", "title": "合规 QA", "purpose": "隐私、协议、审核备注完整性检查",
         "status": "ready", "affects_submission": True, "next_action": "查看 issues"},
        {"path": "generator-qa-report.json", "title": "生成器 QA", "purpose": "模板配置/蓝图/生成产物质量检查",
         "status": "ready", "affects_submission": False, "next_action": "查看 issues"},
        {"path": "qa-report.json", "title": "QA 报告", "purpose": "质量检查 + 构建验证",
         "status": "ready" if qa_passed else "needs_review", "affects_submission": True,
         "next_action": "无" if qa_passed else "查看 issues 并修复"},
        {"path": "listing-materials.md", "title": "上架材料（可读）", "purpose": "上架文案",
         "status": "needs_review", "affects_submission": True, "next_action": "人工 review 文案"},
        {"path": "listing-materials.json", "title": "上架材料（结构化）", "purpose": "结构化上架材料",
         "status": "ready", "affects_submission": False, "next_action": "无"},
        {"path": "human-actions.md", "title": "人工操作指南", "purpose": "上架步骤说明",
         "status": "ready", "affects_submission": False, "next_action": "按指南操作"},
        {"path": "submission-readiness-report.json", "title": "提交就绪报告",
         "purpose": "是否可提交审核的真实判断",
         "status": "ready", "affects_submission": True, "next_action": "查看 blocking_issues"},
        {"path": "publish-package", "title": "提交审核包", "purpose": "各平台提交材料",
         "status": pkg_status, "affects_submission": True,
         "next_action": "无" if ready else "解决提交阻塞项后再使用"},
    ]
    return {"job_id": job_id, "items": items}

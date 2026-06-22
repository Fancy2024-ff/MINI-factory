"""core.runtime.artifacts — 统一产物写盘 + 产物位登记。

职责：所有 job 产物的写入入口与文件名常量（单一事实源）。
新产品方向新增的产物位（viral-score / template-selection / growth-plan /
share-strategy）在此登记，pipeline 依此调度，避免文件名散落。
"""

from __future__ import annotations

import json
from pathlib import Path


# --- 产物文件名（单一事实源）---
# 原有
PRD_JSON = "prd.json"
PRD_MD = "prd.md"
CANDIDATE_JSON = "candidate.json"
OPPORTUNITY_REPORT_JSON = "opportunity-report.json"
QA_REPORT_JSON = "qa-report.json"
LISTING_MATERIALS_MD = "listing-materials.md"
SUBMISSION_READINESS_JSON = "submission-readiness-report.json"

# 新产品方向新增产物位
VIRAL_SCORE_JSON = "viral-score.json"
TEMPLATE_SELECTION_JSON = "template-selection.json"
GROWTH_PLAN_MD = "growth-plan.md"
SHARE_STRATEGY_MD = "share-strategy.md"
GROWTH_QA_JSON = "growth-qa-report.json"
COMPLIANCE_QA_JSON = "compliance-qa-report.json"
GENERATOR_QA_JSON = "generator-qa-report.json"

# 所有新增产物位（供 manifest/校验引用）
NEW_ARTIFACTS = [
    VIRAL_SCORE_JSON,
    TEMPLATE_SELECTION_JSON,
    GROWTH_PLAN_MD,
    SHARE_STRATEGY_MD,
    GROWTH_QA_JSON,
    COMPLIANCE_QA_JSON,
    GENERATOR_QA_JSON,
]


def write_text(path: Path, content: str) -> None:
    """写文本产物。.md 用 utf-8-sig（Windows 友好），其余 utf-8。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    encoding = "utf-8-sig" if path.suffix == ".md" else "utf-8"
    with open(path, "w", encoding=encoding) as f:
        f.write(content)


def write_json(path: Path, data: dict) -> None:
    """写 JSON 产物（中文不转义、缩进 2）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2))

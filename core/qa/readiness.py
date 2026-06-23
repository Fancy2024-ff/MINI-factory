"""core.qa.readiness — 提交就绪决策（能否今天提交审核）。

单一事实源：就绪/阻塞判定只在这里。runner 调用 build_submission_readiness，
聚合各 QA 报告 + 平台鉴权状态，job_id 显式入参。
"""

from __future__ import annotations

import json
from pathlib import Path

from core.runtime.config import DATA_DIR


def platform_auth_status(plat: str) -> tuple[bool, list[str]]:
    """Return (configured, missing_fields) by reading data/platform-auth/<plat>.json."""
    required = {
        "wechat": ["appid", "private_key_path"],
        "alipay": ["appid"],
        "douyin": ["appid"],
        "telegram": ["bot_token"],
    }.get(plat, ["appid"])
    cf = DATA_DIR / "platform-auth" / f"{plat}.json"
    if not cf.exists():
        return False, required[:]
    try:
        cfg = json.loads(cf.read_text(encoding="utf-8-sig"))
    except Exception:
        return False, required[:]
    missing = [f for f in required if not cfg.get(f)]
    return (len(missing) == 0), missing


def build_submission_readiness(best_app: dict, opportunity: dict, qa: dict,
                               output_dir: Path, mode: str, job_id: str = "",
                               growth_qa: dict | None = None,
                               compliance_qa: dict | None = None,
                               generator_qa: dict | None = None) -> dict:
    """Honest answer to: can we submit for review TODAY?

    ready_to_submit is True only when there are zero blocking issues — which
    means: QA/build passed, dist exists, platform auth (AppID) configured,
    screenshots prepared, and real-device testing done.

    除 EngineeringQA(qa) 外，也纳入 GrowthQA / ComplianceQA / GeneratorQA：
    工程/合规/生成不达标为 blocking；增长策略不达标为 warning（不阻塞上架本身）。
    """
    qa_passed = bool(qa.get("passed"))
    dist_exists = bool(qa.get("checks", {}).get("dist_exists"))

    registry_file = DATA_DIR / "platforms" / "platform-registry.json"
    registry = {}
    if registry_file.exists():
        try:
            registry = {p["id"]: p for p in json.loads(registry_file.read_text(encoding="utf-8-sig"))}
        except Exception:
            registry = {}

    platform_readiness = []
    rejected_platforms = []
    any_configured = False

    for plat in opportunity["target_platforms"]:
        reg = registry.get(plat, {})
        status = reg.get("status", "unknown")
        if status in ("not_supported", "research_needed"):
            rejected_platforms.append({
                "platform": plat,
                "reason": reg.get("notes", "平台不支持") if status == "not_supported" else "待调研，暂不可提交",
            })
            continue

        configured, missing_fields = platform_auth_status(plat)
        can_upload = configured and reg.get("automation_level", "manual") != "manual"
        any_configured = any_configured or configured

        plat_blocking = []
        if not configured:
            plat_blocking.append(f"未配置 {plat} 平台授权（缺: {', '.join(missing_fields) or 'AppID'}）")
        if not qa_passed:
            plat_blocking.append("QA/构建未通过")
        if not dist_exists:
            plat_blocking.append("构建产物缺失")

        platform_readiness.append({
            "platform": plat,
            "name_cn": reg.get("name_cn", plat),
            "name_en": reg.get("name_en", plat),
            "ready": status == "active" and configured and qa_passed and dist_exists,
            "configured": configured,
            "can_upload": can_upload,
            "missing_fields": missing_fields,
            "next_action": (
                "上传代码并提交审核" if (configured and qa_passed and dist_exists)
                else f"先解决: {'; '.join(plat_blocking)}"
            ),
            "submit_url": reg.get("submit_url", reg.get("developer_url", "")),
            "upload_path": str(output_dir / "generated" / "miniapp" / (reg.get("upload_target", "") or "dist/build/mp-weixin")),
            "automation_level": reg.get("automation_level", "manual"),
        })

    # Global blocking / warning issues
    blocking_issues = []
    if not qa_passed:
        blocking_issues.append("QA 未通过或构建失败，不能提交审核")
    if not dist_exists:
        blocking_issues.append("构建产物 dist/build/mp-weixin 缺失")
    if not any_configured:
        blocking_issues.append("尚未配置任何平台授权（缺 AppID/密钥）")
    # 合规 / 生成质量未通过 = 阻塞（虚假承诺、缺法务文档、模板结构缺陷不应上架）
    if compliance_qa is not None and not compliance_qa.get("passed", True):
        blocking_issues.append("合规 QA 未通过（隐私/协议/能力边界等），不能提交审核")
    if generator_qa is not None and not generator_qa.get("passed", True):
        blocking_issues.append("生成器 QA 未通过（模板配置/签名页/产物契约缺陷）")
    # These are always required for a real submission and never auto-produced:
    blocking_issues.append("缺少真机测试截图，需人工准备")
    blocking_issues.append("未在目标平台真机测试")

    warning_issues = [
        "生成代码为 MVP 模板，建议人工 review 业务逻辑",
        "AI 处理结果为占位，需接入真实后端 API",
    ]
    # 增长策略不达标 = warning（影响传播效果，但不阻塞上架本身）
    if growth_qa is not None and not growth_qa.get("passed", True):
        warning_issues.append("增长 QA 未通过（分享/解锁/渠道/指标等增长要素不完整）")
    # 合规 QA 的 warnings（敏感词等）透传为 warning
    for w in (compliance_qa or {}).get("warnings", []) or []:
        warning_issues.append(w)

    human_actions = [
        "在对应平台后台创建小程序并获取 AppID",
        "将 AppID/密钥写入 data/platform-auth/<platform>.json",
        "用开发者工具导入 dist/build/mp-weixin 并真机预览",
        "准备 4-5 张截图（参考 listing-materials.md）",
        "提交审核并记录结果",
    ]

    return {
        "job_id": job_id,
        "app_name": best_app["name_cn"],
        "ready_to_submit": len(blocking_issues) == 0,
        # Back-compat alias for older dashboards; same value as ready_to_submit.
        "is_ready_to_submit": len(blocking_issues) == 0,
        "blocking_issues": blocking_issues,
        "warning_issues": warning_issues,
        "human_actions": human_actions,
        "qa_passed": qa_passed,
        "build_dist_exists": dist_exists,
        "target_platforms": [p["platform"] for p in platform_readiness],
        "rejected_platforms": rejected_platforms,
        "platform_readiness": platform_readiness,
        "next_action": (
            "可以提交审核" if len(blocking_issues) == 0
            else "当前不能提交审核，请先解决上方 blocking_issues"
        ),
        "data_source": "demo_rule_based" if mode == "demo" else "real_import_manual",
    }

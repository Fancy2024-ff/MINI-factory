"""core.qa.readiness 测试 — 综合 Engineering/Growth/Compliance/Generator QA 的就绪判断。"""

from __future__ import annotations

from pathlib import Path

from core.qa.readiness import build_submission_readiness

_APP = {"name_cn": "AI 修图", "name": "AI Retouch"}
_OPP = {"target_platforms": ["wechat"]}


def _qa(passed=True, dist=True):
    return {"passed": passed, "checks": {"dist_exists": dist}}


def test_compliance_fail_blocks_submission(tmp_path: Path):
    """合规 QA 未通过 → 进 blocking_issues。"""
    r = build_submission_readiness(
        _APP, _OPP, _qa(), tmp_path, "demo",
        compliance_qa={"passed": False, "issues": ["缺隐私政策"]},
    )
    assert any("合规 QA 未通过" in b for b in r["blocking_issues"])
    assert r["ready_to_submit"] is False


def test_generator_fail_blocks_submission(tmp_path: Path):
    """生成器 QA 未通过 → 进 blocking_issues。"""
    r = build_submission_readiness(
        _APP, _OPP, _qa(), tmp_path, "demo",
        generator_qa={"passed": False, "issues": ["签名页缺失"]},
    )
    assert any("生成器 QA 未通过" in b for b in r["blocking_issues"])


def test_growth_fail_is_warning_not_blocking(tmp_path: Path):
    """增长 QA 未通过 → 只进 warning，不阻塞上架本身。"""
    r = build_submission_readiness(
        _APP, _OPP, _qa(), tmp_path, "demo",
        growth_qa={"passed": False, "issues": ["缺分享钩子"]},
    )
    assert any("增长 QA 未通过" in w for w in r["warning_issues"])
    assert not any("增长 QA" in b for b in r["blocking_issues"])


def test_compliance_warnings_propagated(tmp_path: Path):
    """合规 QA 的 warnings（敏感词等）透传到 readiness warning。"""
    r = build_submission_readiness(
        _APP, _OPP, _qa(), tmp_path, "demo",
        compliance_qa={"passed": True, "issues": [], "warnings": ["含敏感词: 贷款"]},
    )
    assert any("敏感词" in w for w in r["warning_issues"])


def test_backward_compatible_without_extra_qa(tmp_path: Path):
    """不传额外 QA 时行为不变（向后兼容）。"""
    r = build_submission_readiness(_APP, _OPP, _qa(), tmp_path, "demo")
    # 真机截图/测试这类固有 blocking 仍在
    assert any("真机" in b for b in r["blocking_issues"])
    assert "ready_to_submit" in r and "is_ready_to_submit" in r

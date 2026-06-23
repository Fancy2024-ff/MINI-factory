"""
Capability-domain Pipeline - 从机会发现到小程序生成与增长交付。
demo 模式读取 data/samples/apps.json，real 模式读取 data/inputs/real/apps.json。

运行方式:
    python core/pipeline/runner.py

不依赖 LLM，使用本地规则和模板。
"""

import sys
import os
import json
import uuid
import time
from pathlib import Path
from datetime import datetime

# Fix Windows encoding
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
DATA_DIR = PROJECT_ROOT / "data"
SAMPLES_DIR = DATA_DIR / "samples"
REAL_INPUTS_DIR = DATA_DIR / "inputs" / "real"
OUTPUTS_DIR = DATA_DIR / "outputs"

# 业务能力域：pipeline 只编排，规则/策略/QA 在 core/* 各域（单一事实源）。
from core.opportunity.scoring import compute_opportunity_score
from core.opportunity.viral_score import compute_viral_score
from core.opportunity.classifier import classify as classify_template
from core.opportunity.demand_analysis import analyze_demand
from core.opportunity.gap_analysis import check_gap
from core.generator.prd_builder import build_prd
from core.generator.codegen import generate_miniapp
from core.publisher.materials import build_listing_materials
from core.publisher.package_builder import build_publish_package
from core.growth.planner import build_growth_plan
from core.growth.share_strategy import build_share_strategy
from core.qa.engineering_qa import run_engineering_qa
from core.qa.growth_qa import run_growth_qa
from core.qa.compliance_qa import run_compliance_qa
from core.qa.generator_qa import run_generator_qa
from core.qa.readiness import build_submission_readiness
from core.runtime.artifact_manifest import build_artifact_manifest
from core.runtime import artifacts as artifact_names


def p(msg: str):
    print(msg, flush=True)


def step_header(num: int, title: str, capability: str):
    p(f"\n{'─' * 60}")
    p(f"  Step {num} │ {title}")
    p(f"  能力 │ {capability}")
    p(f"{'─' * 60}")


def step_done(output_path: str, duration: float):
    p(f"  ✓ 完成 │ {duration:.1f}s │ {output_path}")




# Pipeline report state (written incrementally)
_pipeline_steps: list[dict] = []
_pipeline_output_dir: Path = Path(".")
_pipeline_job_id: str = ""
_report_meta: dict = {
    "started_at": None,
    "finished_at": None,
    "total_passed": None,
    "error": None,
    "mode": "demo",
    "data_source": "demo_rule_based",
}


def _flush_pipeline_report():
    """Write current pipeline-report.json to disk (report-level + per-step state)."""
    report = {
        "job_id": _pipeline_job_id,
        "mode": _report_meta["mode"],
        "data_source": _report_meta["data_source"],
        "started_at": _report_meta["started_at"],
        "finished_at": _report_meta["finished_at"],
        "total_passed": _report_meta["total_passed"],
        "error": _report_meta["error"],
        "steps": _pipeline_steps,
    }
    report_path = _pipeline_output_dir / "pipeline-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(report, ensure_ascii=False, indent=2))


def finalize_pipeline_report(total_passed=None, error: str = None):
    """Mark the report finished. Always leaves a terminal state (never 'running')."""
    _report_meta["finished_at"] = datetime.now().isoformat()
    _report_meta["total_passed"] = total_passed
    _report_meta["error"] = error
    # Any step still marked running at finalize time is forced to failed.
    for entry in _pipeline_steps:
        if entry.get("status") == "running":
            entry["status"] = "failed"
            entry["finished_at"] = entry["finished_at"] or datetime.now().isoformat()
            entry["error"] = entry.get("error") or (error or "pipeline aborted")
    _flush_pipeline_report()


def step_start(step_id: str, name: str, capability: str):
    """Record step started and flush to disk. Protocol fields are step/capability."""
    if _report_meta["started_at"] is None:
        _report_meta["started_at"] = datetime.now().isoformat()
    entry = {
        "step": step_id,
        "name": name,
        "capability": capability,
        "status": "running",
        "started_at": datetime.now().isoformat(),
        "finished_at": None,
        "duration_ms": 0,
        "artifact": None,
        "error": None,
    }
    _pipeline_steps.append(entry)
    _flush_pipeline_report()
    p(json.dumps({"event": "step_started", "job_id": _pipeline_job_id, "step": step_id, "capability": capability, "message": name, "status": "running", "started_at": entry["started_at"]}))


def step_end(artifact: str = None, error: str = None, error_code: str = None,
             user_message: str = None, developer_message: str = None):
    """Record step finished and flush to disk. Failure carries structured error info."""
    if not _pipeline_steps:
        return
    entry = _pipeline_steps[-1]
    entry["finished_at"] = datetime.now().isoformat()
    started = datetime.fromisoformat(entry["started_at"])
    entry["duration_ms"] = int((datetime.now() - started).total_seconds() * 1000)
    entry["artifact"] = artifact
    is_failed = bool(error or error_code)
    entry["status"] = "failed" if is_failed else "passed"
    if is_failed:
        entry["error"] = error or user_message or "步骤执行失败"
        entry["error_code"] = error_code or "step_error"
        entry["user_message"] = user_message or error or "该步骤执行失败"
        entry["developer_message"] = developer_message or error or ""
    else:
        entry["error"] = None
    _flush_pipeline_report()
    # Print structured event
    evt = {
        "event": "step_finished", "job_id": _pipeline_job_id, "step": entry["step"],
        "capability": entry.get("capability", ""),
        "status": entry["status"], "artifact": artifact or "",
        "finished_at": entry["finished_at"], "duration_ms": entry["duration_ms"],
        "error": entry.get("error") or "",
    }
    if is_failed:
        evt["error_code"] = entry.get("error_code", "step_error")
        evt["user_message"] = entry.get("user_message", "")
        evt["developer_message"] = entry.get("developer_message", "")
    p(json.dumps(evt))


def _normalize_app(app: dict) -> dict:
    """Fill defaultable fields so downstream steps never hit a KeyError.

    Mirrors the backend RealAppInput normalization: name_cn<-name,
    description_cn<-description, features_cn<-features, numeric defaults, and a
    guaranteed non-empty features_cn (so `features_cn[0]` is always safe).
    """
    app = dict(app or {})
    app["name"] = app.get("name", "") or "Unnamed App"
    app["name_cn"] = app.get("name_cn") or app["name"]
    app["category"] = app.get("category", "") or "Utilities"
    app["description"] = app.get("description") or app.get("description_cn") or ""
    app["description_cn"] = app.get("description_cn") or app.get("description") or ""
    features = app.get("features") or app.get("features_cn") or []
    features_cn = app.get("features_cn") or app.get("features") or []
    if not features_cn:
        features_cn = ["核心功能"]
    if not features:
        features = features_cn
    app["features"] = features
    app["features_cn"] = features_cn
    app["downloads"] = app.get("downloads", 0) or 0
    app["rating"] = app.get("rating", 0) or 0
    app["review_count"] = app.get("review_count", 0) or 0
    app["monetization"] = app.get("monetization") or "unknown"
    # 输入契约：标注来源类型 + 透传上游已选模板（与 FeatureOpportunity 统一字段）。
    app["input_type"] = app.get("input_type") or "app_candidate"
    app["selected_template"] = (app.get("selected_template") or "").strip()
    return app


def load_market_input(mode: str = "demo") -> list[dict]:
    """读取 App 数据。demo=样例, real=导入数据, live=实时抓取 App Store + Google Play。"""
    if mode == "live":
        return _fetch_live_apps()
    elif mode == "real":
        apps_file = REAL_INPUTS_DIR / "apps.json"
        if not apps_file.exists():
            raise FileNotFoundError(
                f"data/inputs/real/apps.json not found\n"
                f"请先导入真实 App 数据，参考模板: data/inputs/real/apps.example.json"
            )
    else:
        apps_file = SAMPLES_DIR / "apps.json"
        if not apps_file.exists():
            raise FileNotFoundError(f"样本数据不存在: {apps_file}")
    apps = json.loads(apps_file.read_text(encoding="utf-8-sig"))
    if not isinstance(apps, list) or not apps:
        raise ValueError(f"{apps_file} 必须是非空的 JSON 数组")
    return [_normalize_input(a) for a in apps]


def _normalize_input(raw: dict) -> dict:
    """归一化一条输入：FeatureOpportunity 走 feature 契约，否则按 AppCandidate。

    两类输入归一化后字段统一（含 input_type / selected_template），下游无需再判断形态。
    """
    from core.generator.feature_input import (
        is_feature_opportunity,
        normalize_feature_opportunity,
    )
    if is_feature_opportunity(raw):
        return normalize_feature_opportunity(raw)
    return _normalize_app(raw)


# 候选决策权重：Viral Score 是候选选择的核心因子（占 40%），不是事后标签。
CANDIDATE_DEMAND_WEIGHT = 0.60
CANDIDATE_VIRAL_WEIGHT = 0.40


def select_best_candidate(apps: list[dict]) -> tuple[dict, dict, dict, list[tuple]]:
    """对所有候选打分并选出最优。

    决策分 = demand_score * 0.60 + viral_score * 0.40，因此传播力（Viral Score）
    会真实改变最终选中的候选，而非只生成一份 viral-score.json。
    返回 (best_app, best_analysis, best_viral, scored_list)。
    """
    scored = []
    for app in apps:
        analysis = analyze_demand(app)
        viral_preview = compute_viral_score(app)
        decision_score = round(
            analysis["demand_score"] * CANDIDATE_DEMAND_WEIGHT
            + viral_preview["viral_score"] * CANDIDATE_VIRAL_WEIGHT,
            1,
        )
        analysis["viral_score"] = viral_preview["viral_score"]
        analysis["candidate_decision_score"] = decision_score
        scored.append((app, analysis, viral_preview))

    scored.sort(key=lambda x: x[1]["candidate_decision_score"], reverse=True)
    best_app, best_analysis, best_viral = scored[0]
    return best_app, best_analysis, best_viral, scored


def _fetch_live_apps() -> list[dict]:
    """实时从 App Store + Google Play 抓取 AI 类 App。"""
    from core.opportunity.scrapers.appstore import fetch_ai_apps_appstore
    from core.opportunity.scrapers.googleplay import fetch_ai_apps_googleplay

    print("  [Live] 正在从 App Store 抓取...")
    appstore_apps = fetch_ai_apps_appstore(category="ai", limit=20)
    print(f"  [Live] App Store: 获取 {len(appstore_apps)} 个 App")

    print("  [Live] 正在从 Google Play 抓取...")
    gp_apps = fetch_ai_apps_googleplay(category="ai", limit=20)
    print(f"  [Live] Google Play: 获取 {len(gp_apps)} 个 App")

    # Merge and dedup
    seen = set()
    all_apps = []
    for app in appstore_apps + gp_apps:
        name_lower = app.name.lower()
        if name_lower in seen:
            continue
        seen.add(name_lower)
        all_apps.append({
            "name": app.name,
            "name_cn": app.name,  # Will be translated by LLM later
            "app_id": app.app_id,
            "source": app.source.value if hasattr(app.source, 'value') else str(app.source),
            "category": app.category,
            "description": app.description[:300],
            "description_cn": app.description[:300],
            "downloads": app.downloads,
            "rating": app.rating,
            "review_count": 0,
            "features": app.features if hasattr(app, 'features') else [],
            "monetization": "freemium",
        })

    # Sort by downloads, take top 10
    all_apps.sort(key=lambda a: a.get("downloads", 0), reverse=True)
    top_apps = all_apps[:10]
    print(f"  [Live] 合并去重后 Top 10:")
    for a in top_apps:
        print(f"    {a['name']} | {a['downloads']:,} downloads | {a['rating']:.1f}⭐")

    return [_normalize_app(a) for a in top_apps]


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Use BOM only for .md files (Windows Notepad compatibility)
    # JSON/TS/Vue/HTML must NOT have BOM (breaks parsers)
    encoding = "utf-8-sig" if path.suffix == ".md" else "utf-8"
    with open(path, "w", encoding=encoding) as f:
        f.write(content)


# ═══════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["demo", "real", "live"], default="demo", help="demo: sample data, real: imported data, live: scrape App Store + Google Play")
    parser.add_argument("--job-id", default=None, help="Pre-assigned job ID (from server)")
    args = parser.parse_args()
    mode = args.mode

    p("=" * 60)
    p(f"  Mini App Factory - Pipeline ({mode} mode)")
    p(f"  从市场数据到可上架小程序")
    p("=" * 60)

    # Generate job_id early so all steps can reference it
    global _pipeline_steps, _pipeline_output_dir, _pipeline_job_id
    if args.job_id:
        job_id = args.job_id
    else:
        job_id = datetime.now().strftime("%Y%m%d") + "-" + str(uuid.uuid4())[:6]
    output_dir = OUTPUTS_DIR / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    _pipeline_steps = []
    _pipeline_output_dir = output_dir
    _pipeline_job_id = job_id
    _report_meta["mode"] = mode
    _report_meta["data_source"] = "demo_rule_based" if mode == "demo" else "real_import_manual"
    _report_meta["started_at"] = None
    _report_meta["finished_at"] = None
    _report_meta["total_passed"] = None
    _report_meta["error"] = None
    p(f"  Job ID: {job_id}")
    p(f"  输出目录: {output_dir}")

    try:
        qa = _run_pipeline_steps(mode, job_id, output_dir)
        finalize_pipeline_report(total_passed=bool(qa.get("passed")))
    except SystemExit:
        raise
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        failed_step = _pipeline_steps[-1]["step"] if _pipeline_steps else "unknown"
        user_msg = f"流水线在「{failed_step}」步骤失败: {e}"
        # Close the in-flight step as failed (finalize also forces running->failed).
        if _pipeline_steps and _pipeline_steps[-1].get("status") == "running":
            step_end(error=str(e), error_code="pipeline_exception",
                     user_message=user_msg, developer_message=tb[-1500:])
        finalize_pipeline_report(total_passed=False, error=str(e))
        # Structured failure event for the dashboard WS.
        p(json.dumps({
            "event": "pipeline_failed",
            "job_id": _pipeline_job_id,
            "step": failed_step,
            "user_message": user_msg,
            "developer_message": str(e),
            "success": False,
        }))
        p(f"\n{'═' * 60}")
        p(f"  ✗ Pipeline 失败: {e}")
        p(f"{'═' * 60}")
        sys.exit(1)


def _run_pipeline_steps(mode: str, job_id: str, output_dir: Path) -> dict:
    """Execute all pipeline steps. Returns the QA report. Raises on any failure."""
    # === Step 1: Market Input ===
    t0 = time.time()
    step_header(1, "读取市场数据", "MarketInput")
    step_start("market_input", "读取市场数据", "MarketInput")
    apps = load_market_input(mode=mode)
    p(f"  已加载 {len(apps)} 个候选应用")
    for a in apps:
        p(f"    • {a['name_cn']} ({a['name']}) - {a['downloads']:,} 下载")
    step_end(artifact="candidate.json")
    step_done("data/samples/apps.json", time.time() - t0)

    # === Step 2: Select best candidate ===
    step_header(2, "选择最优候选", "DemandAnalysis")
    step_start("demand_analysis", "选择最优候选", "DemandAnalysis")
    t0 = time.time()

    # Score all apps and pick the best. Viral Score is part of the decision,
    # not only a post-selection label. 选择逻辑在 select_best_candidate（可单测）。
    best_app, best_analysis, best_viral_preview, scored = select_best_candidate(apps)
    for app, analysis, viral_preview in scored:
        p(
            f"    {app['name_cn']}: 需求 {analysis['demand_score']} / "
            f"传播 {viral_preview['viral_score']} → 综合 {analysis['candidate_decision_score']}"
        )

    p("")
    p(
        f"  ★ 选中：{best_app['name_cn']} "
        f"(综合 {best_analysis['candidate_decision_score']}，传播 {best_viral_preview['viral_score']})"
    )

    _write(output_dir / "candidate.json", json.dumps(best_app, ensure_ascii=False, indent=2))
    _write(output_dir / "analysis.json", json.dumps(best_analysis, ensure_ascii=False, indent=2))
    step_end(artifact="analysis.json")
    step_done(f"data/outputs/{job_id}/analysis.json", time.time() - t0)

    # === Step 3: Gap Check ===
    step_header(3, "小程序覆盖检查", "GapCheck")
    step_start("gap_check", "覆盖缺口检查", "GapCheck")
    t0 = time.time()
    gap = check_gap(best_app)
    p(f"  缺失平台: {gap['missing_platforms']}")
    p(f"  缺口评分: {gap['gap_score']}")
    p(f"  推荐平台: {gap['recommended_platforms']}")
    p(f"  机会等级: {gap['opportunity_level']}")
    _write(output_dir / "gap-check.json", json.dumps(gap, ensure_ascii=False, indent=2))
    step_end(artifact="gap-check.json")
    step_done(f"data/outputs/{job_id}/gap-check.json", time.time() - t0)

    # === Step 4: Viral Score + template selection ===
    step_header(4, "传播力评分 + 模板选择", "ViralScore")
    step_start("viral_score", "传播力评分", "ViralScore")
    t0 = time.time()
    viral = compute_viral_score(best_app)
    selection = classify_template(best_app, viral)
    p(f"  Viral Score: {viral['viral_score']}/100 ({viral['tier']})")
    p(f"  题材: {selection['theme_label']} → 模板 {selection['selected_template']}")
    p(f"  排期优先级: {selection['priority']}")
    _write(output_dir / artifact_names.VIRAL_SCORE_JSON, json.dumps(viral, ensure_ascii=False, indent=2))
    _write(output_dir / artifact_names.TEMPLATE_SELECTION_JSON, json.dumps(selection, ensure_ascii=False, indent=2))
    step_end(artifact=artifact_names.VIRAL_SCORE_JSON)
    step_done(f"data/outputs/{job_id}/{artifact_names.VIRAL_SCORE_JSON}", time.time() - t0)

    # === Step 5: Opportunity Score ===
    step_header(5, "机会评分", "OpportunityScore")
    step_start("opportunity_score", "机会评分", "OpportunityScore")
    t0 = time.time()
    opportunity = compute_opportunity_score(best_app, best_analysis, gap, viral=viral)
    p(f"  综合评分: {opportunity['opportunity_score']}/100")
    p(f"  传播维度: {opportunity['viral_score']}/100")
    p(f"  推荐动作: {opportunity['recommendation']}")
    p(f"  预计开发: {opportunity['estimated_dev_days']} 天")
    _write(output_dir / "opportunity-report.json", json.dumps(opportunity, ensure_ascii=False, indent=2))
    step_end(artifact="opportunity-report.json")
    step_done(f"data/outputs/{job_id}/opportunity-report.json", time.time() - t0)

    # === Step 6: Generate PRD ===
    step_header(6, "生成 PRD", "PRD")
    step_start("prd_generation", "生成 PRD", "PRD")
    t0 = time.time()
    prd_md, prd_json = build_prd(best_app, opportunity)
    _write(output_dir / "prd.md", prd_md)
    _write(output_dir / "prd.json", json.dumps(prd_json, ensure_ascii=False, indent=2))
    p(f"  功能数: {len(prd_json['core_features'])}")
    p(f"  页面数: {len(prd_json['pages'])}")
    p(f"  技术栈: {prd_json['tech_stack']['framework']}")
    step_end(artifact="prd.json")
    step_done(f"data/outputs/{job_id}/prd.json", time.time() - t0)

    # === Step 7: Generate Code ===
    step_header(7, "生成小程序代码", "Codegen")
    step_start("code_generation", "生成代码", "Codegen")
    t0 = time.time()
    gen_dir = output_dir / "generated"
    gen_dir.mkdir(exist_ok=True)
    miniapp_dir, gen_source = generate_miniapp(best_app, prd_json, gen_dir, template=selection["selected_template"])
    _write(output_dir / "generator-source.json", json.dumps(gen_source, ensure_ascii=False, indent=2))
    # codegen-report.json：生成模块自我说明（区别于 qa-report.json 的质量判定）。
    codegen_report = dict(gen_source.get("codegen_report") or {})
    codegen_report["job_id"] = job_id
    codegen_report["created_at"] = datetime.now().isoformat()
    _write(output_dir / artifact_names.CODEGEN_REPORT_JSON,
           json.dumps(codegen_report, ensure_ascii=False, indent=2))
    file_count = gen_source["generated_files_count"]
    p(f"  项目路径: {miniapp_dir}")
    p(f"  生成文件: {file_count} 个")
    p(f"  模板来源: {gen_source['source']} ({gen_source['template']})")
    p(f"  输入类型: {codegen_report.get('input_type', 'app_candidate')}")
    step_end(artifact="generated/miniapp/")
    step_done(f"data/outputs/{job_id}/generated/miniapp/", time.time() - t0)

    # === Step 8: Publish Materials ===
    step_header(8, "生成上架材料", "PublishMaterials")
    step_start("publish_materials", "上架材料", "PublishMaterials")
    t0 = time.time()
    listing_md, listing_json = build_listing_materials(best_app, prd_json)
    _write(output_dir / "listing-materials.md", listing_md)
    _write(output_dir / "listing-materials.json", json.dumps(listing_json, ensure_ascii=False, indent=2))
    p(f"  小程序名: {listing_json['app_name_cn']}")
    p(f"  服务类目: {listing_json['category_suggestion']}")
    p(f"  关键词: {', '.join(listing_json['keywords'])}")
    step_end(artifact="listing-materials.json")
    step_done(f"data/outputs/{job_id}/listing-materials.json", time.time() - t0)

    # === Step 9: 增长 + 分享策略（core.growth）===
    step_header(9, "增长 + 分享策略", "Growth")
    step_start("growth_strategy", "增长策略", "Growth")
    t0 = time.time()
    growth_md = build_growth_plan(best_app, viral, selection)
    share_md = build_share_strategy(best_app, viral, selection)
    _write(output_dir / artifact_names.GROWTH_PLAN_MD, growth_md)
    _write(output_dir / artifact_names.SHARE_STRATEGY_MD, share_md)
    p(f"  growth-plan.md / share-strategy.md 已生成（传播力 {viral['tier']}）")
    step_end(artifact=artifact_names.GROWTH_PLAN_MD)
    step_done(f"data/outputs/{job_id}/{artifact_names.GROWTH_PLAN_MD}", time.time() - t0)

    # === Step 10: Human Actions + Publish Package ===
    step_header(10, "生成提交审核包", "PublishPackage")
    step_start("submit_package", "提交审核包", "PublishPackage")
    t0 = time.time()
    # 组装由 core.publisher 负责；平台差异来自 core.platforms.guides。
    build_publish_package(
        best_app, job_id, output_dir,
        listing_md=listing_md, listing_json=listing_json,
        target_platforms=opportunity["target_platforms"],
    )
    p(f"  publish-package/ 已生成")
    p(f"  目标平台: {', '.join(opportunity['target_platforms'])}")
    step_end(artifact="publish-package/")
    step_done(f"data/outputs/{job_id}/publish-package/", time.time() - t0)

    # === Step 11: QA Check (runs last, includes npm install + build) ===
    step_header(11, "质量检查 + 构建验证", "EngineeringQA")
    step_start("build_qa", "构建+质检", "EngineeringQA")
    t0 = time.time()
    p(f"  执行 npm install + npm run build:mp-weixin...")
    qa = run_engineering_qa(miniapp_dir, output_dir)
    checks = qa["checks"]
    p(f"  文件存在:   {'通过' if checks['files_exist'] else '失败'}")
    p(f"  编码检查:   {'通过' if checks['encoding_passed'] else '失败 - 发现乱码'}")
    p(f"  路径检查:   {'通过' if checks['path_passed'] else '失败'}")
    p(f"  上架字段:   {'通过' if checks['listing_fields_passed'] else '失败'}")
    p(f"  README:     {'通过' if checks['readme_passed'] else '失败'}")
    p(f"  构建脚本:   {'通过' if checks['build_scripts_passed'] else '失败'}")
    p(f"  JSON 合法:  {'通过' if checks['json_valid'] else '失败'}")
    p(f"  包大小:     {qa['total_size_readable']}（{'合规' if checks['size_within_limit'] else '超限'}）")
    p(f"  npm install: {'通过' if checks['install_passed'] else '失败'} ({checks['install_duration_ms']}ms)")
    p(f"  build 验证:  {'通过' if checks['build_passed'] else '失败'} ({checks['build_duration_ms']}ms)")
    p(f"  dist 存在:   {'是' if checks['dist_exists'] else '否'}")
    if checks.get('dist_path'):
        p(f"  dist 路径:   {checks['dist_path']}")
    p(f"  QA 结果:    {'✓ 全部通过' if qa['passed'] else '✗ 未通过'}")
    if qa["issues"]:
        for issue in qa["issues"][:5]:
            p(f"    ▸ {issue}")
    _write(output_dir / "qa-report.json", json.dumps(qa, ensure_ascii=False, indent=2))
    # Mark step as failed if QA didn't pass, so pipeline-report stays consistent
    if qa["passed"]:
        step_end(artifact="qa-report.json")
    else:
        qa_fail_reason = "; ".join(qa["issues"][:3]) if qa["issues"] else "QA 检查未通过"
        step_end(artifact="qa-report.json", error=qa_fail_reason,
                 error_code="qa_failed", user_message=f"QA 未通过: {qa_fail_reason}")
    step_done(f"data/outputs/{job_id}/qa-report.json", time.time() - t0)

    # === Step 12: 增长 QA + 合规 QA（core.qa）===
    step_header(12, "增长 QA + 合规 QA", "GrowthComplianceQA")
    step_start("growth_compliance_qa", "增长/合规质检", "GrowthComplianceQA")
    t0 = time.time()
    growth_qa = run_growth_qa(output_dir, miniapp_dir=miniapp_dir)
    compliance_qa = run_compliance_qa(miniapp_dir, output_dir)
    generator_qa = run_generator_qa(miniapp_dir=miniapp_dir)
    _write(output_dir / artifact_names.GROWTH_QA_JSON, json.dumps(growth_qa, ensure_ascii=False, indent=2))
    _write(output_dir / artifact_names.COMPLIANCE_QA_JSON, json.dumps(compliance_qa, ensure_ascii=False, indent=2))
    _write(output_dir / artifact_names.GENERATOR_QA_JSON, json.dumps(generator_qa, ensure_ascii=False, indent=2))
    p(f"  增长 QA: {'通过' if growth_qa['passed'] else '未通过'}")
    p(f"  合规 QA: {'通过' if compliance_qa['passed'] else '未通过'}")
    p(f"  生成器 QA: {'通过' if generator_qa['passed'] else '未通过'}")
    for issue in (growth_qa['issues'] + compliance_qa['issues'] + generator_qa['issues'])[:5]:
        p(f"    ▸ {issue}")
    for warn in compliance_qa.get('warnings', [])[:5]:
        p(f"    ⚠ {warn}")
    step_end(artifact=artifact_names.GROWTH_QA_JSON)
    step_done(f"data/outputs/{job_id}/{artifact_names.GROWTH_QA_JSON}", time.time() - t0)

    # === Step 13: Honest submission readiness + artifact manifest (post-QA) ===
    step_header(13, "提交就绪评估 + 产物清单", "Readiness")
    step_start("readiness", "提交就绪评估", "Readiness")
    t0 = time.time()
    readiness = build_submission_readiness(
        best_app, opportunity, qa, output_dir, mode, job_id=job_id,
        growth_qa=growth_qa, compliance_qa=compliance_qa, generator_qa=generator_qa,
    )
    _write(output_dir / "submission-readiness-report.json", json.dumps(readiness, ensure_ascii=False, indent=2))
    manifest = build_artifact_manifest(output_dir, qa, readiness, job_id=job_id)
    _write(output_dir / "artifact-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    p(f"  可提交审核: {'是' if readiness['ready_to_submit'] else '否'}")
    if not readiness["ready_to_submit"]:
        p(f"  阻塞项:")
        for b in readiness["blocking_issues"]:
            p(f"    ▸ {b}")
    step_end(artifact="submission-readiness-report.json")
    step_done(f"data/outputs/{job_id}/submission-readiness-report.json", time.time() - t0)

    # === Step 14: Telegram 自动部署 ===
    tg_deploy_result = None
    if "telegram" in opportunity.get("target_platforms", []):
        _tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        _cf_token = os.getenv("CLOUDFLARE_API_TOKEN", "")
        if _tg_token and _cf_token:
            step_header(14, "Telegram 自动部署", "TelegramDeploy")
            step_start("telegram_deploy", "Telegram 部署", "TelegramDeploy")
            t0 = time.time()
            try:
                sys.path.insert(0, str(Path(__file__).parent))
                from core.publisher.telegram_deploy import deploy_telegram
                tg_deploy_result = deploy_telegram(job_id, output_dir, best_app, opportunity)
                _write(output_dir / "telegram-deploy.json",
                       json.dumps(tg_deploy_result, ensure_ascii=False, indent=2))
                if tg_deploy_result.get("status") == "deployed":
                    p(f"  ✅ Telegram 部署成功!")
                    p(f"  URL: {tg_deploy_result.get('webapp_url', '')}")
                    p(f"  Bot: {tg_deploy_result.get('bot_link', '')}")
                    step_end(artifact="telegram-deploy.json")
                else:
                    p(f"  ⚠️ 部署状态: {tg_deploy_result.get('status', 'unknown')}")
                    p(f"  原因: {tg_deploy_result.get('reason', tg_deploy_result.get('error', ''))}")
                    step_end(artifact="telegram-deploy.json",
                             error=tg_deploy_result.get("error", "deploy issue"))
            except Exception as e:
                p(f"  ❌ Telegram 部署失败: {e}")
                tg_deploy_result = {"status": "error", "error": str(e)}
                _write(output_dir / "telegram-deploy.json",
                       json.dumps(tg_deploy_result, ensure_ascii=False, indent=2))
                step_end(artifact="telegram-deploy.json", error=str(e))
            step_done(f"data/outputs/{job_id}/telegram-deploy.json", time.time() - t0)
        else:
            p(f"\n  [Telegram] 跳过自动部署（未配置 TELEGRAM_BOT_TOKEN 或 CLOUDFLARE_API_TOKEN）")

    # === SUMMARY ===
    p("\n" + "=" * 60)
    p("  ✓ Pipeline 完成")
    p("=" * 60)
    p(f"\n  选中应用: {best_app['name_cn']} ({best_app['name']})")
    p(f"  机会评分: {opportunity['opportunity_score']}/100")
    p(f"  QA 结果: {'通过 ✓' if qa['passed'] else '未通过 ✗'}")
    p(f"  可提交审核: {'是' if readiness['ready_to_submit'] else '否（见 submission-readiness-report.json）'}")
    p(f"  Job ID:  {job_id}")
    p(f"  输出目录: {output_dir}")
    p(f"\n  产物清单:")
    for f in sorted(output_dir.rglob("*")):
        if f.is_file():
            rel = f.relative_to(output_dir)
            p(f"    {rel}")

    p(f"\n{'─' * 60}")
    p(f"  ⚡ 下一步人工动作:")
    p(f"{'─' * 60}")
    if tg_deploy_result and tg_deploy_result.get("status") == "deployed":
        p(f"  ✅ Telegram 已自动上线: {tg_deploy_result.get('bot_link', '')}")
        p(f"  1. 阅读 prd.md 确认产品方案")
        p(f"  2. 微信/支付宝/抖音如需上架，阅读 human-actions.md")
    else:
        p(f"  1. 阅读 prd.md 确认产品方案")
        p(f"  2. 阅读 human-actions.md 了解上架步骤")
        p(f"  3. 使用微信开发者工具导入 generated/miniapp/")
        p(f"  4. 上传代码并提交审核")
    p(f"  5. 审核通过后发布上线")
    p(f"\n  详细指南: {output_dir / 'human-actions.md'}")
    p("")
    return qa


if __name__ == "__main__":
    main()

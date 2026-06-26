"""auto_runner 编排测试 — mock 抓取与生成，不打真实网络、不跑真实 build。"""

from __future__ import annotations

import json

from core.pipeline import auto_runner


def _fake_crawl_report():
    return {
        "counts": {"candidates": 5, "queue_pending": 3},
        "crawl_stats": {"total_tasks": 4, "fetched_tasks": 4},
        "dedup_stats": {"raw_records": 20, "unique_apps": 5},
        "feature_stats": {"total_features": 10, "recommended_features": 8},
        "queue_stats": {"pending": 3},
    }


def test_run_auto_orchestrates_crawl_then_generate(tmp_path, monkeypatch):
    # 1) mock 抓取：写一个 pending 队列到临时 OPP_DIR
    opp = tmp_path / "opportunity"
    opp.mkdir(parents=True)
    monkeypatch.setattr(auto_runner, "OPP_DIR", opp)
    monkeypatch.setattr(auto_runner, "QUEUE_PATH", opp / "opportunity-queue.json")
    monkeypatch.setattr(auto_runner, "OUTPUTS_DIR", tmp_path / "outputs")

    queue = [{"queue_id": "20260623-001", "feature_key": "app_store:1:ai_photo_retouch",
              "parent_app_key": "app_store:1", "feature_name_cn": "AI 修图",
              "selected_template": "ai-image", "status": "pending"}]

    def fake_crawl(regions=None, platforms=None, limit=None, force_refresh=False):
        (opp / "opportunity-queue.json").write_text(json.dumps(queue, ensure_ascii=False), encoding="utf-8")
        return _fake_crawl_report()

    monkeypatch.setattr(auto_runner.crawl_runner, "run_once", fake_crawl)

    # 2) mock 生成：不跑真实 build，返回成功摘要
    def fake_generate(job_id):
        return {"job_id": job_id, "exit_code": 0, "build_passed": True,
                "qa_passed": True, "selected_template": "ai-image"}

    monkeypatch.setattr(auto_runner, "_generate_one", fake_generate)

    report = auto_runner.run_auto(job_id="auto-test", regions="CN", platforms="app_store",
                                  limit=5, max_generate=1)

    assert report["auto_job_id"] == "auto-test"
    assert report["data_source"] == "opportunity_queue"
    assert report["source"] == "crawl_generated_opportunity"
    assert report["crawl_summary"]["queue_stats"]["pending"] == 3
    assert len(report["generated_jobs"]) == 1
    gen = report["generated_jobs"][0]
    assert gen["build_passed"] is True and gen["qa_passed"] is True
    assert gen["feature_key"] == "app_store:1:ai_photo_retouch"
    # auto-report 写盘
    assert (tmp_path / "outputs" / "auto-test-auto-report.json").exists()


def test_run_auto_stops_when_queue_empty(tmp_path, monkeypatch):
    opp = tmp_path / "opportunity"
    opp.mkdir(parents=True)
    monkeypatch.setattr(auto_runner, "OPP_DIR", opp)
    monkeypatch.setattr(auto_runner, "QUEUE_PATH", opp / "opportunity-queue.json")
    monkeypatch.setattr(auto_runner, "OUTPUTS_DIR", tmp_path / "outputs")

    def fake_crawl(regions=None, platforms=None, limit=None, force_refresh=False):
        (opp / "opportunity-queue.json").write_text("[]", encoding="utf-8")  # 空队列
        return _fake_crawl_report()

    monkeypatch.setattr(auto_runner.crawl_runner, "run_once", fake_crawl)
    called = {"n": 0}
    monkeypatch.setattr(auto_runner, "_generate_one", lambda j: called.__setitem__("n", called["n"] + 1))

    report = auto_runner.run_auto(job_id="auto-empty", max_generate=3)
    assert report["generated_jobs"] == []
    assert called["n"] == 0  # 队列空，未尝试生成

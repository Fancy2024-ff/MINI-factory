"""scripts/crawl_opportunities.py 测试 — preset 展开、参数覆盖、dry-run、warning。"""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "crawl_opportunities.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("crawl_opportunities_script", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


script = _load_script()


def _args(**kw):
    base = dict(preset=None, regions="", platforms="", categories="",
                entry_types="", limit=None, dry_run=False, date=None, max_tasks=None)
    base.update(kw)
    return argparse.Namespace(**base)


def test_preset_quick_expands_to_expected_params():
    params = script.resolve_args(_args(preset="quick"))
    assert params["regions"] == ["US"]
    assert params["platforms"] == ["app_store"]
    assert params["categories"] == ["photo"]
    assert params["entry_types"] == ["top_free"]
    assert params["limit"] == 5


def test_preset_cn_only_app_store():
    params = script.resolve_args(_args(preset="cn"))
    assert params["regions"] == ["CN"]
    assert params["platforms"] == ["app_store"]


def test_explicit_args_override_preset():
    params = script.resolve_args(_args(preset="quick", regions="CN,JP", limit=20))
    assert params["regions"] == ["CN", "JP"]  # 覆盖 preset 的 ["US"]
    assert params["limit"] == 20               # 覆盖 preset 的 5
    assert params["platforms"] == ["app_store"]  # 未覆盖，保留 preset


def test_all_presets_resolve_without_error():
    for name in ["cn", "global", "asia", "quick", "top", "search"]:
        params = script.resolve_args(_args(preset=name))
        assert "regions" in params and "platforms" in params


def test_dry_run_does_not_write(monkeypatch, tmp_path):
    captured = {}

    def fake_run_once(**kw):
        captured.update(kw)
        return {"dry_run": kw.get("dry_run"), "summary": {"success": 1, "failed": 0, "skipped": 0, "cached": 0},
                "counts": {"candidates": 1, "features_total": 1, "features_recommended": 1, "queue_pending": 1},
                "feature_stats": {"top_templates": {"ai-image": 1}}}

    monkeypatch.setattr(script.crawl_runner, "run_once", fake_run_once)
    monkeypatch.setattr("sys.argv", ["crawl_opportunities.py", "--preset", "quick", "--dry-run"])
    script.main()
    assert captured["dry_run"] is True


def test_warning_printed_when_queue_empty(capsys, monkeypatch):
    def fake_run_once(**kw):
        return {"dry_run": True, "summary": {"success": 1, "failed": 0, "skipped": 0, "cached": 0},
                "counts": {"candidates": 5, "features_total": 5, "features_recommended": 0, "queue_pending": 0},
                "feature_stats": {}}

    monkeypatch.setattr(script.crawl_runner, "run_once", fake_run_once)
    monkeypatch.setattr("sys.argv", ["crawl_opportunities.py", "--preset", "quick", "--dry-run"])
    script.main()
    out = capsys.readouterr().out
    assert "WARNING" in out and "queue_pending = 0" in out
    assert "rating filter" in out


def test_no_warning_when_queue_positive(capsys, monkeypatch):
    def fake_run_once(**kw):
        return {"dry_run": True, "summary": {"success": 1, "failed": 0, "skipped": 0, "cached": 0},
                "counts": {"candidates": 5, "features_total": 5, "features_recommended": 3, "queue_pending": 3},
                "feature_stats": {"top_templates": {"ai-image": 3}}}

    monkeypatch.setattr(script.crawl_runner, "run_once", fake_run_once)
    monkeypatch.setattr("sys.argv", ["crawl_opportunities.py", "--preset", "quick", "--dry-run"])
    script.main()
    out = capsys.readouterr().out
    assert "WARNING" not in out

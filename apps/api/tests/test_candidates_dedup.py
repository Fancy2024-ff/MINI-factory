"""候选 App 去重接口测试。

已进流水线（queue status in {queued, produced}）或已生产成功
（processed-apps.json status==produced）的 app，按 canonical_key 从
/api/opportunities/candidates 与 /api/opportunities/summary 的 top_candidates
中过滤掉；failed/skipped/pending 的 app 仍出现（失败可重试）。
仅在返回时过滤，candidate-pool.json 文件本身不变。
"""

from __future__ import annotations

import json


def _seed(api, candidates, queue, processed):
    opp = api.OUTPUTS_DIR.parent / "opportunity"
    opp.mkdir(parents=True, exist_ok=True)
    api.OPPORTUNITY_DIR = opp
    (opp / "candidate-pool.json").write_text(json.dumps(candidates, ensure_ascii=False), encoding="utf-8")
    (opp / "opportunity-queue.json").write_text(json.dumps(queue, ensure_ascii=False), encoding="utf-8")
    (opp / "processed-apps.json").write_text(json.dumps(processed, ensure_ascii=False), encoding="utf-8")
    return opp


def _candidates():
    return [
        {"canonical_key": "app_store:produced", "name": "Produced App"},
        {"canonical_key": "app_store:queued", "name": "Queued App"},
        {"canonical_key": "app_store:failed", "name": "Failed App"},
        {"canonical_key": "app_store:fresh", "name": "Fresh App"},
    ]


def _queue():
    return [
        {"queue_id": "q-1", "parent_app_key": "app_store:queued", "status": "queued"},
        {"queue_id": "q-2", "parent_app_key": "app_store:failed", "status": "failed"},
    ]


def _processed():
    return {"features": {"app_store:produced:meme": {"status": "produced",
                                                     "parent_app_key": "app_store:produced"}}}


def test_candidates_hide_processed_apps(server_client, auth_headers):
    client, api = server_client
    _seed(api, _candidates(), _queue(), _processed())
    res = client.get("/api/opportunities/candidates", headers=auth_headers)
    assert res.status_code == 200
    keys = {c["canonical_key"] for c in res.json()["items"]}
    # produced + queued 隐藏；failed + fresh 保留
    assert keys == {"app_store:failed", "app_store:fresh"}


def test_candidates_total_reflects_filtered(server_client, auth_headers):
    client, api = server_client
    _seed(api, _candidates(), _queue(), _processed())
    res = client.get("/api/opportunities/candidates", headers=auth_headers)
    assert res.json()["total"] == 2


def test_summary_top_candidates_filtered(server_client, auth_headers):
    client, api = server_client
    _seed(api, _candidates(), _queue(), _processed())
    res = client.get("/api/opportunities/summary", headers=auth_headers)
    assert res.status_code == 200
    keys = {c["canonical_key"] for c in res.json()["top_candidates"]}
    assert keys == {"app_store:failed", "app_store:fresh"}


def test_candidate_pool_file_not_modified(server_client, auth_headers):
    client, api = server_client
    opp = _seed(api, _candidates(), _queue(), _processed())
    before = (opp / "candidate-pool.json").read_text(encoding="utf-8")
    client.get("/api/opportunities/candidates", headers=auth_headers)
    after = (opp / "candidate-pool.json").read_text(encoding="utf-8")
    assert before == after  # 只读过滤，绝不改文件


def test_no_processed_no_filter(server_client, auth_headers):
    """无任何已处理记录时，候选全量返回。"""
    client, api = server_client
    _seed(api, _candidates(), [], {"features": {}})
    res = client.get("/api/opportunities/candidates", headers=auth_headers)
    assert res.json()["total"] == 4

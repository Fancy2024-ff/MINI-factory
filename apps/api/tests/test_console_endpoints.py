"""apps.api.main 控制台关键接口回归（jobs / overview / platforms / download / wechat）。

补齐上一轮缺口：除了鉴权/real-inputs/路径穿越/WS，这里覆盖控制台主要读接口
的鉴权 + 基本行为（空态、404、分页、产物结构、平台授权状态、wechat 上传失败行为）。
"""

import json


def _make_job(server, name="job-a", with_qa=True, with_candidate=True):
    """在隔离 OUTPUTS_DIR 下造一个 job 目录。"""
    d = server.OUTPUTS_DIR / name
    d.mkdir(parents=True, exist_ok=True)
    if with_candidate:
        (d / "candidate.json").write_text(
            json.dumps({"name": "Cool", "name_cn": "酷应用"}, ensure_ascii=False), encoding="utf-8")
    if with_qa:
        (d / "qa-report.json").write_text(
            json.dumps({"passed": True, "checks": {"build_verified": True, "dist_exists": True}}),
            encoding="utf-8")
    return d


# --- /api/jobs（公共读，分页 + 结构）---

def test_jobs_empty(server_client):
    client, _ = server_client
    res = client.get("/api/jobs")
    assert res.status_code == 200
    body = res.json()
    assert body["jobs"] == [] and body["total"] == 0


def test_jobs_lists_and_paginates(server_client):
    client, server = server_client
    for i in range(3):
        _make_job(server, f"job-{i}")
    res = client.get("/api/jobs")
    body = res.json()
    assert body["total"] == 3
    assert len(body["jobs"]) == 3
    j = body["jobs"][0]
    assert "id" in j and "artifacts" in j and "qa_passed" in j
    # 分页
    res2 = client.get("/api/jobs?limit=1&offset=0")
    assert len(res2.json()["jobs"]) == 1
    assert res2.json()["total"] == 3


# --- /api/jobs/latest（需 key）---

def test_jobs_latest_requires_key(server_client):
    client, _ = server_client
    assert client.get("/api/jobs/latest").status_code == 401


def test_jobs_latest_404_when_empty(server_client, auth_headers):
    client, _ = server_client
    assert client.get("/api/jobs/latest", headers=auth_headers).status_code == 404


def test_jobs_latest_returns_job(server_client, auth_headers):
    client, server = server_client
    _make_job(server, "only-job")
    res = client.get("/api/jobs/latest", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["id"] == "only-job"


# --- /api/jobs/{id}（需 key，404，产物 dict）---

def test_job_detail_requires_key(server_client):
    client, _ = server_client
    assert client.get("/api/jobs/x").status_code == 401


def test_job_detail_404(server_client, auth_headers):
    client, _ = server_client
    assert client.get("/api/jobs/missing", headers=auth_headers).status_code == 404


def test_job_detail_returns_artifacts(server_client, auth_headers):
    client, server = server_client
    _make_job(server, "job-detail")
    res = client.get("/api/jobs/job-detail", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == "job-detail"
    assert "candidate.json" in body["artifacts"]
    assert body["artifacts"]["qa-report.json"]["passed"] is True


# --- /api/overview（需 key，统计）---

def test_overview_requires_key(server_client):
    client, _ = server_client
    assert client.get("/api/overview").status_code == 401


def test_overview_counts_jobs(server_client, auth_headers):
    client, server = server_client
    _make_job(server, "ov-1")
    _make_job(server, "ov-2")
    res = client.get("/api/overview", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["total_jobs"] == 2
    assert body["pipeline_running"] is False


# --- /api/platforms（需 key）---

def test_platforms_requires_key(server_client):
    client, _ = server_client
    assert client.get("/api/platforms").status_code == 401


def test_platforms_returns_registry(server_client, auth_headers):
    client, _ = server_client
    res = client.get("/api/platforms", headers=auth_headers)
    assert res.status_code == 200
    assert "platforms" in res.json()


# --- /api/platform-auth/status（需 key，不泄密）---

def test_platform_auth_status_requires_key(server_client):
    client, _ = server_client
    assert client.get("/api/platform-auth/status").status_code == 401


def test_platform_auth_status_shape(server_client, auth_headers):
    client, _ = server_client
    res = client.get("/api/platform-auth/status", headers=auth_headers)
    assert res.status_code == 200
    plats = res.json()["platforms"]
    ids = {p["platform_id"] for p in plats}
    assert {"wechat", "telegram", "discord"} <= ids
    for p in plats:
        # 不泄露密钥：只暴露 configured / missing 字段名，不含值
        assert "configured" in p and "missing_config" in p
        assert "appid" not in p and "bot_token" not in p


# --- /api/platforms/wechat/upload（需 key，未配置时优雅失败）---

def test_wechat_upload_requires_key(server_client):
    client, _ = server_client
    assert client.post("/api/platforms/wechat/upload").status_code == 401


def test_wechat_upload_graceful_when_unconfigured(server_client, auth_headers):
    client, server = server_client
    # 隔离环境无 wechat.json -> 不抛异常，返回 upload_passed False + reason
    res = client.post("/api/platforms/wechat/upload", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["upload_passed"] is False
    assert "reason" in body


# --- /api/jobs/{id}/download（需 key，404）---

def test_download_requires_key(server_client):
    client, _ = server_client
    assert client.get("/api/jobs/x/download").status_code == 401


def test_download_404_missing_job(server_client, auth_headers):
    client, _ = server_client
    assert client.get("/api/jobs/missing/download", headers=auth_headers).status_code == 404


def test_download_returns_zip(server_client, auth_headers):
    client, server = server_client
    _make_job(server, "dl-job")
    res = client.get("/api/jobs/dl-job/download", headers=auth_headers)
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"


def test_download_miniapp_target_zips_source_tree(server_client, auth_headers):
    client, server = server_client
    d = _make_job(server, "dl-mini")
    miniapp = d / "generated" / "miniapp"
    miniapp.mkdir(parents=True, exist_ok=True)
    (miniapp / "app.json").write_text("{}", encoding="utf-8")
    res = client.get("/api/jobs/dl-mini/download?target=miniapp", headers=auth_headers)
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"
    assert "miniapp-source" in res.headers.get("content-disposition", "")


def test_download_dist_target_zips_build_output(server_client, auth_headers):
    client, server = server_client
    d = _make_job(server, "dl-dist")
    dist = d / "generated" / "miniapp" / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "bundle.js").write_text("console.log(1)", encoding="utf-8")
    res = client.get("/api/jobs/dl-dist/download?target=dist", headers=auth_headers)
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"


def test_download_invalid_target_400(server_client, auth_headers):
    client, server = server_client
    _make_job(server, "dl-bad")
    res = client.get("/api/jobs/dl-bad/download?target=../etc", headers=auth_headers)
    assert res.status_code == 400


def test_download_missing_target_content_404(server_client, auth_headers):
    client, server = server_client
    _make_job(server, "dl-empty")  # 没有 generated/miniapp
    res = client.get("/api/jobs/dl-empty/download?target=miniapp", headers=auth_headers)
    assert res.status_code == 404

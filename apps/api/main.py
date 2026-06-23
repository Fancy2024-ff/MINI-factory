"""
MiniApp Factory – FastAPI backend (production).
Zero duplicate routes. Each path+method defined exactly once.
"""

import os
import sys
import json
import hmac
import asyncio
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Literal, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Depends, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel, Field, ConfigDict, model_validator, ValidationError

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
from core.runtime.config import DATA_DIR

PIPELINE_RUNNER = PROJECT_ROOT / "core" / "pipeline" / "runner.py"
OUTPUTS_DIR = DATA_DIR / "outputs"
PLATFORMS_DIR = DATA_DIR / "platforms"
PLATFORM_AUTH_DIR = DATA_DIR / "platform-auth"
REAL_INPUTS_DIR = DATA_DIR / "inputs" / "real"
OPPORTUNITY_DIR = DATA_DIR / "opportunity"


def _real_inputs_file() -> Path:
    """Canonical real-input file."""
    return REAL_INPUTS_DIR / "apps.json"

# ---------------------------------------------------------------------------
# Auth + environment
# ---------------------------------------------------------------------------
APP_ENV = os.environ.get("APP_ENV", "development").lower()
DASHBOARD_API_KEY = os.environ.get("DASHBOARD_API_KEY", "")
DASHBOARD_ORIGIN = os.environ.get("DASHBOARD_ORIGIN", "http://localhost:5173")
API_HOST = os.environ.get("API_HOST", "127.0.0.1")
API_PORT = int(os.environ.get("API_PORT", "8000"))

# In production a real API key is mandatory — refuse to start without one.
if APP_ENV == "production" and not DASHBOARD_API_KEY:
    raise RuntimeError(
        "APP_ENV=production requires DASHBOARD_API_KEY to be set. "
        "Refusing to start with authentication disabled."
    )

async def verify_api_key(x_api_key: str = Header(default="")):
    """API key auth. Enforced whenever DASHBOARD_API_KEY is set (always in production).
    Uses constant-time comparison to prevent timing attacks."""
    if DASHBOARD_API_KEY and not hmac.compare_digest(x_api_key, DASHBOARD_API_KEY):
        raise HTTPException(401, "Invalid API key")

# ---------------------------------------------------------------------------
# App + CORS
# ---------------------------------------------------------------------------
app = FastAPI(title="MiniApp Factory API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[DASHBOARD_ORIGIN, "http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        return response


app.add_middleware(SecurityHeadersMiddleware)

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
import time as _time
from collections import deque

PIPELINE_TIMEOUT = int(os.environ.get("PIPELINE_TIMEOUT_SECONDS", "600"))
MAX_LOG_LINES = int(os.environ.get("MAX_LOG_LINES", "5000"))

pipeline_process: Optional[subprocess.Popen] = None
pipeline_job_id: Optional[str] = None
pipeline_logs: deque[str] = deque(maxlen=MAX_LOG_LINES)
# WebSocket clients keyed by job_id (or "__global__" for legacy)
ws_clients: dict[str, list[WebSocket]] = {}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_job_id() -> str:
    """YYYYMMDD-XXXXXXXXXXXX (date + 12 random hex chars)."""
    import secrets
    return datetime.now().strftime("%Y%m%d") + "-" + secrets.token_hex(6)


def _read_json(path: Path):
    """Read JSON with BOM-safe encoding."""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _flush_logs_to_disk(job_id: str):
    """Write buffered pipeline logs to a file in the job's output directory, then clear memory."""
    if not pipeline_logs:
        return
    try:
        job_dir = OUTPUTS_DIR / job_id
        if job_dir.exists():
            log_file = job_dir / "pipeline.log"
            log_file.write_text("\n".join(pipeline_logs), encoding="utf-8")
    except Exception:
        pass  # Best-effort; don't crash the cleanup path
    pipeline_logs.clear()

async def _broadcast(msg: dict, job_id: str = None):
    """Send JSON message to WebSocket clients for a specific job (or all if no job_id)."""
    text = json.dumps(msg, ensure_ascii=False)
    # Send to job-specific clients
    if job_id and job_id in ws_clients:
        for ws in ws_clients[job_id][:]:
            try:
                await ws.send_text(text)
            except Exception:
                ws_clients[job_id].remove(ws)
    # Also send to global clients
    if "__global__" in ws_clients:
        for ws in ws_clients["__global__"][:]:
            try:
                await ws.send_text(text)
            except Exception:
                ws_clients["__global__"].remove(ws)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class PipelineStartRequest(BaseModel):
    # 正式：crawl（抓取生成机会队列）/ queue（消费队列生成）。
    # demo/real 为 dev-only/legacy，仅兼容旧仪表盘。
    mode: Literal["crawl", "queue", "auto", "demo", "real"] = "queue"
    regions: str = "CN,US"
    platforms: str = "app_store"
    limit: int | None = 10
    max_generate: int = 1


class RealAppInput(BaseModel):
    """Validated + normalized real App input for Real Mode.

    Required: name, source, category, (description OR description_cn),
    (features OR features_cn non-empty). Everything else is defaulted/normalized
    so the pipeline never hits a KeyError on a defaultable field.
    """

    model_config = ConfigDict(extra="allow")

    name: str
    source: str
    category: str
    name_cn: str = ""
    description: str = ""
    description_cn: str = ""
    features: list[str] = Field(default_factory=list)
    features_cn: list[str] = Field(default_factory=list)
    downloads: int = 0
    rating: float = 0.0
    review_count: int = 0
    monetization: str = "unknown"

    @model_validator(mode="after")
    def _check_and_normalize(self):
        if not (self.description or self.description_cn):
            raise ValueError("description or description_cn is required")
        if not (self.features or self.features_cn):
            raise ValueError("features or features_cn must contain at least one item")
        # Cross-fill defaults
        self.name_cn = self.name_cn or self.name
        self.description = self.description or self.description_cn
        self.description_cn = self.description_cn or self.description
        self.features = self.features or self.features_cn
        self.features_cn = self.features_cn or self.features
        self.monetization = self.monetization or "unknown"
        return self


class ImageGenerationRequest(BaseModel):
    """图片生成请求（apps/api 仅做 HTTP adapter，不含 provider 业务逻辑）。"""

    template_id: str = "ai-image"
    prompt: str = ""
    style: str = ""
    aspect_ratio: str = "1:1"


class TemplateGenerationRequest(BaseModel):
    """模板级生成请求：结构化 input 由 core.generator.template_generation 改写为出图 prompt。"""

    template_id: str = "ai-image"
    input: dict = Field(default_factory=dict)


class QueueActionRequest(BaseModel):
    """机会队列动作：prioritize（提权）/ skip（跳过）/ retry（重试）/ generate_now（立即生成）。"""

    action: Literal["prioritize", "skip", "retry", "generate_now"]
    queue_id: str
    payload: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# SECTION: Pipeline
# ---------------------------------------------------------------------------

@app.post("/api/pipeline/start", dependencies=[Depends(verify_api_key)])
async def pipeline_start(req: PipelineStartRequest = PipelineStartRequest()):
    """Start pipeline in background, return immediately."""
    global pipeline_process, pipeline_job_id, pipeline_logs

    if pipeline_process and pipeline_process.poll() is None:
        raise HTTPException(409, "Pipeline already running")

    # Validate real mode has data
    if req.mode == "real":
        apps_file = _real_inputs_file()
        if not apps_file.exists():
            raise HTTPException(400, "No real input data: apps.json missing. Import apps first.")
        apps = _read_json(apps_file)
        if not apps:
            raise HTTPException(400, "apps.json is empty. Import at least one app for real mode.")

    # Generate job_id BEFORE starting
    job_id = _generate_job_id()
    pipeline_job_id = job_id
    pipeline_logs.clear()

    python_exe = sys.executable
    cmd = [
        python_exe, "-X", "utf8",
        str(PIPELINE_RUNNER),
        "--mode", req.mode,
        "--job-id", job_id,
    ]
    if req.mode in ("crawl", "auto"):
        if req.regions:
            cmd.extend(["--regions", req.regions])
        if req.platforms:
            cmd.extend(["--platforms", req.platforms])
        if req.limit:
            cmd.extend(["--limit", str(req.limit)])
    if req.mode == "auto":
        cmd.extend(["--max-generate", str(req.max_generate)])

    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}

    pipeline_process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(Path(__file__).parent.parent),
        env=env,
    )

    asyncio.create_task(_stream_pipeline_output(job_id))

    return {"accepted": True, "job_id": job_id, "mode": req.mode}

async def _stream_pipeline_output(job_id: str):
    """Read pipeline stdout line by line, broadcast via WebSocket. Kill on timeout."""
    global pipeline_process

    loop = asyncio.get_running_loop()
    started_at = _time.time()

    try:
        while pipeline_process and pipeline_process.poll() is None:
            # Total timeout check
            elapsed = _time.time() - started_at
            if elapsed > PIPELINE_TIMEOUT:
                pipeline_process.kill()
                await _broadcast({"type": "pipeline_failed", "job_id": job_id, "error": f"Timeout ({PIPELINE_TIMEOUT}s)", "success": False}, job_id=job_id)
                return

            # Per-line read timeout: min(30s, remaining budget) — prevents both
            # blocking forever on a stuck process and overshooting the total timeout.
            remaining = PIPELINE_TIMEOUT - elapsed
            line_timeout = min(30.0, max(0.5, remaining))
            try:
                line = await asyncio.wait_for(
                    loop.run_in_executor(None, pipeline_process.stdout.readline),
                    timeout=line_timeout,
                )
            except asyncio.TimeoutError:
                # No output within line_timeout — loop back and let the elapsed check decide
                continue
            except (ValueError, OSError):
                # Pipe closed (stop was called)
                break
            if not line:
                break
            line = line.rstrip()
            pipeline_logs.append(line)

            # Try parsing structured event from pipeline
            if line.startswith("{") and '"event"' in line:
                try:
                    event = json.loads(line)
                    event["type"] = event.pop("event", "step_log")
                    await _broadcast(event, job_id=job_id)
                    continue
                except Exception:
                    pass

            await _broadcast({"type": "step_log", "data": line, "job_id": job_id, "message": line}, job_id=job_id)

        # Pipeline finished
        exit_code = pipeline_process.returncode if pipeline_process else -1
        success = exit_code == 0
        try:
            await _broadcast({"type": "pipeline_finished", "job_id": job_id, "success": success}, job_id=job_id)
        except Exception:
            pass  # Best-effort; status polling is the safety net
    finally:
        _flush_logs_to_disk(job_id)
        ws_clients.pop(job_id, None)
        if pipeline_process is not None:
            pipeline_process = None  # Idempotent fallback if stop didn't clear it


@app.get("/api/pipeline/status")
def pipeline_status():
    """Current pipeline status."""
    running = pipeline_process is not None and pipeline_process.poll() is None
    return {
        "running": running,
        "job_id": pipeline_job_id,
        "log_lines": len(pipeline_logs),
    }


@app.post("/api/pipeline/stop", dependencies=[Depends(verify_api_key)])
def pipeline_stop():
    """Kill running pipeline. Immediately clears state so next start won't 409."""
    global pipeline_process
    if pipeline_process and pipeline_process.poll() is None:
        job_id = pipeline_job_id
        pipeline_process.terminate()
        try:
            pipeline_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pipeline_process.kill()
            pipeline_process.wait(timeout=2)
        pipeline_process = None  # Immediate cleanup; stream task's finally is idempotent
        return {"stopped": True, "job_id": job_id}
    raise HTTPException(409, "No pipeline running")


# ---------------------------------------------------------------------------
# SECTION: WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/ws/pipeline/{job_id}")
async def ws_pipeline_job(ws: WebSocket, job_id: str):
    """Per-job WebSocket for pipeline log streaming. Validates token if DASHBOARD_API_KEY set."""
    # Token validation via query param
    if DASHBOARD_API_KEY:
        token = ws.query_params.get("token", "")
        if not hmac.compare_digest(token, DASHBOARD_API_KEY):
            await ws.close(code=4001, reason="Unauthorized")
            return
    await ws.accept()
    if job_id not in ws_clients:
        ws_clients[job_id] = []
    ws_clients[job_id].append(ws)

    # Send buffered logs for this job
    if pipeline_job_id == job_id:
        for line in list(pipeline_logs)[-100:]:
            await ws.send_text(json.dumps({"type": "step_log", "data": line, "job_id": job_id, "message": line}))

    running = pipeline_process is not None and pipeline_process.poll() is None and pipeline_job_id == job_id
    await ws.send_text(json.dumps({"type": "status", "running": running, "job_id": job_id}))

    try:
        while True:
            await ws.receive_text()
    except (WebSocketDisconnect, Exception):
        if job_id in ws_clients and ws in ws_clients[job_id]:
            ws_clients[job_id].remove(ws)


@app.websocket("/ws/pipeline")
async def ws_pipeline_global(ws: WebSocket):
    """Global WebSocket (deprecated). Validates token if set."""
    if DASHBOARD_API_KEY:
        token = ws.query_params.get("token", "")
        if not hmac.compare_digest(token, DASHBOARD_API_KEY):
            await ws.close(code=4001, reason="Unauthorized")
            return
    await ws.accept()
    if "__global__" not in ws_clients:
        ws_clients["__global__"] = []
    ws_clients["__global__"].append(ws)

    for line in list(pipeline_logs)[-50:]:
        await ws.send_text(json.dumps({"type": "step_log", "data": line, "job_id": pipeline_job_id}))

    running = pipeline_process is not None and pipeline_process.poll() is None
    await ws.send_text(json.dumps({"type": "status", "running": running, "job_id": pipeline_job_id}))

    try:
        while True:
            await ws.receive_text()
    except (WebSocketDisconnect, Exception):
        if ws in ws_clients.get("__global__", []):
            ws_clients["__global__"].remove(ws)


# ---------------------------------------------------------------------------
# SECTION: Jobs CRUD (from OUTPUTS_DIR)
# ---------------------------------------------------------------------------

@app.get("/api/jobs")
def list_jobs(limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0)):
    """List all pipeline jobs, sorted newest first. Supports pagination."""
    if not OUTPUTS_DIR.exists():
        return {"jobs": [], "total": 0}
    jobs = []
    all_dirs = sorted(
        [d for d in OUTPUTS_DIR.iterdir() if d.is_dir()],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    total = len(all_dirs)
    dirs = all_dirs[offset:offset + limit]
    for d in dirs:
        job: dict = {"id": d.name, "path": str(d)}
        # QA report
        qa_file = d / "qa-report.json"
        if qa_file.exists():
            qa = _read_json(qa_file)
            job["qa_passed"] = qa.get("passed", False)
            job["build_verified"] = qa.get("checks", {}).get("build_verified", False)
        # Candidate info
        cand_file = d / "candidate.json"
        if cand_file.exists():
            cand = _read_json(cand_file)
            job["app_name"] = cand.get("name_cn", cand.get("name", ""))
            job["app_name_en"] = cand.get("name", "")
        # Artifacts list
        job["artifacts"] = [f.name for f in d.iterdir() if f.is_file()]
        job["has_miniapp"] = (d / "generated" / "miniapp").exists()
        jobs.append(job)
    return {"jobs": jobs, "total": total}


@app.get("/api/jobs/latest", dependencies=[Depends(verify_api_key)])
def get_latest_job():
    """Most recent job by modification time."""
    if not OUTPUTS_DIR.exists():
        raise HTTPException(404, "No jobs found")
    dirs = [d for d in OUTPUTS_DIR.iterdir() if d.is_dir()]
    if not dirs:
        raise HTTPException(404, "No jobs found")
    dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    return get_job_detail(dirs[0].name)


@app.get("/api/jobs/{job_id}", dependencies=[Depends(verify_api_key)])
def get_job_detail(job_id: str):
    """Full details for a specific job."""
    job_dir = OUTPUTS_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(404, "Job not found")

    result: dict = {"id": job_id, "path": str(job_dir), "artifacts": {}}

    for f in job_dir.iterdir():
        if f.is_file():
            if f.suffix == ".json":
                if f.stat().st_size > 512 * 1024:
                    result["artifacts"][f.name] = {"_truncated": True, "_size_bytes": f.stat().st_size}
                else:
                    try:
                        result["artifacts"][f.name] = _read_json(f)
                    except Exception:
                        result["artifacts"][f.name] = {"error": "parse failed"}
            elif f.suffix == ".md":
                result["artifacts"][f.name] = f.read_text(encoding="utf-8-sig")

    # Miniapp file tree
    miniapp_dir = job_dir / "generated" / "miniapp"
    if miniapp_dir.exists():
        result["miniapp_files"] = [
            str(f.relative_to(miniapp_dir))
            for f in miniapp_dir.rglob("*")
            if f.is_file() and "node_modules" not in str(f)
        ]
        result["miniapp_path"] = str(miniapp_dir)

    return result


@app.get("/api/jobs/{job_id}/artifact", dependencies=[Depends(verify_api_key)])
def get_job_artifact(job_id: str, file: str):
    """Read a specific artifact file from a job."""
    job_dir = OUTPUTS_DIR / job_id
    file_path = job_dir / file

    # Security: path must resolve within job_dir
    try:
        file_path.resolve().relative_to(job_dir.resolve())
    except ValueError:
        raise HTTPException(403, "Access denied")

    if not file_path.exists():
        raise HTTPException(404, f"Artifact not found: {file}")

    content = file_path.read_text(encoding="utf-8-sig")
    if file_path.suffix == ".json":
        return json.loads(content)
    return {"content": content}


# ---------------------------------------------------------------------------
# SECTION: Opportunities (crawl outputs)
# ---------------------------------------------------------------------------

def _read_opportunity_json(name: str, default):
    path = OPPORTUNITY_DIR / name
    if not path.exists():
        return default
    try:
        return _read_json(path)
    except Exception:
        return default


def _limit_items(items, limit: int):
    if not isinstance(items, list):
        return []
    return items[:limit]


@app.get("/api/opportunities/summary", dependencies=[Depends(verify_api_key)])
def get_opportunities_summary(limit: int = Query(default=8, ge=1, le=50)):
    """Read the latest opportunity crawl outputs for the dashboard."""
    report = _read_opportunity_json("crawl-report.json", {})
    queue = _read_opportunity_json("opportunity-queue.json", [])
    candidates = _read_opportunity_json("candidate-pool.json", [])
    features = _read_opportunity_json("feature-opportunities.json", [])

    pending = [q for q in queue if q.get("status") == "pending"]
    produced = [q for q in queue if q.get("status") == "produced"]
    failed = [q for q in queue if q.get("status") == "failed"]

    top_templates = report.get("feature_stats", {}).get("top_templates", {})
    if not top_templates:
        for q in pending:
            t = q.get("selected_template") or "unknown"
            top_templates[t] = top_templates.get(t, 0) + 1

    return {
        "exists": bool(report or queue or candidates or features),
        "updated_at": report.get("finished_at") or report.get("started_at"),
        "crawl_stats": report.get("crawl_stats", {}),
        "dedup_stats": report.get("dedup_stats", {}),
        "feature_stats": report.get("feature_stats", {}),
        "queue_stats": {
            **(report.get("queue_stats", {}) if isinstance(report.get("queue_stats"), dict) else {}),
            "pending": len(pending),
            "produced": len(produced),
            "failed": len(failed),
            "total": len(queue) if isinstance(queue, list) else 0,
        },
        "top_templates": top_templates,
        "top_queue": _limit_items(pending, limit),
        "top_candidates": _limit_items(candidates, limit),
        "top_features": _limit_items(features, limit),
    }


@app.get("/api/opportunities/queue", dependencies=[Depends(verify_api_key)])
def get_opportunity_queue(limit: int = Query(default=50, ge=1, le=200)):
    queue = _read_opportunity_json("opportunity-queue.json", [])
    return {"items": _limit_items(queue, limit), "total": len(queue) if isinstance(queue, list) else 0}


@app.get("/api/opportunities/candidates", dependencies=[Depends(verify_api_key)])
def get_opportunity_candidates(limit: int = Query(default=50, ge=1, le=200)):
    candidates = _read_opportunity_json("candidate-pool.json", [])
    return {"items": _limit_items(candidates, limit), "total": len(candidates) if isinstance(candidates, list) else 0}


@app.get("/api/opportunities/features", dependencies=[Depends(verify_api_key)])
def get_opportunity_features(limit: int = Query(default=50, ge=1, le=200)):
    features = _read_opportunity_json("feature-opportunities.json", [])
    return {"items": _limit_items(features, limit), "total": len(features) if isinstance(features, list) else 0}


@app.post("/api/opportunities/queue/action", dependencies=[Depends(verify_api_key)])
async def opportunity_queue_action(req: QueueActionRequest):
    """统一队列动作接口：真正改写 opportunity-queue.json，generate_now 触发 queue 生成。

    动作逻辑在 core.opportunity.opportunity_queue（API 只编排）：
    - prioritize：提到队首，下一次消费优先
    - skip：标记 skipped，不再消费
    - retry：failed/skipped 重置为 pending
    - generate_now：提权 + 启动 queue 模式 pipeline 真正消费该机会
    """
    from core.opportunity import opportunity_queue as oq

    queue_path = OPPORTUNITY_DIR / "opportunity-queue.json"
    queue = oq.load_queue(queue_path)
    if oq.find_item(queue, req.queue_id) is None:
        raise HTTPException(404, f"queue_id not found: {req.queue_id}")

    if req.action == "prioritize":
        oq.prioritize(queue, req.queue_id)
        oq.save_queue(queue_path, queue)
        return {"ok": True, "action": "prioritize", "queue_id": req.queue_id, "status": "pending"}

    if req.action == "skip":
        oq.skip(queue, req.queue_id)
        oq.save_queue(queue_path, queue)
        return {"ok": True, "action": "skip", "queue_id": req.queue_id, "status": "skipped"}

    if req.action == "retry":
        oq.retry(queue, req.queue_id)
        oq.save_queue(queue_path, queue)
        return {"ok": True, "action": "retry", "queue_id": req.queue_id, "status": "pending"}

    # generate_now：提权该机会到队首并启动 queue 模式生成（真正执行，不只改状态）。
    global pipeline_process, pipeline_job_id, pipeline_logs
    if pipeline_process and pipeline_process.poll() is None:
        raise HTTPException(409, "Pipeline already running")
    oq.retry(queue, req.queue_id)        # 确保是 pending
    oq.prioritize(queue, req.queue_id)   # 提到队首，runner 消费第一个 pending
    oq.save_queue(queue_path, queue)

    job_id = _generate_job_id()
    pipeline_job_id = job_id
    pipeline_logs.clear()
    cmd = [sys.executable, "-X", "utf8", str(PIPELINE_RUNNER), "--mode", "queue", "--job-id", job_id]
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    pipeline_process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        cwd=str(Path(__file__).parent.parent), env=env,
    )
    asyncio.create_task(_stream_pipeline_output(job_id))
    return {"ok": True, "action": "generate_now", "queue_id": req.queue_id,
            "accepted": True, "job_id": job_id, "mode": "queue"}


# ---------------------------------------------------------------------------
# SECTION: Platforms
# ---------------------------------------------------------------------------

@app.get("/api/platforms", dependencies=[Depends(verify_api_key)])
def get_platforms():
    """Read platform registry."""
    reg_file = PLATFORMS_DIR / "platform-registry.json"
    if not reg_file.exists():
        return {"platforms": []}
    platforms = _read_json(reg_file)
    return {"platforms": platforms, "total": len(platforms)}


# ---------------------------------------------------------------------------
# SECTION: Platform Auth
# ---------------------------------------------------------------------------

@app.get("/api/platform-auth/status", dependencies=[Depends(verify_api_key)])
def get_platform_auth_status():
    """Check auth config status for each platform (never exposes secrets)."""
    platform_configs = {
        "wechat": {"name": "微信小程序", "required": ["appid", "private_key_path"]},
        "telegram": {"name": "Telegram Mini Apps", "required": ["bot_token", "webapp_url"]},
        "discord": {"name": "Discord Activities", "required": ["application_id", "activity_url"]},
    }

    platforms_status = []
    for plat_id, meta in platform_configs.items():
        config_file = PLATFORM_AUTH_DIR / f"{plat_id}.json"
        configured = False
        can_upload = False
        can_submit = False
        missing: list[str] = meta["required"][:]

        if config_file.exists():
            try:
                config = _read_json(config_file)
                missing = [f for f in meta["required"] if not config.get(f)]
                configured = len(missing) == 0
                can_upload = configured and config.get("upload_enabled", False)
                can_submit = configured and config.get("submit_review_enabled", False)
            except Exception:
                missing = meta["required"][:]

        platforms_status.append({
            "platform_id": plat_id,
            "platform_name": meta["name"],
            "configured": configured,
            "can_upload": can_upload,
            "can_submit_review": can_submit,
            "missing_config": missing,
        })

    return {"platforms": platforms_status}


@app.post("/api/platforms/wechat/upload", dependencies=[Depends(verify_api_key)])
def wechat_upload():
    """微信代码上传：配置完整且 miniprogram-ci 可用时真正执行上传，否则结构化失败。

    安全：不回显 private_key 内容；只返回 stdout/stderr 摘要 + 稳定原因。
    """
    config_file = PLATFORM_AUTH_DIR / "wechat.json"
    if not config_file.exists():
        return {"upload_passed": False, "reason": "wechat.json not found in platform-auth"}

    try:
        config = _read_json(config_file)
    except Exception as e:
        return {"upload_passed": False, "reason": f"config parse error: {e}"}

    appid = config.get("appid")
    pk_path = config.get("private_key_path")
    if not appid or not pk_path:
        return {"upload_passed": False, "reason": "appid or private_key_path missing"}
    if not config.get("upload_enabled"):
        return {"upload_passed": False, "reason": "upload_enabled is false"}
    if not Path(pk_path).exists():
        return {"upload_passed": False, "reason": "private_key file not found at private_key_path"}

    import shutil
    if not shutil.which("npx"):
        return {"upload_passed": False, "reason": "npx not found on PATH"}

    # 定位最近一次生成产物的 mp-weixin 构建目录
    project_path = _latest_mp_weixin_dist()
    if not project_path:
        return {"upload_passed": False, "reason": "no built mp-weixin dist found; run pipeline first"}

    version = config.get("version") or "1.0.0"
    desc = config.get("desc") or "auto upload via miniprogram-ci"
    # 通过 npx miniprogram-ci 执行上传（需本地已装 miniprogram-ci / npx 可拉取）。
    cmd = [
        "npx", "miniprogram-ci", "upload",
        "--pp", str(project_path),
        "--pkp", str(pk_path),
        "--appid", str(appid),
        "--uv", str(version),
        "--ud", str(desc),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(Path(__file__).parent.parent), timeout=180,
        )
    except subprocess.TimeoutExpired:
        return {"upload_passed": False, "reason": "miniprogram-ci upload timed out (180s)",
                "next_action": "检查网络/密钥后重试"}
    except Exception as e:
        return {"upload_passed": False, "reason": f"miniprogram-ci invocation failed: {type(e).__name__}"}

    ok = proc.returncode == 0
    return {
        "upload_passed": ok,
        "appid": appid,
        "version": version,
        "stdout_tail": (proc.stdout or "")[-600:],
        "stderr_tail": (proc.stderr or "")[-600:],
        "next_action": ("登录微信公众平台 → 版本管理 → 提交审核" if ok
                        else "上传失败，检查 stderr_tail / appid / 密钥 / 合法域名后重试"),
    }


def _latest_mp_weixin_dist() -> Path | None:
    """返回最近一次生成产物里的 dist/build/mp-weixin 目录（含 app.json）。"""
    import os as _os
    candidates = []
    if OUTPUTS_DIR.exists():
        for job_dir in OUTPUTS_DIR.iterdir():
            mp = job_dir / "generated" / "miniapp" / "dist" / "build" / "mp-weixin"
            if (mp / "app.json").exists():
                candidates.append(mp)
    if not candidates:
        return None
    return max(candidates, key=lambda p: _os.path.getmtime(p))


# ---------------------------------------------------------------------------
# SECTION: Real Inputs
# ---------------------------------------------------------------------------

@app.get("/api/real-inputs/apps", dependencies=[Depends(verify_api_key)])
def get_real_inputs():
    """Get imported real app list."""
    apps_file = _real_inputs_file()
    if not apps_file.exists():
        return {"apps": [], "exists": False}
    apps = _read_json(apps_file)
    return {"apps": apps, "exists": True}


@app.post("/api/real-inputs/apps", dependencies=[Depends(verify_api_key)])
async def save_real_inputs(request: Request):
    """Validate, normalize and save real app data. Returns 400 with per-item errors."""
    body = await request.body()
    try:
        data = json.loads(body)
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    raw = data if isinstance(data, list) else data.get("apps", [])
    if not isinstance(raw, list):
        raise HTTPException(400, "Expected a JSON array of apps")
    if not raw:
        raise HTTPException(400, "At least one app is required")

    normalized: list[dict] = []
    errors: list[dict] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            errors.append({"index": i, "errors": [{"field": "", "message": "must be an object"}]})
            continue
        try:
            model = RealAppInput(**item)
            normalized.append(model.model_dump())
        except ValidationError as e:
            errors.append({
                "index": i,
                "errors": [
                    {"field": ".".join(str(x) for x in err["loc"]), "message": err["msg"]}
                    for err in e.errors()
                ],
            })

    if errors:
        raise HTTPException(status_code=400, detail={"message": "Validation failed", "errors": errors})

    REAL_INPUTS_DIR.mkdir(parents=True, exist_ok=True)
    (REAL_INPUTS_DIR / "apps.json").write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"saved": len(normalized)}


# ---------------------------------------------------------------------------
# SECTION: Overview
# ---------------------------------------------------------------------------

@app.get("/api/overview", dependencies=[Depends(verify_api_key)])
def get_overview():
    """Dashboard stats."""
    # Count jobs
    job_count = 0
    if OUTPUTS_DIR.exists():
        job_count = sum(1 for d in OUTPUTS_DIR.iterdir() if d.is_dir())

    # Count real inputs
    apps_file = _real_inputs_file()
    real_apps_count = 0
    if apps_file.exists():
        try:
            real_apps_count = len(_read_json(apps_file))
        except Exception:
            pass

    # Platform auth status
    platforms_configured = 0
    for name in ("wechat", "telegram", "discord"):
        cf = PLATFORM_AUTH_DIR / f"{name}.json"
        if cf.exists():
            try:
                c = _read_json(cf)
                if c.get("appid") or c.get("bot_token") or c.get("application_id"):
                    platforms_configured += 1
            except Exception:
                pass

    running = pipeline_process is not None and pipeline_process.poll() is None

    return {
        "total_jobs": job_count,
        "real_apps_imported": real_apps_count,
        "platforms_configured": platforms_configured,
        "pipeline_running": running,
        "current_job_id": pipeline_job_id if running else None,
    }


# ---------------------------------------------------------------------------
# SECTION: Image Generation (real provider via core.integrations)
# ---------------------------------------------------------------------------
# 权限边界：这是面向「生成产物（小程序前端）」的 runtime/public 接口，不是 dashboard
# 管理接口。生成出来的小程序不持有 DASHBOARD_API_KEY，因此本接口不挂 verify_api_key，
# 否则 api 模式在生产 apps/api 下必 401。provider key 只在后端 env，不下发前端。
# 仅此 runtime 接口豁免管理鉴权；其它 dashboard 管理接口的鉴权保持不变。

# 防滥用：prompt 长度上限（runtime 接口无管理鉴权，需基础输入约束）。
MAX_PROMPT_LEN = 2000

# ---------------------------------------------------------------------------
# 防滥用：public generation 接口的内存限流（IP + 滑动时间窗口）。
# 这些接口无 dashboard 鉴权且会真实调用 image provider（有成本），上线后若被刷
# 会直接烧钱，因此加最基础的速率保护。第一版用进程内内存计数，不引入 Redis 等
# 重依赖；多进程部署下每进程各自计数（仍能挡住单点暴刷）。
# 仅作用于 runtime 接口；dashboard 管理接口不受影响。
# ---------------------------------------------------------------------------
GENERATION_RATE_LIMIT = int(os.environ.get("GENERATION_RATE_LIMIT", "10"))   # 窗口内最多调用次数
GENERATION_RATE_WINDOW = int(os.environ.get("GENERATION_RATE_WINDOW", "60"))  # 窗口秒数

# key=client ip, value=该 ip 最近调用的时间戳 deque
_generation_calls: dict[str, deque[float]] = {}
_generation_rate_lock = __import__("threading").Lock()


def _client_ip(request: Request) -> str:
    """取客户端 IP：优先 X-Forwarded-For 首段（反代场景），否则 socket peer。"""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limited(request: Request) -> bool:
    """记录一次调用并判断是否超限。True=超限应拒绝。线程安全。"""
    now = _time.time()
    ip = _client_ip(request)
    with _generation_rate_lock:
        calls = _generation_calls.get(ip)
        if calls is None:
            calls = deque()
            _generation_calls[ip] = calls
        # 清掉窗口外的旧时间戳
        cutoff = now - GENERATION_RATE_WINDOW
        while calls and calls[0] < cutoff:
            calls.popleft()
        if len(calls) >= GENERATION_RATE_LIMIT:
            return True
        calls.append(now)
        return False


_RATE_LIMITED_RESPONSE = {
    "ok": False,
    "error": {
        "code": "RATE_LIMITED",
        "message": "请求过于频繁，请稍后再试",
        "retryable": True,
    },
}


@app.post("/api/generation/image")
def generate_image_endpoint(req: ImageGenerationRequest, request: Request):
    """生成产物图片生成 runtime 接口（public，不挂 dashboard 鉴权）。

    HTTP adapter：调 core.integrations.image_generation，返回 ok/result 或 ok/error。
    只做适配 + 校验，不含 provider 业务逻辑；不透传 provider 原始错误/key。
    """
    if _rate_limited(request):
        return _RATE_LIMITED_RESPONSE

    from core.integrations.image_generation import (
        ImageGenerationError,
        ERR_FAILED,
        generate_image,
    )

    prompt = (req.prompt or "").strip()
    if not prompt:
        return {"ok": False, "error": {"code": "VALIDATION_ERROR", "message": "prompt 不能为空"}}
    if len(prompt) > MAX_PROMPT_LEN:
        return {
            "ok": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": f"prompt 过长（上限 {MAX_PROMPT_LEN} 字符）",
            },
        }
    # 第一阶段只支持 ai-image。
    if req.template_id != "ai-image":
        return {
            "ok": False,
            "error": {
                "code": "UNSUPPORTED_TEMPLATE",
                "message": f"暂不支持模板 {req.template_id} 的真实图片生成",
            },
        }

    try:
        result = generate_image(prompt, style=req.style, aspect_ratio=req.aspect_ratio)
    except ImageGenerationError as e:
        # 只回稳定 code + 安全 message，不暴露 provider 原始信息。
        # retryable：瞬时类错误（超时/网络/provider 暂时失败）可重试，配置类不可。
        retryable = e.code in {
            "IMAGE_GENERATION_TIMEOUT",
            "IMAGE_GENERATION_PROVIDER_FAILED",
        }
        return {"ok": False, "error": {"code": e.code, "message": e.message, "retryable": retryable}}
    except Exception:
        return {"ok": False, "error": {"code": ERR_FAILED, "message": "图片生成失败，请稍后重试", "retryable": True}}

    import time as _t

    return {
        "ok": True,
        "result": {
            "preview_type": "image",
            "title": "AI 图片生成",
            "caption": prompt[:60],
            "image_url": result.get("image_url"),
            "image_base64": result.get("image_base64"),
            "prompt": result.get("prompt"),
            "provider": result.get("provider"),
            "created_at": int(_t.time()),
            "metadata": result.get("metadata", {}),
        },
    }


@app.post("/api/generation/template")
def generate_template_endpoint(req: TemplateGenerationRequest, request: Request):
    """模板级生成 runtime 接口（public，不挂 dashboard 鉴权）。

    白名单 template_id（目前 ai-image + avatar-viral），结构化 input 经
    core.generator.template_generation 改写为出图 prompt。不透传 provider key/原文。
    """
    if _rate_limited(request):
        return _RATE_LIMITED_RESPONSE

    from core.integrations.image_generation import ImageGenerationError, ERR_FAILED
    from core.generator.template_generation import (
        SUPPORTED_TEMPLATES,
        generate_template,
    )

    if req.template_id not in SUPPORTED_TEMPLATES:
        return {
            "ok": False,
            "error": {
                "code": "UNSUPPORTED_TEMPLATE",
                "message": f"暂不支持模板 {req.template_id}",
            },
        }

    inp = req.input if isinstance(req.input, dict) else {}
    try:
        return generate_template(req.template_id, inp)
    except ImageGenerationError as e:
        retryable = e.code in {"IMAGE_GENERATION_TIMEOUT", "IMAGE_GENERATION_PROVIDER_FAILED"}
        return {"ok": False, "error": {"code": e.code, "message": e.message, "retryable": retryable}}
    except Exception:
        return {"ok": False, "error": {"code": ERR_FAILED, "message": "生成失败，请稍后重试", "retryable": True}}


# ---------------------------------------------------------------------------
# SECTION: Zip Download
# ---------------------------------------------------------------------------

@app.get("/api/jobs/{job_id}/download", dependencies=[Depends(verify_api_key)])
def download_job(job_id: str):
    """Download all job artifacts as a zip file."""
    import zipfile
    import tempfile
    from fastapi.responses import FileResponse
    from starlette.background import BackgroundTask

    MAX_ZIP_SIZE = 100 * 1024 * 1024  # 100MB

    job_dir = OUTPUTS_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(404, "Job not found")

    # Collect files and enforce size cap
    total_size = 0
    files_to_zip = []
    for f in job_dir.rglob("*"):
        if f.is_file() and "node_modules" not in str(f):
            total_size += f.stat().st_size
            if total_size > MAX_ZIP_SIZE:
                raise HTTPException(413, "Job artifacts exceed maximum download size (100MB)")
            files_to_zip.append(f)

    # Create zip in temp directory
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp.close()

    with zipfile.ZipFile(tmp.name, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in files_to_zip:
            arcname = str(f.relative_to(job_dir))
            zf.write(f, arcname)

    # BackgroundTask to clean up temp file after response is sent
    def cleanup():
        try:
            os.unlink(tmp.name)
        except Exception:
            pass

    return FileResponse(
        tmp.name,
        media_type="application/zip",
        filename=f"miniapp-factory-{job_id}.zip",
        background=BackgroundTask(cleanup),
    )


# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------

@app.on_event("shutdown")
async def shutdown_event():
    """Clean up on server shutdown: kill any running pipeline subprocess."""
    global pipeline_process
    if pipeline_process and pipeline_process.poll() is None:
        pipeline_process.terminate()
        try:
            pipeline_process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pipeline_process.kill()
        pipeline_process = None
    if pipeline_job_id:
        _flush_logs_to_disk(pipeline_job_id)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    # reload only in development; bind to 127.0.0.1 by default for safety.
    uvicorn.run(
        "main:app" if APP_ENV != "production" else app,
        host=API_HOST,
        port=API_PORT,
        reload=(APP_ENV != "production"),
    )



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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Depends, Header, Query, UploadFile, File, Form
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
# 广告闸门配置（提交中心读写、TG 站运行时读）；功能 registry（已上架功能页）。
AD_CONFIG_PATH = PLATFORM_AUTH_DIR / "ad-config.json"
TELEGRAM_AUTH_PATH = PLATFORM_AUTH_DIR / "telegram.json"
FEATURES_REGISTRY_PATH = PROJECT_ROOT / "apps" / "web" / "src" / "tg" / "registry" / "features.generated.json"
# 广告视频上传：本地存 data/ad-videos/，经 public 路由 /api/tg/ad-video/<file> 服务。
AD_VIDEOS_DIR = DATA_DIR / "ad-videos"
MAX_AD_VIDEO_BYTES = int(os.environ.get("MAX_AD_VIDEO_BYTES", str(50 * 1024 * 1024)))
_ALLOWED_VIDEO_MIME = {"video/mp4": ".mp4", "video/webm": ".webm"}


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
# Telegram bot token：send-to-chat 接口用它校验 WebApp initData 并调 Bot API
# sendPhoto。只在服务端，不下发前端。
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

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
    # force_refresh=True 时绕过当日快照缓存强制重抓（默认 False 用缓存）。
    force_refresh: bool = False
    # 执行模型：async（默认，正式主路径）= 入队由 worker 异步执行；
    # sync（兼容/调试）= 旧的请求线程内直起子进程模型，非主路径。
    execution_mode: Literal["async", "sync"] = "async"


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


class SendToChatRequest(BaseModel):
    """把生成图发到用户 Telegram 聊天（send-to-chat）。

    init_data 是 Telegram WebApp 下发的已签名串，后端用 bot token 校验后取 chat_id，
    防止伪造请求把图发给任意用户。image_src 为图片 data URI 或 http(s) URL。
    """

    init_data: str = ""
    image_src: str = ""
    caption: str = ""


class QueueActionRequest(BaseModel):
    """机会队列动作：prioritize（提权）/ skip（跳过）/ retry（重试）/ generate_now（立即生成）。"""

    action: Literal["prioritize", "skip", "retry", "generate_now"]
    queue_id: str
    payload: dict = Field(default_factory=dict)


class AdConfigRequest(BaseModel):
    """提交中心：更新某功能页（route）的广告闸门配置。至少传一个可改字段。"""

    route: str
    ad_enabled: Optional[bool] = None
    ad_seconds: Optional[int] = None


class PipelineEnqueueRequest(BaseModel):
    """把一次生成/抓取/自动流程作为持久化任务入队（生产任务系统）。

    与 /api/pipeline/start 的区别：start 直接起子进程（单进程模型，旧行为保留），
    enqueue 只写入 task_store，由 task_worker 异步消费（可持久化/重试/取消/优先级）。
    """

    kind: Literal["pipeline.run", "opportunity.crawl", "pipeline.auto"] = "pipeline.run"
    priority: int = 100
    max_attempts: int = 3
    payload: dict = Field(default_factory=dict)



# ---------------------------------------------------------------------------
# SECTION: Pipeline
# ---------------------------------------------------------------------------
# 正式执行模型：task queue + task_worker（见 SECTION: Tasks）。API 默认只“入队 +
# 返回 task_id/job_id”，不在请求线程内直接跑 pipeline。/api/pipeline/start 默认 async；
# sync 仅兼容/调试。所有入队入口统一走 enqueue_pipeline_task helper（单一实现）。

# pipeline mode → task kind 映射（统一入队语义）。
_MODE_TO_KIND = {
    "queue": "pipeline.run",
    "demo": "pipeline.run",
    "real": "pipeline.run",
    "crawl": "opportunity.crawl",
    "auto": "pipeline.auto",
}


def enqueue_pipeline_task(
    mode: str,
    *,
    regions: str = "",
    platforms: str = "",
    limit: int | None = None,
    max_generate: int = 1,
    queue_id: str | None = None,
    job_id: str | None = None,
    priority: int = 100,
    max_attempts: int = 3,
    dedupe_queue_id: bool = False,
    force_refresh: bool = False,
) -> dict:
    """统一入队 helper：把一次 pipeline 动作（mode）建模成 task 并入 task_store。

    所有 API 入口（start / enqueue / generate_now）都走这里，避免两套分叉实现。
    - mode→kind 映射见 _MODE_TO_KIND。
    - payload 带 mode/job_id/queue_id/抓取参数，供 worker + runner 使用。
    - dedupe_queue_id=True 时（generate_now）：同一 queue_id 已有 active task 则不重复创建，
      返回 {"reused": True, ...}。
    返回结构含 task_id / kind / status / job_id / queue_id / reused。
    """
    kind = _MODE_TO_KIND.get(mode, "pipeline.run")
    store = _task_store()

    # 去重：同一 queue item 已有 pending/running 任务时，不重复创建。
    if dedupe_queue_id and queue_id:
        existing = store.find_active_by_queue_id(queue_id)
        if existing is not None:
            return {
                "ok": True, "reused": True, "task_id": existing["id"], "kind": existing["kind"],
                "status": existing["status"], "job_id": existing.get("job_id"),
                "queue_id": queue_id, "mode": mode,
            }

    # job_id：queue/demo/real 这类“生成”任务预分配，便于追踪产物目录；crawl 无 job 概念。
    if job_id is None and kind in ("pipeline.run", "pipeline.auto"):
        job_id = _generate_job_id()

    payload: dict = {"mode": mode}
    if job_id:
        payload["job_id"] = job_id
    if queue_id:
        payload["queue_id"] = queue_id
    if regions:
        payload["regions"] = regions
    if platforms:
        payload["platforms"] = platforms
    if limit is not None:
        payload["limit"] = limit
    if mode == "auto":
        payload["max_generate"] = max_generate
    if force_refresh:
        payload["force_refresh"] = True

    task_id = store.enqueue_task(
        kind=kind, payload=payload, priority=priority, max_attempts=max_attempts,
        queue_id=queue_id, job_id=job_id,
    )
    return {
        "ok": True, "reused": False, "task_id": task_id, "kind": kind,
        "status": "pending", "job_id": job_id, "queue_id": queue_id, "mode": mode,
    }


@app.post("/api/pipeline/start", dependencies=[Depends(verify_api_key)])
async def pipeline_start(req: PipelineStartRequest = PipelineStartRequest()):
    """启动一次 pipeline。

    默认 async（正式主路径）：创建 task 并返回 task_id/job_id，由 task_worker 执行。
    execution_mode=sync 走旧的请求线程内子进程模型（兼容/调试，非主路径）。
    """
    # Validate real mode has data (both paths).
    if req.mode == "real":
        apps_file = _real_inputs_file()
        if not apps_file.exists():
            raise HTTPException(400, "No real input data: apps.json missing. Import apps first.")
        apps = _read_json(apps_file)
        if not apps:
            raise HTTPException(400, "apps.json is empty. Import at least one app for real mode.")

    # --- 默认异步：入队，由 worker 执行 ---
    if req.execution_mode == "async":
        res = enqueue_pipeline_task(
            req.mode, regions=req.regions, platforms=req.platforms,
            limit=req.limit, max_generate=req.max_generate,
            force_refresh=req.force_refresh,
        )
        return {
            "accepted": True, "execution_mode": "async",
            "task_id": res["task_id"], "kind": res["kind"], "status": res["status"],
            "job_id": res.get("job_id"), "queue_id": res.get("queue_id"), "mode": req.mode,
        }

    # --- 兼容 sync：旧的请求线程内子进程模型（非主路径）---
    return _pipeline_start_sync(req)


def _pipeline_start_sync(req: PipelineStartRequest) -> dict:
    """旧同步模型：请求线程内直起 runner 子进程并流式 WS。仅兼容/调试，非主路径。"""
    global pipeline_process, pipeline_job_id, pipeline_logs

    if pipeline_process and pipeline_process.poll() is None:
        raise HTTPException(409, "Pipeline already running")

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

    return {"accepted": True, "execution_mode": "sync", "job_id": job_id, "mode": req.mode}

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


def _processed_app_keys() -> set:
    """已进流水线/已生产的 app canonical_key 集合（用于候选列表 app 级去重）。

    读 processed-apps.json + opportunity-queue.json，委托 core 纯函数计算。
    读不到文件 / 解析失败 → 空集合（绝不让去重逻辑影响接口可用性）。
    """
    from core.opportunity.processed_apps import processed_app_keys

    processed = _read_opportunity_json("processed-apps.json", {"features": {}})
    queue = _read_opportunity_json("opportunity-queue.json", [])
    try:
        return processed_app_keys(
            processed if isinstance(processed, dict) else {"features": {}},
            queue if isinstance(queue, list) else [],
        )
    except Exception:
        return set()


def _filter_processed_candidates(candidates):
    """从候选列表剔除已处理的 app（按 canonical_key）。非 list 原样返回。"""
    if not isinstance(candidates, list):
        return candidates
    hidden = _processed_app_keys()
    if not hidden:
        return candidates
    return [c for c in candidates if c.get("canonical_key") not in hidden]



@app.get("/api/opportunities/summary", dependencies=[Depends(verify_api_key)])
def get_opportunities_summary(limit: int = Query(default=8, ge=1, le=50)):
    """Read the latest opportunity crawl outputs for the dashboard."""
    report = _read_opportunity_json("crawl-report.json", {})
    queue = _read_opportunity_json("opportunity-queue.json", [])
    candidates = _read_opportunity_json("candidate-pool.json", [])
    features = _read_opportunity_json("feature-opportunities.json", [])

    # 候选列表 app 级去重：已进流水线/已生产的 app 不再出现（只读过滤）。
    candidates = _filter_processed_candidates(candidates)

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
    # app 级去重：已进流水线/已生产的 app 不再出现（只读过滤，文件不变）。
    candidates = _filter_processed_candidates(candidates)
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

    # generate_now：正式走 task queue。提权该机会 + 入队 pipeline.run（定向 queue_id 消费），
    # 由 worker 执行。同一 queue item 已有 active task 时不重复创建（返回 reused）。
    oq.retry(queue, req.queue_id)        # 确保是 pending（failed/skipped 也能重新发起）
    oq.prioritize(queue, req.queue_id)   # 提到队首（普通消费时也优先）

    res = enqueue_pipeline_task(
        "queue", queue_id=req.queue_id, dedupe_queue_id=True,
    )
    # 记录 queue item ↔ task ↔ job 映射，并标记 queued（task 系统已持有它）。
    oq.mark_queued(queue, req.queue_id, task_id=res["task_id"], job_id=res.get("job_id") or "")
    oq.save_queue(queue_path, queue)

    return {
        "ok": True, "action": "generate_now", "queue_id": req.queue_id,
        "accepted": True, "reused": res.get("reused", False),
        "task_id": res["task_id"], "kind": res["kind"], "status": res["status"],
        "job_id": res.get("job_id"), "mode": "queue",
    }


# ---------------------------------------------------------------------------
# SECTION: Tasks (persistent task queue — production task system)
# ---------------------------------------------------------------------------
# 生产任务系统：持久化 SQLite 队列（core.runtime.task_store），由独立 worker
# (core.pipeline.task_worker) 异步消费。这些接口只读/管理队列状态，不在请求线程内
# 执行 pipeline（与 /api/pipeline/start 的单进程模型并存，互不破坏）。

# 任务库路径（None=用 task_store 默认 data/runtime/tasks.sqlite3）。测试可覆盖。
TASK_DB_PATH: Optional[str] = None
_task_store_instance = None


def _task_store():
    """惰性构建任务库单例（按 TASK_DB_PATH）。测试改 TASK_DB_PATH 后置空本变量即可重建。"""
    global _task_store_instance
    if _task_store_instance is None:
        from core.runtime.task_store import TaskStore
        _task_store_instance = TaskStore(TASK_DB_PATH)
    return _task_store_instance


@app.get("/api/tasks/summary", dependencies=[Depends(verify_api_key)])
def tasks_summary():
    """任务队列统计（按状态/种类聚合 + 总数）。"""
    return _task_store().task_summary()


@app.get("/api/tasks/health", dependencies=[Depends(verify_api_key)])
def tasks_health():
    """队列健康指标：状态计数 + 最老 pending 等待 + 活跃 worker 近似数。"""
    return _task_store().health_summary()


@app.get("/api/tasks", dependencies=[Depends(verify_api_key)])
def list_tasks(
    status: Optional[str] = Query(default=None),
    kind: Optional[str] = Query(default=None),
    queue_id: Optional[str] = Query(default=None),
    job_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """列出任务（最新在前），可按 status / kind / queue_id / job_id 过滤。"""
    items = _task_store().list_tasks(
        status=status, kind=kind, queue_id=queue_id, job_id=job_id,
        limit=limit, offset=offset,
    )
    return {"tasks": items, "count": len(items)}


@app.get("/api/tasks/by-queue/{queue_id}", dependencies=[Depends(verify_api_key)])
def list_tasks_by_queue(queue_id: str, limit: int = Query(default=50, ge=1, le=200)):
    """按 queue_id 列出关联任务（task↔queue item 追踪）。"""
    items = _task_store().list_tasks(queue_id=queue_id, limit=limit)
    return {"queue_id": queue_id, "tasks": items, "count": len(items)}


@app.get("/api/tasks/by-job/{job_id}", dependencies=[Depends(verify_api_key)])
def list_tasks_by_job(job_id: str, limit: int = Query(default=50, ge=1, le=200)):
    """按 job_id 列出关联任务（task↔job 追踪）。"""
    items = _task_store().list_tasks(job_id=job_id, limit=limit)
    return {"job_id": job_id, "tasks": items, "count": len(items)}


@app.get("/api/tasks/{task_id}", dependencies=[Depends(verify_api_key)])
def get_task(task_id: str):
    """单个任务详情。"""
    task = _task_store().get_task(task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    return task


@app.post("/api/tasks/{task_id}/cancel", dependencies=[Depends(verify_api_key)])
def cancel_task(task_id: str):
    """取消任务（pending/running/failed -> cancelled）。终态任务返回当前状态不报错。"""
    store = _task_store()
    if store.get_task(task_id) is None:
        raise HTTPException(404, "Task not found")
    task = store.cancel_task(task_id)
    return {"ok": True, "task_id": task_id, "status": task["status"]}


@app.post("/api/tasks/{task_id}/retry", dependencies=[Depends(verify_api_key)])
def retry_task(task_id: str):
    """手动重试 failed 任务（failed -> pending，重置 attempts）。"""
    store = _task_store()
    if store.get_task(task_id) is None:
        raise HTTPException(404, "Task not found")
    task = store.retry_task(task_id)
    return {"ok": True, "task_id": task_id, "status": task["status"]}


@app.post("/api/tasks/maintenance/requeue-stale", dependencies=[Depends(verify_api_key)])
def requeue_stale_tasks():
    """回收锁过期的 running 任务（worker 崩溃/卡死后处理）。

    返回 requeued（仍有尝试余量、回 pending）与 failed（已达 max_attempts、标 failed）
    两个计数，避免「pending 却永不被 claim」的误导态。
    """
    stats = _task_store().requeue_stale_tasks_detailed()
    return {"ok": True, "requeued": stats["requeued"], "failed": stats["failed"]}


@app.post("/api/pipeline/enqueue", dependencies=[Depends(verify_api_key)])
def pipeline_enqueue(req: PipelineEnqueueRequest = PipelineEnqueueRequest()):
    """把一次 pipeline.run / opportunity.crawl / pipeline.auto 作为持久化任务入队。

    与 /api/pipeline/start（默认 async）共享同一执行模型：都进 task_store，由 worker 执行。
    本接口以 kind+payload 直接表达任务；start 以 mode 表达后映射到 kind。两者最终都落到
    同一个 task_store.enqueue_task。payload.queue_id / payload.job_id 会提为一等列以便追踪。
    """
    store = _task_store()
    payload = dict(req.payload or {})
    queue_id = payload.get("queue_id")
    job_id = payload.get("job_id")
    # 生成类任务若未带 job_id，预分配一个，保证 task↔job 可追踪。
    if job_id is None and req.kind in ("pipeline.run", "pipeline.auto"):
        job_id = _generate_job_id()
        payload["job_id"] = job_id

    # queue_id 去重：已有 active task 则复用（与 generate_now 一致）。
    if queue_id:
        existing = store.find_active_by_queue_id(queue_id)
        if existing is not None:
            return {"ok": True, "reused": True, "task_id": existing["id"],
                    "kind": existing["kind"], "status": existing["status"],
                    "job_id": existing.get("job_id"), "queue_id": queue_id}

    tid = store.enqueue_task(
        kind=req.kind, payload=payload, priority=req.priority,
        max_attempts=req.max_attempts, queue_id=queue_id, job_id=job_id,
    )
    return {"ok": True, "reused": False, "task_id": tid, "kind": req.kind,
            "status": "pending", "job_id": job_id, "queue_id": queue_id}


# ---------------------------------------------------------------------------
# SECTION: Submit Center — 已上架功能页 + 广告闸门配置
# ---------------------------------------------------------------------------

@app.get("/api/submit/deployed-apps", dependencies=[Depends(verify_api_key)])
def get_deployed_apps():
    """提交中心：列出已上架的功能页（含预览 URL + 当前广告配置）。

    站点未部署（无 telegram.json）→ items 空。每项附 resolve 后的广告配置，
    供后台展示开关/时长当前值。
    """
    from core.publisher.deployed_apps import list_deployed_features
    from core.publisher.ad_config import load_ad_config, resolve_ad

    features = list_deployed_features(TELEGRAM_AUTH_PATH, FEATURES_REGISTRY_PATH)
    cfg = load_ad_config(AD_CONFIG_PATH)
    items = [{**f, "ad": resolve_ad(cfg, f["route"])} for f in features]
    return {"items": items, "total": len(items)}


@app.post("/api/submit/ad-config", dependencies=[Depends(verify_api_key)])
def update_ad_config(req: AdConfigRequest):
    """提交中心：更新某功能页广告闸门（上架/下架 + 时长）。返回该 route 最新配置。"""
    from core.publisher.ad_config import load_ad_config, set_ad, save_ad_config, resolve_ad

    if req.ad_enabled is None and req.ad_seconds is None:
        return {"ok": False, "error": {"code": "NO_CHANGE", "message": "未提供可更新字段"}}
    cfg = load_ad_config(AD_CONFIG_PATH)
    cfg = set_ad(cfg, req.route, enabled=req.ad_enabled, seconds=req.ad_seconds)
    save_ad_config(AD_CONFIG_PATH, cfg)
    return {"ok": True, "route": req.route, "ad": resolve_ad(cfg, req.route)}


@app.get("/api/tg/ad-config")
def get_tg_ad_config(route: Optional[str] = Query(default=None)):
    """TG 站运行时读广告配置（public 免鉴权，跨域被合集站调用）。

    权限边界同 /api/generation/*：生成产物/合集站不持有 DASHBOARD_API_KEY，
    此只读接口不挂鉴权，且不涉及任何密钥。
    传 route → 返回该页 resolve 后的 {ad_enabled, ad_seconds}；不传 → 返回整份配置。
    """
    from core.publisher.ad_config import load_ad_config, resolve_ad

    cfg = load_ad_config(AD_CONFIG_PATH)
    if route:
        return {"ok": True, "route": route, "ad": resolve_ad(cfg, route)}
    return {"ok": True, "config": cfg}


@app.post("/api/submit/ad-video", dependencies=[Depends(verify_api_key)])
async def upload_ad_video(route: str = Form(...), video: UploadFile = File(...)):
    """提交中心：为某功能页上传广告视频（替换下载闸门的倒计时黑屏）。

    校验类型(mp4/webm)+大小(50MB)，存 data/ad-videos/<slug>.<ext>，
    把 video_url 写入 ad-config 该 route。返回新 video_url。
    """
    from core.publisher.ad_config import load_ad_config, set_ad, save_ad_config, route_to_slug

    content_type = (video.content_type or "").lower()
    ext = _ALLOWED_VIDEO_MIME.get(content_type)
    if not ext:
        return {"ok": False, "error": {"code": "VALIDATION_ERROR", "message": "仅支持 MP4 / WebM 视频"}}
    data = await video.read()
    if not data:
        return {"ok": False, "error": {"code": "VALIDATION_ERROR", "message": "视频为空"}}
    if len(data) > MAX_AD_VIDEO_BYTES:
        return {"ok": False, "error": {"code": "VALIDATION_ERROR", "message": "视频过大（上限 50MB）"}}

    slug = route_to_slug(route)
    AD_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    # 同一 route 换格式时清掉旧扩展名文件，避免残留。
    for old in AD_VIDEOS_DIR.glob(f"{slug}.*"):
        try:
            old.unlink()
        except OSError:
            pass
    filename = f"{slug}{ext}"
    (AD_VIDEOS_DIR / filename).write_bytes(data)

    video_url = f"/api/tg/ad-video/{filename}"
    cfg = load_ad_config(AD_CONFIG_PATH)
    cfg = set_ad(cfg, route, video_url=video_url)
    save_ad_config(AD_CONFIG_PATH, cfg)
    return {"ok": True, "route": route, "video_url": video_url}


@app.delete("/api/submit/ad-video", dependencies=[Depends(verify_api_key)])
def delete_ad_video(route: str = Query(...)):
    """提交中心：删除某功能页广告视频（文件 + 清 config video_url）。退回倒计时黑屏。"""
    from core.publisher.ad_config import load_ad_config, set_ad, save_ad_config, route_to_slug

    slug = route_to_slug(route)
    if AD_VIDEOS_DIR.exists():
        for f in AD_VIDEOS_DIR.glob(f"{slug}.*"):
            try:
                f.unlink()
            except OSError:
                pass
    cfg = load_ad_config(AD_CONFIG_PATH)
    cfg = set_ad(cfg, route, video_url="")
    save_ad_config(AD_CONFIG_PATH, cfg)
    return {"ok": True, "route": route, "video_url": ""}


@app.get("/api/tg/ad-video/{filename}")
def get_ad_video(filename: str):
    """public：返回广告视频文件，供 TG 站 <video> 跨域播放。

    安全：filename 白名单 [\\w.-]+ 且解析后必须落在 AD_VIDEOS_DIR 内，防目录穿越。
    """
    from fastapi.responses import FileResponse
    import re as _re

    if not _re.fullmatch(r"[A-Za-z0-9_.-]+", filename or ""):
        raise HTTPException(404, "not found")
    target = (AD_VIDEOS_DIR / filename).resolve()
    try:
        target.relative_to(AD_VIDEOS_DIR.resolve())
    except ValueError:
        raise HTTPException(404, "not found")
    if not target.is_file():
        raise HTTPException(404, "not found")
    media = "video/webm" if filename.endswith(".webm") else "video/mp4"
    return FileResponse(str(target), media_type=media)


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
        # 建议客户端等待整窗后再重试，避免快重试把限流窗口持续打满（自锁死）。
        "retry_after": GENERATION_RATE_WINDOW,
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


MAX_IMAGE_UPLOAD_BYTES = int(os.environ.get("MAX_IMAGE_UPLOAD_BYTES", str(12 * 1024 * 1024)))
_ALLOWED_IMAGE_MIME = {"image/png", "image/jpeg", "image/jpg", "image/webp"}


@app.post("/api/generation/image-edit")
async def edit_image_endpoint(
    request: Request,
    image: UploadFile = File(...),
    prompt: str = Form(""),
    task: str = Form("background_remove"),
):
    """图像编辑 runtime 接口（public）：接收上传图，做背景去除等 image-to-image。

    HTTP adapter：调 core.integrations.image_generation.edit_image。
    不透传 provider key / 原始错误。task=background_remove 时用内置去背 prompt。
    """
    if _rate_limited(request):
        return _RATE_LIMITED_RESPONSE

    from core.integrations.image_generation import (
        ImageGenerationError,
        ERR_FAILED,
        edit_image,
        BG_REMOVE_PROMPT,
        WATERMARK_REMOVE_PROMPT,
    )

    content_type = (image.content_type or "").lower()
    if content_type not in _ALLOWED_IMAGE_MIME:
        return {"ok": False, "error": {"code": "VALIDATION_ERROR", "message": "仅支持 PNG / JPG / WebP 图片"}}

    data = await image.read()
    if not data:
        return {"ok": False, "error": {"code": "VALIDATION_ERROR", "message": "图片为空"}}
    if len(data) > MAX_IMAGE_UPLOAD_BYTES:
        return {"ok": False, "error": {"code": "VALIDATION_ERROR", "message": "图片过大（上限 12MB）"}}

    # task 决定内置 prompt：未显式传 prompt 时按 task 选择，名副其实。
    edit_prompt = (prompt or "").strip()
    if task == "watermark_remove" and not edit_prompt:
        edit_prompt = WATERMARK_REMOVE_PROMPT
    elif task == "background_remove" or not edit_prompt:
        edit_prompt = BG_REMOVE_PROMPT
    if len(edit_prompt) > MAX_PROMPT_LEN:
        return {"ok": False, "error": {"code": "VALIDATION_ERROR", "message": "指令过长"}}

    try:
        result = edit_image(
            data, edit_prompt,
            filename=image.filename or "image.png",
            mime_type=content_type,
        )
    except ImageGenerationError as e:
        retryable = e.code in {"IMAGE_GENERATION_TIMEOUT", "IMAGE_GENERATION_PROVIDER_FAILED"}
        return {"ok": False, "error": {"code": e.code, "message": e.message, "retryable": retryable}}
    except Exception:
        return {"ok": False, "error": {"code": ERR_FAILED, "message": "图片处理失败，请稍后重试", "retryable": True}}

    import time as _t
    _edit_labels = {
        "background_remove": ("背景去除", "已移除背景"),
        "watermark_remove": ("去水印", "已去除水印"),
    }
    _title, _caption = _edit_labels.get(task, ("图片处理", "处理完成"))
    return {
        "ok": True,
        "result": {
            "preview_type": "image",
            "title": _title,
            "caption": _caption,
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
# SECTION: Send generated image to Telegram chat（可存相册）
# ---------------------------------------------------------------------------

# initData 新鲜度上限：超过则视为过期，拒绝（防重放）。
INIT_DATA_MAX_AGE = 24 * 3600


def verify_telegram_init_data(init_data: str, bot_token: str) -> Optional[dict]:
    """校验 Telegram WebApp initData 并返回解析出的 user dict（含 id）。

    标准算法：secret = HMAC_SHA256("WebAppData", bot_token)；
    比对 HMAC_SHA256(secret, data_check_string) 与 initData 中的 hash。
    校验失败 / 过期 / 无 user 返回 None。绝不信任前端直接传来的 user。
    """
    import hashlib
    from urllib.parse import parse_qsl

    if not init_data or not bot_token:
        return None
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True)
    except Exception:
        return None
    data = dict(pairs)
    received_hash = data.pop("hash", "")
    if not received_hash:
        return None

    # data_check_string：除 hash 外所有字段按 key 排序，以 \n 连接。
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc_hash, received_hash):
        return None

    # 新鲜度：auth_date 不能太旧。
    try:
        auth_date = int(data.get("auth_date", "0"))
        if auth_date <= 0 or (_time.time() - auth_date) > INIT_DATA_MAX_AGE:
            return None
    except (ValueError, TypeError):
        return None

    # 取 user（initData 里 user 是 JSON 串）。
    try:
        user = json.loads(data.get("user", ""))
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(user, dict) or "id" not in user:
        return None
    return user


# data URI base64 体积上限（对齐 12MB 原图 → base64 膨胀约 4/3）。
MAX_SEND_IMAGE_B64 = 17 * 1024 * 1024


@app.post("/api/generation/send-to-chat")
def send_to_chat_endpoint(req: SendToChatRequest, request: Request):
    """把生成图发到用户的 Telegram 聊天（public runtime 接口，不挂 dashboard 鉴权）。

    安全：用 bot token 校验 initData 取 chat_id，前端无法把图发给任意用户。
    image_src 为 data URI → 解码后 multipart 上传；为 http(s) → 作为 photo URL 直传。
    """
    if _rate_limited(request):
        return _RATE_LIMITED_RESPONSE

    if not TELEGRAM_BOT_TOKEN:
        return {"ok": False, "error": {"code": "NOT_CONFIGURED", "message": "发送服务暂未开启"}}

    user = verify_telegram_init_data(req.init_data, TELEGRAM_BOT_TOKEN)
    if not user:
        return {"ok": False, "error": {"code": "INVALID_INIT_DATA", "message": "身份校验失败，请在 Telegram 中打开"}}

    chat_id = user["id"]
    src = (req.image_src or "").strip()
    if not src:
        return {"ok": False, "error": {"code": "VALIDATION_ERROR", "message": "没有可发送的图片"}}
    caption = (req.caption or "")[:1024]

    import httpx
    api_base = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"

    try:
        if src.startswith("data:"):
            # data:[<mime>][;base64],<data> → 解码为字节走 multipart。
            import base64
            try:
                header, b64 = src.split(",", 1)
            except ValueError:
                return {"ok": False, "error": {"code": "VALIDATION_ERROR", "message": "图片格式不支持"}}
            if len(b64) > MAX_SEND_IMAGE_B64:
                return {"ok": False, "error": {"code": "VALIDATION_ERROR", "message": "图片过大"}}
            try:
                photo_bytes = base64.b64decode(b64)
            except Exception:
                return {"ok": False, "error": {"code": "VALIDATION_ERROR", "message": "图片解码失败"}}
            with httpx.Client(timeout=30) as client:
                resp = client.post(
                    api_base,
                    data={"chat_id": str(chat_id), "caption": caption},
                    files={"photo": ("image.png", photo_bytes, "image/png")},
                )
        elif src.startswith("http://") or src.startswith("https://"):
            with httpx.Client(timeout=30) as client:
                resp = client.post(
                    api_base,
                    data={"chat_id": str(chat_id), "caption": caption, "photo": src},
                )
        else:
            return {"ok": False, "error": {"code": "VALIDATION_ERROR", "message": "图片地址不支持"}}
    except Exception:
        return {"ok": False, "error": {"code": "SEND_FAILED", "message": "发送失败，请稍后再试", "retryable": True}}

    # 解析 Telegram 返回。
    try:
        body = resp.json()
    except Exception:
        body = {}
    if resp.status_code == 200 and body.get("ok"):
        return {"ok": True}
    # 用户没和 bot 对话过 / 拉黑：403。给可操作的友好提示。
    if resp.status_code == 403:
        return {"ok": False, "error": {"code": "BOT_BLOCKED", "message": "请先在 Bot 中发送任意消息后重试"}}
    return {"ok": False, "error": {"code": "SEND_FAILED", "message": "发送失败，请稍后再试", "retryable": True}}


# ---------------------------------------------------------------------------
# SECTION: Zip Download
# ---------------------------------------------------------------------------

@app.get("/api/jobs/{job_id}/download", dependencies=[Depends(verify_api_key)])
def download_job(job_id: str, target: str = "all"):
    """Download job artifacts as a zip file.

    target:
      all     -> entire job directory (default)
      miniapp -> generated/miniapp source tree (小程序源码)
      dist    -> generated/miniapp/dist build output (构建产物)
    """
    import zipfile
    import tempfile
    from fastapi.responses import FileResponse
    from starlette.background import BackgroundTask

    MAX_ZIP_SIZE = 100 * 1024 * 1024  # 100MB

    job_dir = OUTPUTS_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(404, "Job not found")

    # Resolve which subtree to zip; every root is validated to stay under job_dir.
    targets = {
        "all": (job_dir, f"miniapp-factory-{job_id}.zip"),
        "miniapp": (job_dir / "generated" / "miniapp", f"miniapp-source-{job_id}.zip"),
        "dist": (job_dir / "generated" / "miniapp" / "dist", f"miniapp-dist-{job_id}.zip"),
    }
    if target not in targets:
        raise HTTPException(400, f"Invalid target: {target}")
    root_dir, download_name = targets[target]

    # Security: resolved root must stay within job_dir.
    try:
        root_dir.resolve().relative_to(job_dir.resolve())
    except ValueError:
        raise HTTPException(403, "Access denied")
    if not root_dir.exists():
        raise HTTPException(404, f"Nothing to download for target: {target}")

    # Collect files and enforce size cap
    total_size = 0
    files_to_zip = []
    for f in root_dir.rglob("*"):
        if f.is_file() and "node_modules" not in str(f):
            total_size += f.stat().st_size
            if total_size > MAX_ZIP_SIZE:
                raise HTTPException(413, "Job artifacts exceed maximum download size (100MB)")
            files_to_zip.append(f)
    if not files_to_zip:
        raise HTTPException(404, f"Nothing to download for target: {target}")

    # Create zip in temp directory
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp.close()

    with zipfile.ZipFile(tmp.name, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in files_to_zip:
            arcname = str(f.relative_to(root_dir))
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
        filename=download_name,
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



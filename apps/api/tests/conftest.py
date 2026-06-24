"""apps/api 测试共享 fixtures。

针对 apps.api.main：开启鉴权、隔离数据目录、清理全局状态。
"""

import importlib
import sys
from pathlib import Path

import pytest

# repo 根加入 path，确保 import apps.api.main / core.* 可用
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def server_client(monkeypatch, tmp_path):
    """Return (TestClient, api_module) with auth enabled and isolated data dirs.

    真实 DATA_DIR 不受影响：REAL_INPUTS_DIR / OUTPUTS_DIR 重定向到 tmp。
    """
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DASHBOARD_API_KEY", "secret123")

    # 重新导入，使模块级 env 读取（DASHBOARD_API_KEY）生效
    sys.modules.pop("apps.api.main", None)
    import apps.api.main as api
    importlib.reload(api)

    api.REAL_INPUTS_DIR = tmp_path / "inputs" / "real"
    api.OUTPUTS_DIR = tmp_path / "outputs"
    api.REAL_INPUTS_DIR.mkdir(parents=True, exist_ok=True)
    api.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    # 隔离平台目录，避免依赖真实 data/platform-auth、data/platforms
    api.PLATFORM_AUTH_DIR = tmp_path / "platform-auth"
    api.PLATFORMS_DIR = tmp_path / "platforms"
    api.PLATFORM_AUTH_DIR.mkdir(parents=True, exist_ok=True)
    api.PLATFORMS_DIR.mkdir(parents=True, exist_ok=True)
    # 隔离任务库，避免污染真实 data/runtime/tasks.sqlite3
    api.TASK_DB_PATH = str(tmp_path / "tasks.sqlite3")
    api._task_store_instance = None

    from fastapi.testclient import TestClient

    yield TestClient(api.app), api

    # Teardown: reset global state
    api.pipeline_process = None
    api.pipeline_job_id = None
    api.pipeline_logs.clear()
    api.ws_clients.clear()


@pytest.fixture
def auth_headers():
    return {"X-API-Key": "secret123"}

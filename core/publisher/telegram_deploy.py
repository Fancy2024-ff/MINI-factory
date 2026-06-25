"""
Telegram Mini App 全自动部署脚本。

流程：
1. 读取 PRD 提取 app 信息
2. 渲染 H5 纯 HTML 模板
3. 调用 Cloudflare Pages API 上传
4. 调用 Telegram Bot API 设置 Menu Button
5. 输出 deploy-status.json
"""

import os
import sys
import json
import time
import hashlib
import base64
from pathlib import Path
from datetime import datetime

import httpx

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = SCRIPT_DIR / "templates" / "telegram-webapp"
DATA_DIR = PROJECT_ROOT / "data"

# ---------------------------------------------------------------------------
# Config (from env)
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "")
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "")
CLOUDFLARE_PROJECT_NAME = os.getenv("CLOUDFLARE_PROJECT_NAME", "miniforge-app")
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
# Production branch of the Pages project; deploying to it updates the canonical
# <project>.pages.dev domain (the one the TG menu button points to).
CLOUDFLARE_PAGES_BRANCH = os.getenv("CLOUDFLARE_PAGES_BRANCH", "main")

# LLM config for the webapp frontend (legacy text-app template)
WEBAPP_LLM_BASE_URL = os.getenv("WEBAPP_LLM_BASE_URL", "https://api.deepseek.com")
WEBAPP_LLM_API_KEY = os.getenv("WEBAPP_LLM_API_KEY", "")
WEBAPP_LLM_MODEL = os.getenv("WEBAPP_LLM_MODEL", "deepseek-chat")

# Image app: the WebApp calls OUR backend image endpoint (provider key stays on
# the server, never baked into the public page). Defaults to the public API base.
WEBAPP_BACKEND_URL = os.getenv("WEBAPP_BACKEND_URL", os.getenv("GENERATED_APP_API_BASE", ""))
# 部署成出图 WebApp 还是文本 WebApp。默认出图。
TELEGRAM_WEBAPP_KIND = os.getenv("TELEGRAM_WEBAPP_KIND", "image")


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

DEFAULT_ICONS = {
    "写作": "✍️", "翻译": "🌐", "摘要": "📋", "阅读": "📖",
    "工具": "🛠️", "效率": "⚡", "学习": "📚", "健康": "💊",
    "AI": "🤖", "默认": "✨",
}


def pick_icon(app_name: str, features: list[str]) -> str:
    """Pick an emoji icon based on app name/features."""
    text = app_name + " ".join(features)
    for keyword, icon in DEFAULT_ICONS.items():
        if keyword in text:
            return icon
    return DEFAULT_ICONS["默认"]


def build_system_prompt(app_name: str, features: list[str]) -> str:
    """Build a system prompt for the LLM based on app features."""
    features_text = "、".join(features) if features else "文本处理"
    return (
        f"你是{app_name}的 AI 助手，支持以下功能：{features_text}。"
        f"请严格按照以下 JSON 格式返回结果，不要返回任何其他内容：\n"
        f'{{"corrected": "处理后的完整文本", "notes": ["说明1", "说明2"]}}\n'
        f"如果无需修改，notes 返回空数组，corrected 返回原文。"
    )


def render_template(app_name: str, features: list[str], description: str) -> str:
    """Render the H5 HTML template with app-specific content."""
    template_path = TEMPLATE_DIR / "index.html"
    html = template_path.read_text(encoding="utf-8")

    icon = pick_icon(app_name, features)
    subtitle = description[:40] if description else "AI 智能助手"
    placeholder = f"在这里输入需要处理的文本..."
    system_prompt = build_system_prompt(app_name, features)

    # Escape for JS string embedding
    system_prompt_escaped = system_prompt.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")

    replacements = {
        "{{APP_NAME}}": app_name,
        "{{APP_ICON}}": icon,
        "{{APP_SUBTITLE}}": subtitle,
        "{{INPUT_PLACEHOLDER}}": placeholder,
        "{{LLM_MODEL}}": WEBAPP_LLM_MODEL,
        "{{SYSTEM_PROMPT}}": system_prompt_escaped,
    }

    for key, value in replacements.items():
        html = html.replace(key, value)

    return html


def render_image_template(app_name: str, features: list[str], description: str) -> str:
    """Render the image-generation H5 template.

    The WebApp calls our own backend (`WEBAPP_BACKEND_URL` + /api/generation/image),
    so NO provider key is baked into the public page. Frontend only sends a prompt;
    failures are retried silently on the client and never shown to the user.
    """
    template_path = TEMPLATE_DIR / "image.html"
    html = template_path.read_text(encoding="utf-8")

    icon = pick_icon(app_name, features)
    subtitle = (description[:40] if description else "AI 图片生成") or "AI 图片生成"
    placeholder = "例如：一只戴墨镜的柴犬，赛博朋克风格"

    replacements = {
        "{{APP_NAME}}": app_name,
        "{{APP_ICON}}": icon,
        "{{APP_SUBTITLE}}": subtitle,
        "{{INPUT_PLACEHOLDER}}": placeholder,
        "{{API_BASE}}": WEBAPP_BACKEND_URL.rstrip("/"),
        "{{TEMPLATE_ID}}": "ai-image",
        "{{STYLE}}": "",
    }
    for key, value in replacements.items():
        html = html.replace(key, value)
    return html


# ---------------------------------------------------------------------------
# Cloudflare Pages deployment
# ---------------------------------------------------------------------------

def get_cloudflare_account_id() -> str:
    """Auto-detect Cloudflare account ID if not set."""
    if CLOUDFLARE_ACCOUNT_ID:
        return CLOUDFLARE_ACCOUNT_ID
    resp = httpx.get(
        "https://api.cloudflare.com/client/v4/accounts",
        headers={"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}"},
        timeout=15,
    )
    resp.raise_for_status()
    accounts = resp.json().get("result", [])
    if not accounts:
        raise RuntimeError("No Cloudflare accounts found for this token")
    return accounts[0]["id"]


def deploy_to_cloudflare(html_content: str) -> str:
    """
    Deploy HTML + Pages Functions to Cloudflare Pages using wrangler CLI.
    Returns the production URL.

    部署目录结构：
        <tmpdir>/index.html              静态页（无任何密钥）
        <tmpdir>/functions/api/chat.js   LLM 代理（密钥经服务端 secret 读取）
    """
    import shutil
    import subprocess
    import tempfile

    # Resolve the npx executable. On Windows the launcher is `npx.cmd`, which
    # subprocess cannot find by the bare name `npx` without shell=True. Fall
    # back to the plain name so non-Windows platforms are unaffected.
    npx = shutil.which("npx") or shutil.which("npx.cmd") or "npx"

    # Write HTML + copy Pages Functions into a temp directory
    with tempfile.TemporaryDirectory() as tmpdir:
        index_path = Path(tmpdir) / "index.html"
        index_path.write_text(html_content, encoding="utf-8")

        # 复制 functions/ 目录（Pages Functions：functions/api/chat.js -> /api/chat）
        functions_src = TEMPLATE_DIR / "functions"
        if functions_src.exists():
            shutil.copytree(functions_src, Path(tmpdir) / "functions")

        # Run wrangler deploy
        env = os.environ.copy()
        env["CLOUDFLARE_API_TOKEN"] = CLOUDFLARE_API_TOKEN
        if CLOUDFLARE_ACCOUNT_ID:
            env["CLOUDFLARE_ACCOUNT_ID"] = CLOUDFLARE_ACCOUNT_ID

        # Deploy to the project's PRODUCTION branch so the canonical domain
        # (<project>.pages.dev) is updated. Without --branch, wrangler uses the
        # current git branch name; any non-production branch lands on a preview
        # URL and the menu-button domain keeps serving the old content.
        cmd = [npx, "wrangler", "pages", "deploy", tmpdir,
             "--project-name", CLOUDFLARE_PROJECT_NAME,
             "--branch", CLOUDFLARE_PAGES_BRANCH,
             "--commit-dirty=true"]

        result = subprocess.run(
            cmd,
            capture_output=True, text=True, env=env, timeout=120,
            encoding="utf-8", errors="replace",
        )

        if result.returncode != 0:
            raise RuntimeError(f"wrangler deploy failed: {result.stderr or result.stdout}")

    production_url = f"https://{CLOUDFLARE_PROJECT_NAME}.pages.dev"
    print(f"  [Cloudflare] Production: {production_url}")

    return production_url


def put_cloudflare_secrets() -> None:
    """把 LLM key / base url 写入 Cloudflare Pages 服务端 secret（非交互，stdin 传值）。

    secret 仅存于 Cloudflare 服务端，供 functions/api/chat.js 读取，不进入下发的 HTML。
    """
    import subprocess

    secrets = {
        "LLM_API_KEY": WEBAPP_LLM_API_KEY,
        "LLM_BASE_URL": WEBAPP_LLM_BASE_URL,
    }
    env = os.environ.copy()
    env["CLOUDFLARE_API_TOKEN"] = CLOUDFLARE_API_TOKEN
    if CLOUDFLARE_ACCOUNT_ID:
        env["CLOUDFLARE_ACCOUNT_ID"] = CLOUDFLARE_ACCOUNT_ID

    for name, value in secrets.items():
        cmd = ["npx", "wrangler", "pages", "secret", "put", name,
               "--project-name", CLOUDFLARE_PROJECT_NAME]
        result = subprocess.run(
            cmd,
            input=value + "\n",
            capture_output=True, text=True, env=env, timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(f"wrangler secret put {name} failed: {result.stderr}")
        print(f"  [Cloudflare] secret set: {name}")


# ---------------------------------------------------------------------------
# Telegram Bot API
# ---------------------------------------------------------------------------

def setup_telegram_bot(webapp_url: str, app_name: str) -> dict:
    """Configure Telegram bot with Web App menu button."""
    base = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

    # Set menu button
    resp = httpx.post(
        f"{base}/setChatMenuButton",
        json={
            "menu_button": {
                "type": "web_app",
                "text": app_name[:16],  # Telegram limit
                "web_app": {"url": webapp_url},
            }
        },
        timeout=10,
    )
    resp.raise_for_status()
    menu_ok = resp.json().get("ok", False)

    # Set bot description
    short_desc = f"{app_name} - Telegram Mini App"
    httpx.post(
        f"{base}/setMyShortDescription",
        json={"short_description": short_desc},
        timeout=10,
    )

    bot_link = f"https://t.me/{TELEGRAM_BOT_USERNAME}"

    print(f"  [Telegram] Menu button set: {menu_ok}")
    print(f"  [Telegram] Bot link: {bot_link}")

    return {
        "menu_button_set": menu_ok,
        "bot_link": bot_link,
        "webapp_url": webapp_url,
    }


# ---------------------------------------------------------------------------
# Main deploy function
# ---------------------------------------------------------------------------

def deploy_telegram(job_id: str, output_dir: Path, app_info: dict, opportunity: dict) -> dict:
    """
    Full automatic Telegram deployment.

    Args:
        job_id: Pipeline job ID
        output_dir: Path to job output directory
        app_info: Best app candidate dict
        opportunity: Opportunity analysis dict

    Returns:
        Deploy status dict
    """
    print(f"\n  [TG Deploy] Starting automatic deployment...")

    is_image = TELEGRAM_WEBAPP_KIND == "image"

    # Validate config
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not CLOUDFLARE_API_TOKEN:
        missing.append("CLOUDFLARE_API_TOKEN")
    if is_image:
        # Image WebApp calls our backend; needs the public backend URL, not an LLM key.
        if not WEBAPP_BACKEND_URL:
            missing.append("WEBAPP_BACKEND_URL")
    else:
        if not WEBAPP_LLM_API_KEY:
            missing.append("WEBAPP_LLM_API_KEY")

    if missing:
        return {
            "status": "skipped",
            "reason": f"Missing config: {', '.join(missing)}",
            "automated": False,
        }

    # Extract app info
    app_name = app_info.get("name_cn", app_info.get("name", "AI 助手"))
    features = []

    # Try to get features from PRD
    prd_path = output_dir / "prd.json"
    if prd_path.exists():
        try:
            prd = json.loads(prd_path.read_text(encoding="utf-8"))
            features = [f.get("name", "") for f in prd.get("core_features", []) if f.get("name")]
        except Exception:
            pass

    if not features:
        features = app_info.get("features", ["文本处理"])

    description = app_info.get("description_cn", app_info.get("description", ""))

    # Step 1: Render template
    kind_label = "image" if is_image else "text"
    print(f"  [TG Deploy] Rendering {kind_label} template for: {app_name}")
    if is_image:
        html = render_image_template(app_name, features, description)
    else:
        html = render_template(app_name, features, description)

    # Step 2: Deploy to Cloudflare
    print(f"  [TG Deploy] Deploying to Cloudflare Pages...")
    try:
        webapp_url = deploy_to_cloudflare(html)
    except Exception as e:
        return {
            "status": "failed",
            "stage": "cloudflare_deploy",
            "error": str(e),
            "automated": True,
        }

    # Step 2b: 写入服务端 secret（仅文本 WebApp 需要）。
    # 文本 App 经 functions/api/chat.js 代理调 LLM，key 存 Cloudflare 服务端 secret，
    # 不进下发的 HTML。出图 App 调我们自己的后端，无需在此设置 LLM secret。
    if not is_image:
        print(f"  [TG Deploy] Setting Cloudflare server-side secrets...")
        try:
            put_cloudflare_secrets()
        except Exception as e:
            return {
                "status": "partial",
                "stage": "cloudflare_secrets",
                "error": str(e),
                "webapp_url": webapp_url,
                "automated": True,
            }

    # Step 3: Configure Telegram Bot
    print(f"  [TG Deploy] Configuring Telegram Bot...")
    try:
        tg_result = setup_telegram_bot(webapp_url, app_name)
    except Exception as e:
        return {
            "status": "partial",
            "stage": "telegram_config",
            "error": str(e),
            "webapp_url": webapp_url,
            "automated": True,
        }

    # Step 4: Save deploy status
    deploy_status = {
        "status": "deployed",
        "automated": True,
        "platform": "telegram",
        "job_id": job_id,
        "app_name": app_name,
        "webapp_url": webapp_url,
        "bot_link": tg_result["bot_link"],
        "bot_username": TELEGRAM_BOT_USERNAME,
        "deployed_at": datetime.now().isoformat(),
        "cloudflare_project": CLOUDFLARE_PROJECT_NAME,
        "llm_provider": WEBAPP_LLM_BASE_URL,
        "llm_model": WEBAPP_LLM_MODEL,
    }

    # Update platform-auth/telegram.json
    auth_file = DATA_DIR / "platform-auth" / "telegram.json"
    auth_file.parent.mkdir(parents=True, exist_ok=True)
    auth_file.write_text(json.dumps({
        "bot_token": TELEGRAM_BOT_TOKEN,
        "webapp_url": webapp_url,
        "bot_username": TELEGRAM_BOT_USERNAME,
        "deploy_target": "cloudflare",
        "deploy_url": webapp_url,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"  [TG Deploy] ✅ Deployed successfully!")
    print(f"  [TG Deploy] URL: {webapp_url}")
    print(f"  [TG Deploy] Bot: {tg_result['bot_link']}")

    return deploy_status


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run standalone: python core/publisher/telegram_deploy.py <job_id>"""
    # On Windows the console defaults to GBK and cannot encode emoji/UTF-8 in
    # status messages; force stdout/stderr to UTF-8 so prints never crash.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")

    # Reload env after dotenv
    globals().update({
        "TELEGRAM_BOT_TOKEN": os.getenv("TELEGRAM_BOT_TOKEN", ""),
        "TELEGRAM_BOT_USERNAME": os.getenv("TELEGRAM_BOT_USERNAME", ""),
        "CLOUDFLARE_API_TOKEN": os.getenv("CLOUDFLARE_API_TOKEN", ""),
        "CLOUDFLARE_PROJECT_NAME": os.getenv("CLOUDFLARE_PROJECT_NAME", "miniforge-app"),
        "CLOUDFLARE_ACCOUNT_ID": os.getenv("CLOUDFLARE_ACCOUNT_ID", ""),
        "CLOUDFLARE_PAGES_BRANCH": os.getenv("CLOUDFLARE_PAGES_BRANCH", "main"),
        "WEBAPP_LLM_BASE_URL": os.getenv("WEBAPP_LLM_BASE_URL", "https://api.deepseek.com"),
        "WEBAPP_LLM_API_KEY": os.getenv("WEBAPP_LLM_API_KEY", ""),
        "WEBAPP_LLM_MODEL": os.getenv("WEBAPP_LLM_MODEL", "deepseek-chat"),
        "WEBAPP_BACKEND_URL": os.getenv("WEBAPP_BACKEND_URL", os.getenv("GENERATED_APP_API_BASE", "")),
        "TELEGRAM_WEBAPP_KIND": os.getenv("TELEGRAM_WEBAPP_KIND", "image"),
    })

    if len(sys.argv) < 2:
        print("Usage: python core/publisher/telegram_deploy.py <job_id>")
        sys.exit(1)

    job_id = sys.argv[1]
    output_dir = DATA_DIR / "outputs" / job_id

    if not output_dir.exists():
        print(f"Error: output dir not found: {output_dir}")
        sys.exit(1)

    # Load app info from candidate.json
    candidate_file = output_dir / "candidate.json"
    if candidate_file.exists():
        app_info = json.loads(candidate_file.read_text(encoding="utf-8"))
    else:
        app_info = {"name": "AI Assistant", "name_cn": "AI 助手"}

    opportunity = {"target_platforms": ["telegram"]}

    result = deploy_telegram(job_id, output_dir, app_info, opportunity)
    print(json.dumps(result, ensure_ascii=False, indent=2))

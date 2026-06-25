"""telegram_deploy 测试：核心安全不变量 —— 渲染产物不得含任何密钥，
请求必须经同域代理 /api/chat，且代理函数文件存在。

防回归点：历史上模板把 LLM_API_KEY 明文注入 HTML，任何用户可从源码窃取。
现在改为经 Cloudflare Pages Function 服务端代理，key 不下发客户端。
"""

from __future__ import annotations

from pathlib import Path

import core.publisher.telegram_deploy as td


SECRET_SENTINEL = "sk-super-secret-key-должно-не-появиться-12345"


def _render(monkeypatch):
    # 即便配了 key/base，渲染产物里也不该出现 key（应只进服务端 secret）
    monkeypatch.setattr(td, "WEBAPP_LLM_API_KEY", SECRET_SENTINEL)
    monkeypatch.setattr(td, "WEBAPP_LLM_BASE_URL", "https://upstream.example.com")
    monkeypatch.setattr(td, "WEBAPP_LLM_MODEL", "test-model")
    return td.render_template(
        app_name="测试助手",
        features=["文本处理", "翻译"],
        description="一个测试用的 AI 助手",
    )


def test_rendered_html_has_no_api_key(monkeypatch):
    html = _render(monkeypatch)
    assert SECRET_SENTINEL not in html, "渲染产物中泄露了 API key"
    # 旧的明文注入占位符不应再被使用
    assert "{{LLM_API_KEY}}" not in html
    assert "{{LLM_BASE_URL}}" not in html
    # 也不应出现 Authorization Bearer 明文头（key 拼接的痕迹）
    assert "Bearer ' + CONFIG.apiKey" not in html
    assert "apiKey" not in html


def test_rendered_html_calls_same_origin_proxy(monkeypatch):
    html = _render(monkeypatch)
    # 前端必须打同域代理，而不是直连上游
    assert "/api/chat" in html
    assert "upstream.example.com" not in html
    # 仍应注入非敏感的 model / system prompt
    assert "test-model" in html


def test_proxy_function_file_exists():
    fn = td.TEMPLATE_DIR / "functions" / "api" / "chat.js"
    assert fn.exists(), "缺少 Pages Function 代理 functions/api/chat.js"
    src = fn.read_text(encoding="utf-8")
    # 代理从服务端环境读 key，而非硬编码
    assert "env.LLM_API_KEY" in src
    assert SECRET_SENTINEL not in src


def test_deploy_skips_when_config_missing(monkeypatch, tmp_path):
    # 缺 key 时应结构化 skip，不抛异常、不假装成功
    monkeypatch.setattr(td, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(td, "CLOUDFLARE_API_TOKEN", "")
    monkeypatch.setattr(td, "WEBAPP_LLM_API_KEY", "")
    result = td.deploy_telegram("job-x", tmp_path, {"name": "X"}, {})
    assert result["status"] == "skipped"
    assert result["automated"] is False
    assert "TELEGRAM_BOT_TOKEN" in result["reason"]

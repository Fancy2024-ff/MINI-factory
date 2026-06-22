"""core.platforms.telegram.api — Telegram Bot API 轻量 HTTP 封装。

为什么不引入 python-telegram-bot / aiogram：本仓库已有 httpx，Bot API 是纯 HTTP，
第一版只用到 getUpdates / sendMessage / sendPhoto / answerCallbackQuery 几个方法，
轻封装即可，避免引入大依赖。所有方法都走单一 _call()，测试可整体 mock，不打真实网络。

安全：token 只从 env 经 config 读取，绝不入日志/消息/测试。本模块不打印 token，
也不打印图片 URL / base64。
"""

from __future__ import annotations

from typing import Any

import httpx

API_ROOT = "https://api.telegram.org"


class TelegramAPIError(Exception):
    """Telegram API 调用失败（不含 token）。"""


class TelegramClient:
    """最小 Telegram Bot API 客户端。token 由调用方从 config 注入，不在此读 env。"""

    def __init__(self, token: str, timeout: int = 30):
        if not token:
            raise TelegramAPIError("TELEGRAM_BOT_TOKEN 未配置")
        self._token = token
        self._timeout = timeout

    def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{API_ROOT}/bot{self._token}/{method}"
        try:
            resp = httpx.post(url, json=payload, timeout=self._timeout)
        except httpx.HTTPError:
            # 不带 token / 不带 url 细节
            raise TelegramAPIError(f"Telegram API 请求失败: {method}")
        if resp.status_code >= 400:
            raise TelegramAPIError(f"Telegram API 返回错误: {method} ({resp.status_code})")
        try:
            data = resp.json()
        except Exception:
            raise TelegramAPIError(f"Telegram API 响应非法: {method}")
        if not data.get("ok"):
            raise TelegramAPIError(f"Telegram API 拒绝: {method}")
        return data.get("result", {})

    def get_updates(self, offset: int | None = None, timeout: int = 25) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        result = self._call("getUpdates", payload)
        return result if isinstance(result, list) else []

    def send_message(
        self,
        chat_id: int | str,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self._call("sendMessage", payload)

    def edit_message_text(
        self,
        chat_id: int | str,
        message_id: int,
        text: str,
    ) -> dict[str, Any]:
        """编辑既有消息文本（用于进度条推进）。"""
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }
        return self._call("editMessageText", payload)

    def delete_message(self, chat_id: int | str, message_id: int) -> dict[str, Any]:
        """删除既有消息（用于出图前移除进度条）。"""
        payload: dict[str, Any] = {"chat_id": chat_id, "message_id": message_id}
        return self._call("deleteMessage", payload)

    def send_photo_bytes(
        self,
        chat_id: int | str,
        photo: bytes,
        caption: str = "",
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """以 multipart 上传图片字节。base64 解码后的 bytes 由调用方传入。"""
        url = f"{API_ROOT}/bot{self._token}/sendPhoto"
        data: dict[str, Any] = {"chat_id": str(chat_id)}
        if caption:
            data["caption"] = caption
        if reply_markup is not None:
            import json as _json

            data["reply_markup"] = _json.dumps(reply_markup)
        files = {"photo": ("image.png", photo, "image/png")}
        try:
            resp = httpx.post(url, data=data, files=files, timeout=self._timeout)
        except httpx.HTTPError:
            raise TelegramAPIError("Telegram sendPhoto 请求失败")
        if resp.status_code >= 400:
            raise TelegramAPIError(f"Telegram sendPhoto 错误 ({resp.status_code})")
        try:
            body = resp.json()
        except Exception:
            raise TelegramAPIError("Telegram sendPhoto 响应非法")
        if not body.get("ok"):
            raise TelegramAPIError("Telegram sendPhoto 被拒绝")
        return body.get("result", {})

    def send_photo_url(
        self,
        chat_id: int | str,
        photo_url: str,
        caption: str = "",
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": chat_id, "photo": photo_url}
        if caption:
            payload["caption"] = caption
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self._call("sendPhoto", payload)

    def answer_callback_query(self, callback_query_id: str, text: str = "") -> dict[str, Any]:
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        return self._call("answerCallbackQuery", payload)

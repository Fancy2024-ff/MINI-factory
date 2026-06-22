"""core.platforms.telegram bot tests — 全程 mock，不打真实 Telegram / provider。"""

from __future__ import annotations

import base64

import pytest

from core.integrations.image_generation import ImageGenerationError
from core.platforms.telegram import bot as bot_mod


SECRET_TOKEN = "123:FAKE-DO-NOT-LEAK"
# 一段极小的有效 base64（解码为 4 字节），代表图片字节，绝非真实图片。
TINY_PNG_B64 = base64.b64encode(b"\x89PNG").decode()


class FakeClient:
    """记录调用的假 Telegram 客户端，不发真实网络请求。"""

    def __init__(self):
        self.messages = []  # (chat_id, text, reply_markup)
        self.photos_bytes = []  # (chat_id, photo_bytes, caption, reply_markup)
        self.photos_url = []  # (chat_id, url, caption, reply_markup)
        self.callbacks = []  # (cb_id, text)

    def send_message(self, chat_id, text, reply_markup=None):
        self.messages.append((chat_id, text, reply_markup))
        return {"message_id": 1}

    def send_photo_bytes(self, chat_id, photo, caption="", reply_markup=None):
        self.photos_bytes.append((chat_id, photo, caption, reply_markup))
        return {"message_id": 2}

    def send_photo_url(self, chat_id, photo_url, caption="", reply_markup=None):
        self.photos_url.append((chat_id, photo_url, caption, reply_markup))
        return {"message_id": 3}

    def answer_callback_query(self, callback_query_id, text=""):
        self.callbacks.append((callback_query_id, text))
        return {}


def _msg_update(text: str, chat_id: int = 555):
    return {"update_id": 1, "message": {"chat": {"id": chat_id}, "text": text}}


def _ok_base64(prompt, style="", aspect_ratio="1:1"):
    return {
        "provider": "test-provider",
        "status": "succeeded",
        "image_url": None,
        "image_base64": TINY_PNG_B64,
        "prompt": prompt,
        "metadata": {},
    }


def _ok_url(prompt, style="", aspect_ratio="1:1"):
    return {
        "provider": "test-provider",
        "status": "succeeded",
        "image_url": "https://img.example/secret-result.png",
        "image_base64": None,
        "prompt": prompt,
        "metadata": {},
    }


def test_start_command():
    c = FakeClient()
    bot_mod.handle_update(c, _msg_update("/start"))
    assert len(c.messages) == 1
    assert "欢迎" in c.messages[0][1]
    assert not c.photos_bytes and not c.photos_url


def test_help_command():
    c = FakeClient()
    bot_mod.handle_update(c, _msg_update("/help"))
    assert len(c.messages) == 1
    assert "示例" in c.messages[0][1]


def test_image_command_missing_prompt():
    c = FakeClient()
    bot_mod.handle_update(c, _msg_update("/image   "))
    assert len(c.messages) == 1
    assert c.messages[0][1] == bot_mod.EMPTY_PROMPT_HINT
    assert not c.photos_bytes


def test_image_command_generates_base64_photo():
    c = FakeClient()
    bot_mod.handle_update(c, _msg_update("/image 一只柴犬"), generate=_ok_base64)
    assert len(c.photos_bytes) == 1
    chat_id, photo, caption, markup = c.photos_bytes[0]
    assert chat_id == 555
    assert photo == b"\x89PNG"  # 已从 base64 解码为 bytes
    assert markup and "inline_keyboard" in markup  # 增长按钮存在


def test_plain_text_generates_photo():
    c = FakeClient()
    bot_mod.handle_update(c, _msg_update("海边日落 油画"), generate=_ok_base64)
    assert len(c.photos_bytes) == 1
    assert not c.messages  # 普通文本直接当 prompt，无多余提示


def test_image_url_path():
    c = FakeClient()
    bot_mod.handle_update(c, _msg_update("/image 雪山"), generate=_ok_url)
    assert len(c.photos_url) == 1
    assert c.photos_url[0][1] == "https://img.example/secret-result.png"


def test_prompt_too_long():
    c = FakeClient()
    long_prompt = "猫" * (bot_mod.MAX_PROMPT_LEN + 1)
    bot_mod.handle_update(c, _msg_update("/image " + long_prompt), generate=_ok_base64)
    assert len(c.messages) == 1
    assert c.messages[0][1] == bot_mod.TOO_LONG_HINT
    assert not c.photos_bytes


def test_provider_error_friendly():
    c = FakeClient()

    def fail(prompt, **kw):
        raise ImageGenerationError("IMAGE_GENERATION_PROVIDER_FAILED", "raw provider detail LEAK")

    bot_mod.handle_update(c, _msg_update("/image 猫"), generate=fail)
    assert len(c.messages) == 1
    assert c.messages[0][1] == bot_mod.PROVIDER_FAILED_HINT
    assert "raw provider detail" not in c.messages[0][1]


def test_not_configured_friendly():
    c = FakeClient()

    def fail(prompt, **kw):
        raise ImageGenerationError("IMAGE_GENERATION_NOT_CONFIGURED", "endpoint missing")

    bot_mod.handle_update(c, _msg_update("/image 猫"), generate=fail)
    assert c.messages[0][1] == bot_mod.NOT_CONFIGURED_HINT


def test_callback_help_button():
    c = FakeClient()
    update = {
        "update_id": 9,
        "callback_query": {
            "id": "cb1",
            "data": "help",
            "message": {"chat": {"id": 777}},
        },
    }
    bot_mod.handle_update(c, update)
    assert any("示例" in m[1] for m in c.messages)
    assert c.callbacks and c.callbacks[0][0] == "cb1"


def test_no_token_or_base64_leak_in_outputs():
    """回归：bot 产出（消息文本）不含 token / base64 原文 / 完整 URL。"""
    c = FakeClient()
    bot_mod.handle_update(c, _msg_update("/image 猫"), generate=_ok_base64)
    for chat_id, text, _ in c.messages:
        assert SECRET_TOKEN not in text
        assert TINY_PNG_B64 not in text
    # base64 只作为 bytes 进 sendPhoto，不进任何文本消息
    for _, _, caption, _ in c.photos_bytes:
        assert TINY_PNG_B64 not in caption
        assert SECRET_TOKEN not in caption


def test_client_requires_token():
    from core.platforms.telegram.api import TelegramClient, TelegramAPIError

    with pytest.raises(TelegramAPIError):
        TelegramClient("")

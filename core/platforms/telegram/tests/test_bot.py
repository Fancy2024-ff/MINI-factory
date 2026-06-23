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
        self.edits = []  # (chat_id, message_id, text)
        self.deletes = []  # (chat_id, message_id)
        self._next_message_id = 100

    def send_message(self, chat_id, text, reply_markup=None):
        self.messages.append((chat_id, text, reply_markup))
        self._next_message_id += 1
        return {"message_id": self._next_message_id}

    def edit_message_text(self, chat_id, message_id, text):
        self.edits.append((chat_id, message_id, text))
        return {"message_id": message_id}

    def delete_message(self, chat_id, message_id):
        self.deletes.append((chat_id, message_id))
        return {}

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
    # 普通文本直接当 prompt：唯一的消息是进度条，且生成完成后被删除
    assert len(c.messages) == 1
    assert "生成中" in c.messages[0][1]
    assert len(c.deletes) == 1  # 进度条已删


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
    # 失败时进度条被删除，最后一条消息是友好提示，且不泄漏 provider 原文
    assert c.deletes  # 进度条已删
    assert c.messages[-1][1] == bot_mod.PROVIDER_FAILED_HINT
    for _, text, _ in c.messages:
        assert "raw provider detail" not in text
    assert not c.photos_bytes


def test_not_configured_friendly():
    c = FakeClient()

    def fail(prompt, **kw):
        raise ImageGenerationError("IMAGE_GENERATION_NOT_CONFIGURED", "endpoint missing")

    bot_mod.handle_update(c, _msg_update("/image 猫"), generate=fail)
    assert c.messages[-1][1] == bot_mod.NOT_CONFIGURED_HINT
    assert c.deletes  # 进度条已删


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


# --- WebApp 联动 -----------------------------------------------------------

WEBAPP_URL = "https://example.org/tg"


def _find_buttons(markup):
    if not markup:
        return []
    return [btn for row in markup.get("inline_keyboard", []) for btn in row]


def test_start_has_webapp_button_when_url_set():
    c = FakeClient()
    bot_mod.handle_update(c, _msg_update("/start"), webapp_url=WEBAPP_URL)
    assert len(c.messages) == 1
    _, _, markup = c.messages[0]
    buttons = _find_buttons(markup)
    web_app_btns = [b for b in buttons if "web_app" in b]
    assert web_app_btns, "/start 应带 web_app 按钮"
    assert web_app_btns[0]["web_app"]["url"] == WEBAPP_URL


def test_start_degrades_without_webapp_url():
    c = FakeClient()
    # 显式空字符串：无 https url，按钮降级为 callback，不崩
    bot_mod.handle_update(c, _msg_update("/start"), webapp_url="")
    assert len(c.messages) == 1
    _, _, markup = c.messages[0]
    buttons = _find_buttons(markup)
    assert buttons, "降级时仍应有按钮"
    assert all("web_app" not in b for b in buttons), "无 url 时不应出现 web_app 按钮"
    assert any(b.get("callback_data") == "open_hint" for b in buttons)


def test_start_rejects_non_https_webapp_url():
    c = FakeClient()
    bot_mod.handle_update(c, _msg_update("/start"), webapp_url="http://insecure.example/tg")
    _, _, markup = c.messages[0]
    buttons = _find_buttons(markup)
    assert all("web_app" not in b for b in buttons), "非 https 不应作为 web_app 按钮"


def test_image_result_has_webapp_and_regen_buttons():
    c = FakeClient()
    bot_mod.handle_update(c, _msg_update("/image 猫"), generate=_ok_base64, webapp_url=WEBAPP_URL)
    assert len(c.photos_bytes) == 1
    _, _, _, markup = c.photos_bytes[0]
    buttons = _find_buttons(markup)
    assert any("web_app" in b for b in buttons), "结果按钮应含 WebApp 入口"
    assert any(b.get("callback_data") == "regen" for b in buttons), "结果按钮应含再生成"


def test_image_result_buttons_degrade_without_url():
    c = FakeClient()
    bot_mod.handle_update(c, _msg_update("/image 猫"), generate=_ok_base64, webapp_url="")
    _, _, _, markup = c.photos_bytes[0]
    buttons = _find_buttons(markup)
    assert all("web_app" not in b for b in buttons)
    assert any(b.get("callback_data") == "regen" for b in buttons)


# --- /avatar 命令 ----------------------------------------------------------

def test_avatar_command_missing_prompt():
    c = FakeClient()
    bot_mod.handle_update(c, _msg_update("/avatar   "))
    assert len(c.messages) == 1
    assert c.messages[0][1] == bot_mod.AVATAR_EMPTY_HINT
    assert not c.photos_bytes


def test_avatar_command_generates_base64_photo():
    captured = {}

    def gen(prompt, **kw):
        captured["prompt"] = prompt
        return _ok_base64(prompt, **kw)

    c = FakeClient()
    bot_mod.handle_update(c, _msg_update("/avatar 短发女生 简约时尚"), generate=gen)
    assert len(c.photos_bytes) == 1
    # 走 avatar adapter：出图 prompt 被改写为头像方向，而非原样透传
    assert "avatar" in captured["prompt"].lower()
    assert "短发女生 简约时尚" in captured["prompt"]


def test_avatar_command_provider_error_friendly():
    def fail(prompt, **kw):
        raise ImageGenerationError("IMAGE_GENERATION_PROVIDER_FAILED", "raw detail LEAK")

    c = FakeClient()
    bot_mod.handle_update(c, _msg_update("/avatar 一个人"), generate=fail)
    # 进度条已删除，最后一条消息是友好提示，不泄漏 provider 原文
    assert c.deletes
    assert c.messages[-1][1] == bot_mod.PROVIDER_FAILED_HINT
    for _, text, _ in c.messages:
        assert "raw detail" not in text
    assert not c.photos_bytes


def test_avatar_command_no_base64_or_key_leak():
    c = FakeClient()
    bot_mod.handle_update(c, _msg_update("/avatar 一个人"), generate=_ok_base64)
    for _, text, _ in c.messages:
        assert TINY_PNG_B64 not in text
        assert SECRET_TOKEN not in text
    for _, _, caption, _ in c.photos_bytes:
        assert TINY_PNG_B64 not in caption


# --- /sticker 命令 ---------------------------------------------------------

def test_sticker_command_missing_prompt():
    c = FakeClient()
    bot_mod.handle_update(c, _msg_update("/sticker   "))
    assert len(c.messages) == 1
    assert c.messages[0][1] == bot_mod.STICKER_EMPTY_HINT
    assert not c.photos_bytes


def test_sticker_command_generates_photo_via_adapter():
    captured = {}

    def gen(prompt, **kw):
        captured["prompt"] = prompt
        return _ok_base64(prompt, **kw)

    c = FakeClient()
    bot_mod.handle_update(c, _msg_update("/sticker 打工人 怼人专用"), generate=gen)
    assert len(c.photos_bytes) == 1
    # 走 sticker adapter：出图 prompt 含 sticker 方向词 + 原始主题
    assert "sticker" in captured["prompt"].lower()
    assert "打工人 怼人专用" in captured["prompt"]


# --- /pettalk 命令 ---------------------------------------------------------

def test_pettalk_command_missing_prompt():
    c = FakeClient()
    bot_mod.handle_update(c, _msg_update("/pettalk   "))
    assert len(c.messages) == 1
    assert c.messages[0][1] == bot_mod.PETTALK_EMPTY_HINT
    assert not c.photos_bytes


def test_pettalk_command_generates_photo_via_adapter():
    captured = {}

    def gen(prompt, **kw):
        captured["prompt"] = prompt
        return _ok_base64(prompt, **kw)

    c = FakeClient()
    bot_mod.handle_update(c, _msg_update("/pettalk 主人该喂饭啦"), generate=gen)
    assert len(c.photos_bytes) == 1
    # 走 pet-talk adapter：出图 prompt 含 pet 方向词 + 台词
    assert "pet" in captured["prompt"].lower()
    assert "主人该喂饭啦" in captured["prompt"]


# ── 进度条相关 ────────────────────────────────────────────────

def test_progress_message_sent_then_deleted_on_success():
    """成功出图：先发进度条消息，出图前删除该进度条。"""
    c = FakeClient()
    bot_mod.handle_update(c, _msg_update("/image 柴犬"), generate=_ok_base64)
    # 进度条消息发出（含进度条文案）
    assert len(c.messages) == 1
    progress_chat_id, progress_text, _ = c.messages[0]
    assert progress_chat_id == 555
    assert "生成中" in progress_text
    # 进度条在发图前被删除，且删的就是那条进度消息
    assert len(c.deletes) == 1
    assert c.deletes[0][0] == 555
    # 真实图片随后发出
    assert len(c.photos_bytes) == 1


def test_progress_advances_when_generation_is_slow():
    """生成耗时较长时，进度条会被编辑推进（百分比上升、封顶 90%）。"""
    import time

    def slow_generate(prompt, **kw):
        time.sleep(0.5)  # 给进度线程时间推进
        return _ok_base64(prompt)

    # 用极快的步进间隔让测试无需真等数秒
    c = FakeClient()
    bot_mod.handle_update(
        c, _msg_update("/image 慢图"), generate=slow_generate,
        progress_interval=0.05,
    )
    # 至少推进过一次（编辑过进度消息）
    assert c.edits, "进度条未被推进编辑"
    # 推进的都是同一条进度消息
    progress_msg_id = c.deletes[0][1]
    assert all(mid == progress_msg_id for _, mid, _ in c.edits)
    # 百分比封顶不超过 90（不谎报完成）
    for _, _, text in c.edits:
        import re
        m = re.search(r"(\d+)%", text)
        if m:
            assert int(m.group(1)) <= 90
    assert len(c.photos_bytes) == 1


def test_progress_thread_stops_after_generation():
    """主流程结束后，进度推进线程必须已终止（不泄漏线程）。"""
    import threading

    before = set(threading.enumerate())
    c = FakeClient()
    bot_mod.handle_update(
        c, _msg_update("/image 猫"), generate=_ok_base64, progress_interval=0.05,
    )
    # 给 daemon 线程一点退出余量
    import time
    time.sleep(0.2)
    after = set(threading.enumerate())
    leaked = [t for t in (after - before) if t.is_alive() and "tg-progress" in t.name]
    assert not leaked, f"进度线程泄漏: {leaked}"


def test_progress_edit_failure_does_not_break_generation():
    """进度条编辑失败（例如消息已被删）不能影响最终出图。"""
    c = FakeClient()

    def boom(chat_id, message_id, text):
        raise RuntimeError("edit failed")

    c.edit_message_text = boom  # 任何进度编辑都抛错
    bot_mod.handle_update(
        c, _msg_update("/image 猫"), generate=_ok_base64, progress_interval=0.05,
    )
    # 出图照常完成
    assert len(c.photos_bytes) == 1


def test_no_token_or_base64_leak_in_progress():
    """回归：进度条文案也不得含 token / base64。"""
    c = FakeClient()
    bot_mod.handle_update(c, _msg_update("/image 猫"), generate=_ok_base64,
                          progress_interval=0.05)
    for _, text, _ in c.messages:
        assert SECRET_TOKEN not in text and TINY_PNG_B64 not in text
    for _, _, text in c.edits:
        assert SECRET_TOKEN not in text and TINY_PNG_B64 not in text

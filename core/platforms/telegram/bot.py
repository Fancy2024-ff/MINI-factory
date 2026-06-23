"""core.platforms.telegram.bot — Telegram image AI bot（capability-domain）。

职责：把 Telegram 文本/命令转成 image generation capability 调用，再把结果发回。
- 复用 core.integrations.image_generation.generate_image（唯一 provider 真源）。
- provider key / telegram token 只从 core.runtime.config（env）读，绝不入消息/日志/测试。
- 不打印 base64 原文、不打印完整图片 URL。

启动：python -m core.platforms.telegram.bot
"""

from __future__ import annotations

import base64
import binascii
import logging
import threading
from typing import Any, Callable

from core.integrations.image_generation import ImageGenerationError, generate_image
from core.generator.template_generation import generate_template
from core.platforms.telegram.api import TelegramAPIError, TelegramClient

logger = logging.getLogger("telegram.bot")

MAX_PROMPT_LEN = 1000

# 进度条：provider 不回传真实进度，这里按经验时长「模拟推进」，封顶 90%，
# 真实出图成功才视作 100%（删进度条→发图）。每档之间 sleep PROGRESS_INTERVAL 秒。
PROGRESS_INTERVAL = 3.5
# (百分比, 已填格数/共5格) — 文案用方块条直观表达
PROGRESS_STEPS = [
    (15, 1),
    (35, 2),
    (55, 3),
    (75, 4),
    (90, 5),
]


def _progress_text(percent: int, filled: int) -> str:
    bar = "▰" * filled + "▱" * (5 - filled)
    return f"🎨 生成中 {bar} {percent}%"


def _initial_progress_text() -> str:
    percent, filled = PROGRESS_STEPS[0]
    return _progress_text(percent, filled)

START_TEXT = (
    "👋 欢迎使用 AI 图片生成 Bot！\n\n"
    "直接发一句描述，我就会生成图片，例如：\n"
    "  一只戴墨镜的柴犬，赛博朋克风格\n\n"
    "命令：\n"
    "  /image <描述>  生成图片\n"
    "  /avatar <人物描述>  生成 AI 头像\n"
    "  /sticker <表情主题>  生成表情包\n"
    "  /pettalk <宠物台词>  宠物说话预览（静态，视频预留）\n"
    "  /help  查看示例"
)

HELP_TEXT = (
    "🖼 用法示例：\n\n"
    "  /image 海边日落，油画风格\n"
    "  /avatar 25 岁短发女生，简约时尚，自信微笑\n"
    "  /sticker 打工人 怼人专用\n"
    "  /pettalk 主人，该喂饭啦！\n\n"
    "也可以直接发描述文字（不带命令）生成图片。\n"
    "注：/pettalk 当前生成静态预览图，真实说话视频为流程预留。\n"
    f"描述长度上限 {MAX_PROMPT_LEN} 字符。"
)

EMPTY_PROMPT_HINT = "请在命令后输入图片描述，例如：/image 一只戴帽子的猫"
AVATAR_EMPTY_HINT = "请在命令后输入人物描述，例如：/avatar 25 岁短发女生，简约时尚"
STICKER_EMPTY_HINT = "请在命令后输入表情主题，例如：/sticker 打工人 怼人专用"
PETTALK_EMPTY_HINT = "请在命令后输入宠物台词，例如：/pettalk 主人，该喂饭啦！"
NOT_CONFIGURED_HINT = "图片生成服务暂未配置，请稍后再试。"
PROVIDER_FAILED_HINT = "图片生成失败，请换个描述或稍后再试。"
TOO_LONG_HINT = f"描述太长啦，请控制在 {MAX_PROMPT_LEN} 字符以内。"
DECODE_FAILED_HINT = "图片生成结果异常，请稍后再试。"

# provider 错误码 -> 用户友好提示（不透传 provider 原文）
_NOT_CONFIGURED_CODES = {"IMAGE_GENERATION_NOT_CONFIGURED"}

# 模板命令分发表：(命令前缀, template_id, 空输入提示)。三命令同源走 generate_template。
_TEMPLATE_COMMANDS = (
    ("/avatar", "avatar-viral", AVATAR_EMPTY_HINT),
    ("/sticker", "sticker-viral", STICKER_EMPTY_HINT),
    ("/pettalk", "pet-talk-viral", PETTALK_EMPTY_HINT),
)


def _resolve_webapp_url(webapp_url: str | None) -> str:
    """显式传入优先；否则从 config（env）读。仅接受 https。"""
    if webapp_url is None:
        from core.runtime import config

        webapp_url = config.TELEGRAM_WEBAPP_URL
    webapp_url = (webapp_url or "").strip()
    return webapp_url if webapp_url.startswith("https://") else ""


def _open_button(webapp_url: str) -> dict[str, Any]:
    """构造「打开 MiniForge」按钮：有 https webapp url 用 web_app，否则降级文本回调。"""
    if webapp_url:
        return {"text": "🚀 打开 MiniForge", "web_app": {"url": webapp_url}}
    return {"text": "🚀 打开 MiniForge", "callback_data": "open_hint"}


def build_start_keyboard(webapp_url: str = "") -> dict[str, Any]:
    """/start 的按钮：打开 WebApp（或降级提示）。"""
    return {"inline_keyboard": [[_open_button(webapp_url)]]}


def build_growth_keyboard(webapp_url: str = "") -> dict[str, Any]:
    """返回图片后的增长 inline 按钮。第一版部分按钮为 callback skeleton。

    第一行加入 WebApp 入口（配置了 https url 时）与「再生成」。
    """
    rows: list[list[dict[str, Any]]] = [
        [
            _open_button(webapp_url),
            {"text": "🔄 再生成", "callback_data": "regen"},
        ],
        [
            {"text": "🎨 换风格", "callback_data": "restyle"},
            {"text": "✨ 生成同款", "callback_data": "variant"},
        ],
        [
            {"text": "❓ 帮助", "callback_data": "help"},
        ],
    ]
    return {"inline_keyboard": rows}


def extract_prompt(text: str) -> tuple[str, bool]:
    """从一条消息文本提取 prompt。

    返回 (prompt, is_command)。命令形如 /image xxx；/start /help 单独处理。
    """
    text = (text or "").strip()
    if text.startswith("/image"):
        return text[len("/image"):].strip(), True
    if text.startswith("/"):
        # 其它命令交给上层
        return "", True
    return text, False


def _friendly_error(err: ImageGenerationError) -> str:
    if err.code in _NOT_CONFIGURED_CODES:
        return NOT_CONFIGURED_HINT
    return PROVIDER_FAILED_HINT


def handle_update(
    client: TelegramClient,
    update: dict[str, Any],
    *,
    generate: Callable[..., dict[str, Any]] = generate_image,
    webapp_url: str | None = None,
    progress_interval: float = PROGRESS_INTERVAL,
) -> None:
    """处理单条 Telegram update。generate / webapp_url 可注入，便于测试 mock。
    progress_interval 控制进度条推进间隔（测试可调小以免真等数秒）。"""
    resolved_webapp = _resolve_webapp_url(webapp_url)
    # 回调按钮：第一版只确认，不重跑核心链路。
    callback = update.get("callback_query")
    if isinstance(callback, dict):
        _handle_callback(client, callback)
        return

    message = update.get("message") or update.get("edited_message")
    if not isinstance(message, dict):
        return
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return
    text = message.get("text") or ""

    # 命令分发
    stripped = text.strip()
    if stripped.startswith("/start"):
        client.send_message(chat_id, START_TEXT, reply_markup=build_start_keyboard(resolved_webapp))
        return
    if stripped.startswith("/help"):
        client.send_message(chat_id, HELP_TEXT)
        return
    # 三端同源的模板命令：/avatar /sticker /pettalk 统一走
    # core.generator.template_generation 的对应 adapter（与 WebApp / API 同一条链路），
    # 把统一返回的 result 适配成 _generate_and_reply 期望的扁平结构，复用进度条/发图。
    for cmd, template_id, empty_hint in _TEMPLATE_COMMANDS:
        if stripped.startswith(cmd):
            subject = stripped[len(cmd):].strip()
            if not subject:
                client.send_message(chat_id, empty_hint)
                return
            if len(subject) > MAX_PROMPT_LEN:
                client.send_message(chat_id, TOO_LONG_HINT)
                return

            def _tmpl_generate(_ignored: str, _tid: str = template_id, _subj: str = subject,
                               **_kw: Any) -> dict[str, Any]:
                out = generate_template(_tid, {"prompt": _subj}, generate=generate)
                return out.get("result", {})

            _generate_and_reply(client, chat_id, subject, _tmpl_generate, resolved_webapp, progress_interval)
            return

    prompt, is_command = extract_prompt(stripped)
    if is_command and not prompt:
        # /image 无参数，或未知命令
        if stripped.startswith("/image"):
            client.send_message(chat_id, EMPTY_PROMPT_HINT)
        else:
            client.send_message(chat_id, HELP_TEXT)
        return
    if not prompt:
        client.send_message(chat_id, EMPTY_PROMPT_HINT)
        return
    if len(prompt) > MAX_PROMPT_LEN:
        client.send_message(chat_id, TOO_LONG_HINT)
        return

    _generate_and_reply(client, chat_id, prompt, generate, resolved_webapp, progress_interval)


def _handle_callback(client: TelegramClient, callback: dict[str, Any]) -> None:
    data = callback.get("data") or ""
    cb_id = callback.get("id") or ""
    msg = callback.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    if data == "help" and chat_id is not None:
        client.send_message(chat_id, HELP_TEXT)
    elif data == "open_hint" and chat_id is not None:
        # WebApp URL 未配置时的降级提示
        client.send_message(chat_id, "MiniForge WebApp 暂未开放，可直接在这里发描述生成图片～")
    # 第一版：再生成/换风格/同款仅确认 skeleton，不重跑核心链路。
    if cb_id:
        try:
            client.answer_callback_query(cb_id, "收到，正在为你准备～")
        except TelegramAPIError:
            pass


def _run_progress(
    client: TelegramClient,
    chat_id: int | str,
    message_id: int,
    stop: threading.Event,
    interval: float,
) -> None:
    """后台推进进度条：依次编辑进度消息到 35/55/75/90%，到顶或被叫停即退出。

    任何编辑失败（消息已删/网络抖动）都静默跳过，绝不影响主出图流程。
    """
    for percent, filled in PROGRESS_STEPS[1:]:
        if stop.wait(interval):  # 被叫停则立即退出
            return
        try:
            client.edit_message_text(chat_id, message_id, _progress_text(percent, filled))
        except Exception:
            # 进度只是体验增强，失败不打断生成；不记录 provider/token 细节
            return


def _generate_and_reply(
    client: TelegramClient,
    chat_id: int | str,
    prompt: str,
    generate: Callable[..., dict[str, Any]],
    webapp_url: str = "",
    progress_interval: float = PROGRESS_INTERVAL,
) -> None:
    # 1. 先发进度条消息，拿到 message_id 供后续编辑/删除
    progress_message_id: int | None = None
    try:
        sent = client.send_message(chat_id, _initial_progress_text())
        progress_message_id = sent.get("message_id")
    except TelegramAPIError:
        progress_message_id = None  # 发不出进度条也不阻断生成

    # 2. 起后台线程推进进度（仅在有进度消息时）
    stop = threading.Event()
    progress_thread: threading.Thread | None = None
    if progress_message_id is not None:
        progress_thread = threading.Thread(
            target=_run_progress,
            args=(client, chat_id, progress_message_id, stop, progress_interval),
            name="tg-progress",
            daemon=True,
        )
        progress_thread.start()

    def _cleanup_progress() -> None:
        """停进度线程并删掉进度条消息（成功/失败都要调用）。"""
        stop.set()
        if progress_thread is not None:
            progress_thread.join(timeout=5)
        if progress_message_id is not None:
            try:
                client.delete_message(chat_id, progress_message_id)
            except Exception:
                pass  # 删不掉也不影响结果发送

    # 3. 同步生成（阻塞）
    try:
        result = generate(prompt)
    except ImageGenerationError as err:
        logger.info("image generation failed: code=%s", err.code)
        _cleanup_progress()
        client.send_message(chat_id, _friendly_error(err))
        return
    except Exception:
        logger.info("image generation unexpected error")
        _cleanup_progress()
        client.send_message(chat_id, PROVIDER_FAILED_HINT)
        return

    # 4. 生成成功：停进度、删进度条，再发图
    _cleanup_progress()

    image_b64 = result.get("image_base64")
    image_url = result.get("image_url")
    caption = "✨ 生成完成"
    keyboard = build_growth_keyboard(webapp_url)

    if image_b64:
        try:
            photo = base64.b64decode(image_b64, validate=True)
        except (binascii.Error, ValueError):
            logger.info("base64 decode failed")
            client.send_message(chat_id, DECODE_FAILED_HINT)
            return
        client.send_photo_bytes(chat_id, photo, caption=caption, reply_markup=keyboard)
        logger.info("sent photo via base64 bytes (size=%d bytes)", len(photo))
        return

    if image_url:
        client.send_photo_url(chat_id, image_url, caption=caption, reply_markup=keyboard)
        logger.info("sent photo via url")  # 不打印完整 URL
        return

    client.send_message(chat_id, PROVIDER_FAILED_HINT)


def run_polling() -> None:
    """长轮询主循环（本地启动入口）。"""
    from core.runtime import config

    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN 未配置，无法启动 bot（请在 .env 设置，勿提交）")

    client = TelegramClient(token)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logger.info("Telegram image bot 启动，开始长轮询...")

    offset: int | None = None
    while True:
        try:
            updates = client.get_updates(offset=offset)
        except TelegramAPIError:
            logger.info("getUpdates 失败，重试中")
            continue
        for update in updates:
            offset = update.get("update_id", 0) + 1
            try:
                handle_update(client, update)
            except TelegramAPIError:
                logger.info("发送消息失败，跳过该 update")
            except Exception:
                logger.info("处理 update 异常，跳过")


if __name__ == "__main__":
    run_polling()

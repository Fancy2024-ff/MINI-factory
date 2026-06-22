# core/platforms/telegram — Telegram image AI bot

Telegram Bot 接入：用户在 bot 里发 prompt → 调用 image generation capability → 返回图片。

## 落点说明
Telegram 是平台特定的交互入口，故放在 `core/platforms/telegram`，与
`core/publisher/telegram_deploy.py`（把生成的小程序部署为 TG WebApp）职责区分：
- `publisher/telegram_deploy.py`：交付侧，部署 H5 WebApp 到 Cloudflare。
- `platforms/telegram/bot.py`：交互侧，聊天 bot 实时生成图片。

## 结构
- `api.py` — Telegram Bot API 轻量 httpx 封装（不引入 python-telegram-bot/aiogram）。
- `bot.py` — 命令/文本分发、错误映射、增长按钮、长轮询入口。
- `tests/` — 全程 mock Telegram + image provider，不打真实网络。

## 复用
图片生成唯一真源 = `core.integrations.image_generation.generate_image`。
bot 直接调 core capability，不绕 HTTP（apps/api 的 `/api/generation/image` 仍保留给小程序前端）。

## 启动
```bash
# .env 配好 TELEGRAM_BOT_TOKEN + IMAGE_GENERATION_* 后（勿提交）
python -m core.platforms.telegram.bot
```

## 命令
- `/start` 使用说明
- `/help` 示例 prompt
- `/image <描述>` 生成图片
- 普通文本也当 prompt 处理

## 安全边界
- token / provider key 只从 `core.runtime.config`（env）读，绝不入消息/日志/测试/提交。
- 不打印 base64 原文，不打印完整图片 URL。
- prompt 长度上限 1000 字符。
- provider 原始错误不透传给用户，统一转友好提示。

/**
 * Cloudflare Pages Function — LLM 代理。
 *
 * 路由：POST /api/chat  （Pages Functions 按文件路径自动映射）
 *
 * 作用：把前端请求转发到上游大模型 /chat/completions，
 *      API key 只存在于 Cloudflare 服务端环境变量（secret），
 *      永不进入下发给用户的 HTML。
 *
 * 服务端环境变量（由 wrangler pages secret 写入）：
 *   LLM_API_KEY  — 上游大模型 API key（必需）
 *   LLM_BASE_URL — 上游 base url，如 https://api.deepseek.com（必需）
 */

const MAX_BODY_BYTES = 32 * 1024; // 32KB，限制请求体防滥用
const UPSTREAM_TIMEOUT_MS = 30_000;

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

export async function onRequestPost(context) {
  const { request, env } = context;

  const apiKey = env.LLM_API_KEY;
  const baseUrl = env.LLM_BASE_URL;
  if (!apiKey || !baseUrl) {
    return json({ error: "server_not_configured" }, 500);
  }

  // 限制 body 大小
  const raw = await request.text();
  if (raw.length > MAX_BODY_BYTES) {
    return json({ error: "payload_too_large" }, 413);
  }

  let payload;
  try {
    payload = JSON.parse(raw);
  } catch {
    return json({ error: "invalid_json" }, 400);
  }

  const messages = payload && payload.messages;
  if (!Array.isArray(messages) || messages.length === 0) {
    return json({ error: "messages_required" }, 400);
  }

  // 只转发白名单字段，避免前端越权传参
  const upstreamBody = {
    model: payload.model,
    messages,
    max_tokens: typeof payload.max_tokens === "number" ? payload.max_tokens : 1024,
  };

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), UPSTREAM_TIMEOUT_MS);
  try {
    const upstream = await fetch(baseUrl.replace(/\/+$/, "") + "/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + apiKey,
      },
      body: JSON.stringify(upstreamBody),
      signal: controller.signal,
    });

    const text = await upstream.text();
    return new Response(text, {
      status: upstream.status,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  } catch (e) {
    return json({ error: "upstream_error", detail: String(e) }, 502);
  } finally {
    clearTimeout(timer);
  }
}

// 非 POST 一律拒绝
export async function onRequest(context) {
  if (context.request.method !== "POST") {
    return json({ error: "method_not_allowed" }, 405);
  }
  return onRequestPost(context);
}

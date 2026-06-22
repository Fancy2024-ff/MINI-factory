"""Image generation provider client.

This module is the only place that talks to the external image-generation
relay. apps/api imports it as an adapter target; generated mini-app frontends
must never receive provider credentials or provider-specific request details.
"""

from __future__ import annotations

from typing import Any

import httpx

from core.runtime import config

ERR_NOT_CONFIGURED = "IMAGE_GENERATION_NOT_CONFIGURED"
ERR_TIMEOUT = "IMAGE_GENERATION_TIMEOUT"
ERR_AUTH_FAILED = "IMAGE_GENERATION_AUTH_FAILED"
ERR_PROVIDER_FAILED = "IMAGE_GENERATION_PROVIDER_FAILED"
ERR_MALFORMED_RESPONSE = "IMAGE_GENERATION_MALFORMED_RESPONSE"
ERR_FAILED = "IMAGE_GENERATION_FAILED"

# Keep aliases patchable in tests while sourcing defaults from core.runtime.config.
IMAGE_GENERATION_ENDPOINT = config.IMAGE_GENERATION_ENDPOINT
IMAGE_GENERATION_API_KEY = config.IMAGE_GENERATION_API_KEY
IMAGE_GENERATION_PROVIDER = config.IMAGE_GENERATION_PROVIDER
IMAGE_GENERATION_TIMEOUT_SECONDS = config.IMAGE_GENERATION_TIMEOUT_SECONDS

_SENSITIVE_RESPONSE_KEYS = {
    "api_key",
    "apikey",
    "key",
    "secret",
    "token",
    "access_token",
    "authorization",
    "auth",
    "bearer",
    "provider_key",
    "password",
}


class ImageGenerationError(Exception):
    """Stable image-generation error that never includes provider secrets."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _strip_sensitive(data: Any) -> Any:
    if isinstance(data, dict):
        return {
            key: _strip_sensitive(value)
            for key, value in data.items()
            if key.lower() not in _SENSITIVE_RESPONSE_KEYS
        }
    if isinstance(data, list):
        return [_strip_sensitive(item) for item in data]
    return data


def _dig(data: Any, *path: Any) -> Any:
    current = data
    for key in path:
        try:
            current = current[key]
        except (KeyError, IndexError, TypeError):
            return None
    return current


def _build_payload(prompt: str, style: str, aspect_ratio: str) -> dict[str, Any]:
    payload: dict[str, Any] = {"prompt": prompt, "provider": IMAGE_GENERATION_PROVIDER}
    if style:
        payload["style"] = style
    if aspect_ratio:
        payload["aspect_ratio"] = aspect_ratio
    return payload


def _normalize_response(raw: dict[str, Any], prompt: str) -> dict[str, Any]:
    image_url = (
        raw.get("image_url")
        or raw.get("url")
        or raw.get("output_url")
        or _dig(raw, "data", 0, "url")
        or _dig(raw, "data", 0, "image_url")
        or _dig(raw, "output", "url")
    )
    image_base64 = (
        raw.get("image_base64")
        or raw.get("b64_json")
        or raw.get("base64")
        or _dig(raw, "data", 0, "b64_json")
        or _dig(raw, "output", "b64_json")
    )
    if not image_url and not image_base64:
        raise ImageGenerationError(ERR_MALFORMED_RESPONSE, "Image result is missing.")

    metadata = raw.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    return {
        "provider": IMAGE_GENERATION_PROVIDER,
        "status": "succeeded",
        "image_url": image_url,
        "image_base64": image_base64,
        "prompt": prompt,
        "metadata": metadata,
    }


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {IMAGE_GENERATION_API_KEY}",
        "Content-Type": "application/json",
    }


def _post(endpoint: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    try:
        response = httpx.post(endpoint, json=payload, headers=_headers(), timeout=timeout)
    except httpx.TimeoutException:
        raise ImageGenerationError(ERR_TIMEOUT, "Image generation timed out.")
    except httpx.HTTPError:
        raise ImageGenerationError(ERR_PROVIDER_FAILED, "Image generation service is unavailable.")

    if response.status_code in (401, 403):
        raise ImageGenerationError(ERR_AUTH_FAILED, "Image generation authentication failed.")
    if response.status_code >= 400:
        raise ImageGenerationError(ERR_PROVIDER_FAILED, "Image generation service returned an error.")

    try:
        data = response.json()
    except Exception:
        raise ImageGenerationError(ERR_MALFORMED_RESPONSE, "Image generation response is invalid.")
    if not isinstance(data, dict):
        raise ImageGenerationError(ERR_MALFORMED_RESPONSE, "Image generation response is invalid.")
    return _strip_sensitive(data)


def generate_image(prompt: str, style: str = "", aspect_ratio: str = "1:1") -> dict[str, Any]:
    prompt = (prompt or "").strip()
    if not prompt:
        raise ImageGenerationError(ERR_FAILED, "Prompt is required.")
    if not IMAGE_GENERATION_ENDPOINT:
        raise ImageGenerationError(ERR_NOT_CONFIGURED, "Image generation endpoint is not configured.")
    if not IMAGE_GENERATION_API_KEY:
        raise ImageGenerationError(ERR_NOT_CONFIGURED, "Image generation credential is not configured.")

    payload = _build_payload(prompt, style, aspect_ratio)
    raw = _post(IMAGE_GENERATION_ENDPOINT, payload, IMAGE_GENERATION_TIMEOUT_SECONDS)
    return _normalize_response(raw, prompt)

import asyncio
import base64
import logging
import mimetypes
import os
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import requests
from google import genai
from google.genai import types

try:
    import yaml
except Exception:
    yaml = None

logger = logging.getLogger(__name__)

IMAGE_MODEL_NAME = "gemini-2.0-flash-preview-image-generation"
_CONFIG_CACHE: Optional[Dict[str, Any]] = None
_RATE_LIMIT_SECONDS = 30.0
_LAST_GENERATION_TS: Optional[float] = None
_RATE_LIMIT_LOCK = threading.Lock()


def _load_config() -> Dict[str, Any]:
    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE
    if not yaml:
        _CONFIG_CACHE = {}
        return _CONFIG_CACHE
    config_path = os.path.join(os.getcwd(), "config.yml")
    if not os.path.exists(config_path):
        _CONFIG_CACHE = {}
        return _CONFIG_CACHE
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            _CONFIG_CACHE = yaml.safe_load(f) or {}
    except Exception as exc:
        logger.debug(f"Failed to load config.yml for image generation: {exc}")
        _CONFIG_CACHE = {}
    return _CONFIG_CACHE


def _resolve_webhook_url() -> Tuple[Optional[str], str]:
    config = _load_config()
    candidates = []
    if isinstance(config, dict):
        webhooks = config.get("webhooks")
        if isinstance(webhooks, dict):
            candidates.append(webhooks.get("image_generation"))
            candidates.append(webhooks.get("image_generation_webhook"))

        discord_cfg = config.get("discord")
        if isinstance(discord_cfg, dict):
            candidates.append(discord_cfg.get("image_generation_webhook"))
            candidates.append(discord_cfg.get("image_webhook"))

        image_cfg = config.get("image_generation")
        if isinstance(image_cfg, dict):
            candidates.append(image_cfg.get("webhook"))
            candidates.append(image_cfg.get("discord_webhook"))

    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip(), "config"

    env_webhook = os.getenv("DISCORD_IMAGE_WEBHOOK")
    if env_webhook and env_webhook.strip():
        return env_webhook.strip(), "environment"

    return None, "missing"


def _build_default_filename(extension: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d")
    base = f"{stamp}-gabriel-generatedimage"
    ext = extension if extension.startswith(".") else f".{extension}" if extension else ".png"
    if base.lower().endswith(ext.lower()):
        return base
    return f"{base}{ext}"


def _sanitize_discord_content(content: Optional[str]) -> Optional[str]:
    if not content:
        return content
    sanitized = content.replace("@everyone", "@\u200beveryone")
    sanitized = sanitized.replace("@here", "@\u200bhere")
    return sanitized


def _resolve_api_key() -> Tuple[Optional[str], str]:
    config = _load_config()
    if isinstance(config, dict):
        api_cfg = config.get("api")
        if isinstance(api_cfg, dict):
            direct_key = api_cfg.get("api_key")
            if isinstance(direct_key, str) and direct_key.strip():
                return direct_key.strip(), "config"
            env_name = api_cfg.get("key_env_var")
            if isinstance(env_name, str) and env_name.strip():
                env_value = os.getenv(env_name.strip())
                if env_value and env_value.strip():
                    return env_value.strip(), f"environment:{env_name.strip()}"

    fallback_env = os.getenv("GEMINI_API_KEY")
    if fallback_env and fallback_env.strip():
        return fallback_env.strip(), "environment:GEMINI_API_KEY"

    legacy = config.get("gemini_api_key") if isinstance(config, dict) else None
    if isinstance(legacy, str) and legacy.strip():
        return legacy.strip(), "config"

    return None, "missing"


IMAGE_FUNCTION_DECLARATIONS = [
    {
        "name": "generate_image_to_webhook",
        "description": "Generate an image from a prompt using Gemini and upload it to a Discord webhook.",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Detailed description of the image to generate"
                },
                "message": {
                    "type": "string",
                    "description": "Optional message to include with the Discord post"
                }
            },
            "required": ["prompt"]
        }
    }
]

async def handle_image_generation_function_calls(function_call) -> types.FunctionResponse:
    name = function_call.name
    args = function_call.args or {}
    try:
        if name == "generate_image_to_webhook":
            result = await asyncio.to_thread(
                _generate_image_to_webhook,
                args.get("prompt"),
                args.get("message")
            )
        else:
            result = {"success": False, "message": f"Unknown image generation function: {name}"}
        return types.FunctionResponse(id=function_call.id, name=name, response=result)
    except Exception as exc:
        logger.error(f"Image generation tool error: {exc}")
        return types.FunctionResponse(
            id=function_call.id,
            name=name,
            response={"success": False, "message": str(exc)}
        )

def _generate_image_to_webhook(prompt: Optional[str], message: Optional[str]) -> Dict[str, Any]:
    cleaned_prompt = (prompt or "").strip()
    if not cleaned_prompt:
        return {"success": False, "message": "prompt is required"}
    global _LAST_GENERATION_TS
    with _RATE_LIMIT_LOCK:
        now = time.monotonic()
        if _LAST_GENERATION_TS is not None and now - _LAST_GENERATION_TS < _RATE_LIMIT_SECONDS:
            wait_time = int(_RATE_LIMIT_SECONDS - (now - _LAST_GENERATION_TS)) + 1
            return {"success": False, "message": f"Image generation limited to one request every 30 seconds. Try again in {wait_time} seconds."}
        _LAST_GENERATION_TS = now
    resolved_webhook, webhook_source = _resolve_webhook_url()
    if not resolved_webhook:
        return {"success": False, "message": "Discord webhook not configured. Set webhooks.image_generation in config.yml or DISCORD_IMAGE_WEBHOOK."}
    api_key, api_source = _resolve_api_key()
    if not api_key:
        return {"success": False, "message": "Gemini API key missing. Set api.api_key in config.yml or provide GEMINI_API_KEY."}
    client = genai.Client(api_key=api_key)
    contents = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=cleaned_prompt)]
        )
    ]
    config = types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"])
    response = client.models.generate_content(
        model=IMAGE_MODEL_NAME,
        contents=contents,
        config=config
    )
    images = []
    text_outputs: list[str] = []
    if response.candidates:
        for candidate in response.candidates:
            content = getattr(candidate, "content", None)
            if not content or not getattr(content, "parts", None):
                continue
            for part in content.parts:
                inline = getattr(part, "inline_data", None)
                if inline and getattr(inline, "data", None):
                    data = inline.data
                    if isinstance(data, str):
                        data = base64.b64decode(data)
                    mime_type = getattr(inline, "mime_type", None) or "image/png"
                    images.append((data, mime_type))
                    continue
                text_attr = getattr(part, "text", None)
                if isinstance(text_attr, str) and text_attr.strip():
                    text_outputs.append(text_attr.strip())
    if not images:
        return {"success": False, "message": "No image content returned"}
    image_bytes, mime_type = images[0]
    extension = mimetypes.guess_extension(mime_type) or ".png"
    final_name = _build_default_filename(extension)
    effective_message = message
    if not effective_message:
        combined_text = " ".join(text_outputs).strip()
        if combined_text:
            effective_message = combined_text
    if not effective_message:
        effective_message = f"Image generated for prompt: {cleaned_prompt}"
    effective_message = _sanitize_discord_content(effective_message)
    payload = {"content": effective_message}
    files = {"file": (final_name, image_bytes, mime_type)}
    response = requests.post(resolved_webhook, data=payload, files=files, timeout=30)
    if response.status_code >= 400:
        return {"success": False, "message": f"Discord webhook error: {response.status_code}"}
    return {
        "success": True,
        "message": "Image generated and posted",
        "file_name": final_name,
        "mime_type": mime_type,
        "webhook_source": webhook_source,
        "api_key_source": api_source,
        "model_text": text_outputs
    }

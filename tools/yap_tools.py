"""
Yap mode tools for Gabriel "Arre Yaar ENABLE YAP MODE"
"""

import logging
from typing import Dict, Any
from google.genai import types

logger = logging.getLogger(__name__)


_YAP_MODE_ENABLED: bool = False
_AI_SPEAKING: bool = False
_YAP_TURNS_REMAINING: int = 0


def is_yap_mode_enabled() -> bool:
    """Return whether yap mode is currently enabled."""
    return _YAP_MODE_ENABLED


def set_yap_mode(enabled: bool) -> None:
    """Set yap mode on or off."""
    global _YAP_MODE_ENABLED
    global _YAP_TURNS_REMAINING
    prev = _YAP_MODE_ENABLED
    _YAP_MODE_ENABLED = bool(enabled)
    
    if _YAP_MODE_ENABLED:
        _YAP_TURNS_REMAINING = 3
    else:
        _YAP_TURNS_REMAINING = 0
    logger.info(f"Yap mode {'ENABLED' if _YAP_MODE_ENABLED else 'DISABLED'} (was {'ENABLED' if prev else 'DISABLED'}); turns_remaining={_YAP_TURNS_REMAINING}")


def is_ai_speaking() -> bool:
    """Return whether the AI is currently speaking (output audio playing)."""
    return _AI_SPEAKING


def set_ai_speaking(speaking: bool) -> None:
    """Set whether the AI is currently speaking.

    This should be toggled by the audio receive/playback pipeline when
    output audio starts and ends.
    """
    global _AI_SPEAKING
    prev = _AI_SPEAKING
    _AI_SPEAKING = bool(speaking)
    
    if prev != _AI_SPEAKING:
        logger.info(f"AI speaking state: {'STARTED' if _AI_SPEAKING else 'ENDED'}")


def notify_ai_turn_complete() -> int:
    """Notify yap system that one AI turn completed and decrement counter.

    Returns the remaining turns (0 means yap mode was auto-disabled).
    """
    global _YAP_TURNS_REMAINING
    try:
        if _YAP_MODE_ENABLED and _YAP_TURNS_REMAINING > 0:
            _YAP_TURNS_REMAINING -= 1
            logger.info(f"Yap turns remaining: {_YAP_TURNS_REMAINING}")
            if _YAP_TURNS_REMAINING <= 0:
                set_yap_mode(False)
        return _YAP_TURNS_REMAINING
    except Exception as e:
        logger.warning(f"Error notifying yap turn complete: {e}")
        return _YAP_TURNS_REMAINING


def get_yap_turns_remaining() -> int:
    """Return number of AI turns remaining before yap auto-disables."""
    return _YAP_TURNS_REMAINING



YAP_FUNCTION_DECLARATIONS = [
    {
        "name": "enable_yap_mode",
        "description": (
            "Disable microphone input so the user cannot interrupt you. "
            "Use this when you need to speak without being cut off. You must later call disable_yap_mode to re-enable input."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Optional explanation shown in logs/UI for enabling yap mode.",
                    "default": "AI requires uninterrupted speaking"
                }
            }
        }
    },
    {
        "name": "disable_yap_mode",
        "description": "Re-enable microphone input so the user can speak to you again.",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Optional explanation shown in logs/UI for disabling yap mode.",
                    "default": "AI finished speaking uninterrupted"
                }
            }
        }
    },
    {
        "name": "get_yap_mode_status",
        "description": "Get whether yap mode is currently enabled (audio input disabled).",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    }
]


async def handle_yap_function_calls(function_call) -> types.FunctionResponse:
    """Handle yap mode related function calls."""
    fname = function_call.name
    args: Dict[str, Any] = function_call.args or {}
    try:
        if fname == "enable_yap_mode":
            reason = args.get("reason", "AI requires uninterrupted speaking")
            set_yap_mode(True)
            response = {
                "success": True,
                "message": f"Yap mode enabled. {reason}",
                "yap_mode_enabled": True
            }
        elif fname == "disable_yap_mode":
            reason = args.get("reason", "AI finished speaking uninterrupted")
            set_yap_mode(False)
            response = {
                "success": True,
                "message": f"Yap mode disabled. {reason}",
                "yap_mode_enabled": False
            }
        elif fname == "get_yap_mode_status":
            response = {
                "success": True,
                "yap_mode_enabled": is_yap_mode_enabled()
            }
        else:
            response = {
                "success": False,
                "message": f"Unknown yap function: {fname}"
            }

        return types.FunctionResponse(
            id=function_call.id,
            name=fname,
            response=response,
        )
    except Exception as e:
        logger.error(f"Error handling yap function {fname}: {e}")
        return types.FunctionResponse(
            id=function_call.id,
            name=fname,
            response={
                "success": False,
                "message": f"Error executing {fname}: {str(e)}"
            }
        )

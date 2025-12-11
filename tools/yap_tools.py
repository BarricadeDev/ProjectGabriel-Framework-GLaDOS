"""
Yap mode tools for Gabriel "Arre Yaar ENABLE YAP MODE"
"""

import logging
import time
import asyncio
from typing import Dict, Any, Optional
from google.genai import types

logger = logging.getLogger(__name__)


_YAP_MODE_ENABLED: bool = False
_AI_SPEAKING: bool = False
_YAP_TURNS_REMAINING: int = 0
_YAP_TIMER_TASK: Optional[asyncio.Task] = None
_YAP_ENABLE_TIME: float = 0.0
_YAP_DURATION: float = 30.0  # Default 30 seconds


def is_yap_mode_enabled() -> bool:
    """Return whether yap mode is currently enabled."""
    return _YAP_MODE_ENABLED


def set_yap_mode(enabled: bool, duration: float = 30.0) -> None:
    """Set yap mode on or off.
    
    Args:
        enabled: Whether to enable yap mode
        duration: Duration in seconds before auto-disable (default 30s, max 60s)
    """
    global _YAP_MODE_ENABLED, _YAP_TURNS_REMAINING, _YAP_TIMER_TASK, _YAP_ENABLE_TIME, _YAP_DURATION
    
    prev = _YAP_MODE_ENABLED
    _YAP_MODE_ENABLED = bool(enabled)
    
    # Cancel existing timer if any
    if _YAP_TIMER_TASK and not _YAP_TIMER_TASK.done():
        _YAP_TIMER_TASK.cancel()
        _YAP_TIMER_TASK = None
    
    if _YAP_MODE_ENABLED:
        _YAP_TURNS_REMAINING = 3  # Keep for legacy compatibility
        _YAP_ENABLE_TIME = time.time()
        _YAP_DURATION = min(max(1.0, duration), 60.0)  # Clamp between 1-60 seconds
        logger.info(f"Yap mode ENABLED (was {'ENABLED' if prev else 'DISABLED'}); will auto-disable in {_YAP_DURATION}s")
        
        # Start background timer
        try:
            loop = asyncio.get_event_loop()
            _YAP_TIMER_TASK = loop.create_task(_yap_timer_task())
        except RuntimeError:
            logger.warning("No event loop available to start YAP timer")
    else:
        _YAP_TURNS_REMAINING = 0
        _YAP_ENABLE_TIME = 0.0
        logger.info(f"Yap mode DISABLED (was {'ENABLED' if prev else 'DISABLED'})")


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


async def _yap_timer_task():
    """Background task to auto-disable YAP mode after duration expires."""
    global _YAP_MODE_ENABLED, _YAP_ENABLE_TIME, _YAP_DURATION
    
    try:
        await asyncio.sleep(_YAP_DURATION)
        
        # Check if YAP mode is still enabled and hasn't been manually disabled
        if _YAP_MODE_ENABLED and _YAP_ENABLE_TIME > 0:
            elapsed = time.time() - _YAP_ENABLE_TIME
            logger.info(f"YAP mode auto-disabling after {elapsed:.1f}s (duration: {_YAP_DURATION}s)")
            set_yap_mode(False)
    except asyncio.CancelledError:
        logger.debug("YAP timer task cancelled")
    except Exception as e:
        logger.error(f"Error in YAP timer task: {e}")


def get_yap_time_remaining() -> float:
    """Return seconds remaining before YAP mode auto-disables, or 0 if disabled."""
    if not _YAP_MODE_ENABLED or _YAP_ENABLE_TIME == 0:
        return 0.0
    elapsed = time.time() - _YAP_ENABLE_TIME
    remaining = max(0.0, _YAP_DURATION - elapsed)
    return remaining



YAP_FUNCTION_DECLARATIONS = [
    {
        "name": "enable_yap_mode",
        "description": (
            "Disable microphone input so the user cannot interrupt you. "
            "YAP mode will automatically disable after the specified duration (default 30s, max 60s). "
            "Use this when you need to speak without being cut off."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "duration": {
                    "type": "number",
                    "description": "Duration in seconds before YAP mode auto-disables (default: 30, max: 60)",
                    "default": 30.0,
                    "minimum": 1.0,
                    "maximum": 60.0
                },
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
            duration = args.get("duration", 30.0)
            reason = args.get("reason", "AI requires uninterrupted speaking")
            set_yap_mode(True, duration=duration)
            response = {
                "success": True,
                "message": f"Yap mode enabled for {duration}s. {reason}",
                "yap_mode_enabled": True,
                "duration": duration
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
                "yap_mode_enabled": is_yap_mode_enabled(),
                "time_remaining_seconds": get_yap_time_remaining()
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

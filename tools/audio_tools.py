import logging
from typing import Dict, Any
from google.genai import types

logger = logging.getLogger(__name__)

try:
    from sfx import sfx_manager
    SFX_OK = True
except Exception as e:
    sfx_manager = None
    SFX_OK = False
    logger.warning(f"SFX unavailable: {e}")

try:
    from myinstants import myinstants_client
    MYI_OK = True
except Exception as e:
    myinstants_client = None
    MYI_OK = False
    logger.warning(f"MyInstants unavailable: {e}")

AUDIO_FUNCTION_DECLARATIONS = [
    {
        "name": "stop_all_audio_playback",
        "description": "Stop audio playback globally. Optionally target only music files.",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Choose 'all' to stop all audio, or 'music' to stop only music category where supported.",
                    "enum": ["all", "music"],
                    "default": "all"
                }
            }
        }
    }
]

async def handle_audio_function_calls(function_call) -> types.FunctionResponse:
    name = function_call.name
    args = function_call.args or {}
    try:
        if name == "stop_all_audio_playback":
            target = str(args.get("target", "all")).lower().strip() or "all"
            stopped_sfx = False
            stopped_myinstants = False
            sfx_msg = None
            myi_msg = None
            if SFX_OK and sfx_manager is not None:
                if target == "music":
                    try:
                        if getattr(sfx_manager, "is_music_playing", lambda: False)():
                            r = sfx_manager.stop_audio()
                            stopped_sfx = bool(r.get("success"))
                            sfx_msg = r.get("message")
                        else:
                            sfx_msg = "No music playing"
                    except Exception as e:
                        sfx_msg = str(e)
                else:
                    try:
                        r = sfx_manager.stop_audio()
                        stopped_sfx = bool(r.get("success"))
                        sfx_msg = r.get("message")
                    except Exception as e:
                        sfx_msg = str(e)
            if MYI_OK and myinstants_client is not None:
                if target == "all":
                    try:
                        r2 = myinstants_client.stop_sound()
                        stopped_myinstants = bool(r2.get("success"))
                        myi_msg = r2.get("message")
                    except Exception as e:
                        myi_msg = str(e)
                else:
                    myi_msg = "Skipped for music-only"
            result: Dict[str, Any] = {
                "success": True,
                "target": target,
                "stopped_sfx": stopped_sfx,
                "stopped_myinstants": stopped_myinstants,
                "sfx_message": sfx_msg,
                "myinstants_message": myi_msg
            }
        else:
            result = {"success": False, "message": f"Unknown audio function: {name}"}
        return types.FunctionResponse(id=function_call.id, name=name, response=result)
    except Exception as e:
        logger.error(f"Audio tool error: {e}")
        return types.FunctionResponse(
            id=function_call.id,
            name=name,
            response={"success": False, "message": str(e)}
        )

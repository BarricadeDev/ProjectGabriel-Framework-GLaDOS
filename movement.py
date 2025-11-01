import asyncio
import logging
import random
from typing import Any, Dict, Optional

from pythonosc.udp_client import SimpleUDPClient

import osc

logger = logging.getLogger(__name__)



_movement_config: Dict[str, Any] = {}
_fallback_client: Optional[SimpleUDPClient] = None
_active_press_tasks: Dict[str, asyncio.Task] = {}
_key_injector = None  


def initialize_movement(config: Dict[str, Any]) -> None:
    global _movement_config, _fallback_client
    _movement_config = config.get("movement", {}) if config else {}

    host = (_movement_config.get("host") or config.get("osc", {}).get("host") or "127.0.0.1")
    port = int(_movement_config.get("port") or config.get("osc", {}).get("port") or 9000)

    try:
        
        _fallback_client = SimpleUDPClient(host, port)
        logger.info(f"Movement OSC fallback client ready at {host}:{port}")
    except Exception as e:
        _fallback_client = None
        logger.warning(f"Unable to initialize movement fallback OSC client: {e}")

    
    global _key_injector
    if _key_injector is None:
        try:
            import pydirectinput as _pdi  
            _key_injector = _pdi
            
            pause = float(_movement_config.get("key_inject_pause", 0.0))
            try:
                _pdi.PAUSE = pause
            except Exception:
                pass
            logger.info("Keyboard injector ready via PyDirectInput")
        except Exception as e:
            _key_injector = None
            logger.warning(f"PyDirectInput not available for keyboard inputs: {e}")

    
    try:
        lb_min = _movement_config.get("look_behind_min")
        lb_max = _movement_config.get("look_behind_max")
        if lb_min is None or lb_max is None:
            lb_min = _movement_config.get("turn_duration_min", _movement_config.get("turn_duration_default", 1.0))
            lb_max = _movement_config.get("turn_duration_max", _movement_config.get("turn_duration_default", 1.0))
        logger.info(f"Movement config: use_axis={_movement_config.get('use_axis', False)}, look_behind_min={lb_min}, look_behind_max={lb_max}, turn_default={_movement_config.get('turn_duration_default', 1.0)}")
    except Exception:
        pass


def _get_udp_client() -> Optional[SimpleUDPClient]:
    client = osc.get_osc_client()
    if client and getattr(client, "client", None):
        return client.client
    return _fallback_client


async def _press_button(address: str, duration: float) -> None:
    client = _get_udp_client()
    if not client:
        logger.error("OSC client not available for movement inputs")
        return

    try:
        client.send_message(address, 1)
        await asyncio.sleep(max(0.0, duration))
    finally:
        try:
            client.send_message(address, 0)
        except Exception as e:
            logger.warning(f"Failed to release {address}: {e}")


async def _set_axis(address: str, value: float, duration: float) -> None:
    client = _get_udp_client()
    if not client:
        logger.error("OSC client not available for movement inputs")
        return

    try:
        client.send_message(address, float(value))
        await asyncio.sleep(max(0.0, duration))
    finally:
        try:
            client.send_message(address, 0.0)
        except Exception as e:
            logger.warning(f"Failed to reset axis {address}: {e}")


def _spawn_unique_press(address: str, coro_factory) -> None:
    existing = _active_press_tasks.get(address)
    if existing and not existing.done():
        existing.cancel()
    task = asyncio.create_task(coro_factory())
    _active_press_tasks[address] = task



def _key_down(key: str) -> None:
    global _key_injector
    if _key_injector is None:
        try:
            import pydirectinput as _pdi  
            _key_injector = _pdi
        except Exception as e:
            raise RuntimeError(f"Keyboard injector not available. Install pydirectinput. {e}")
    _key_injector.keyDown(key)


def _key_up(key: str) -> None:
    global _key_injector
    if _key_injector is None:
        try:
            import pydirectinput as _pdi  
            _key_injector = _pdi
        except Exception as e:
            raise RuntimeError(f"Keyboard injector not available. Install pydirectinput. {e}")
    _key_injector.keyUp(key)


async def _press_key(key: str, duration: float) -> None:
    try:
        _key_down(key)
        await asyncio.sleep(max(0.0, duration))
    finally:
        try:
            _key_up(key)
        except Exception as e:
            logger.warning(f"Failed to release key {key}: {e}")



async def look_turn(direction: str, duration: Optional[float] = None) -> Dict[str, Any]:
    use_axis = bool(_movement_config.get("use_axis", False))
    default_duration = float(_movement_config.get("turn_duration_default", 1.0))
    axis_value = float(_movement_config.get("axis_turn_value", 1.0))

    dur = float(duration if duration is not None else default_duration)

    direction = (direction or "").lower()
    if direction not in {"left", "right"}:
        return {"success": False, "message": "direction must be 'left' or 'right'"}

    if use_axis:
        value = -axis_value if direction == "left" else axis_value
        address = "/input/LookHorizontal"
        _spawn_unique_press(address, lambda: _set_axis(address, value, dur))
    else:
        address = "/input/LookLeft" if direction == "left" else "/input/LookRight"
        _spawn_unique_press(address, lambda: _press_button(address, dur))

    return {"success": True, "action": "look_turn", "direction": direction, "duration": dur}


async def look_behind(min_seconds: Optional[float] = None, max_seconds: Optional[float] = None) -> Dict[str, Any]:
    
    lb_min_cfg = _movement_config.get("look_behind_min")
    lb_max_cfg = _movement_config.get("look_behind_max")

    if lb_min_cfg is None or lb_max_cfg is None:
        
        turn_default = float(_movement_config.get("turn_duration_default", 1.0))
        lb_min = float(_movement_config.get("turn_duration_min", turn_default)) if lb_min_cfg is None else float(lb_min_cfg)
        lb_max = float(_movement_config.get("turn_duration_max", turn_default)) if lb_max_cfg is None else float(lb_max_cfg)
    else:
        lb_min = float(lb_min_cfg)
        lb_max = float(lb_max_cfg)

    
    if min_seconds is not None and float(min_seconds) not in {2.0}:  
        lb_min = float(min_seconds)
    if max_seconds is not None and float(max_seconds) not in {3.0}:  
        lb_max = float(max_seconds)

    if lb_max < lb_min:
        lb_min, lb_max = lb_max, lb_min

    dur = lb_min if abs(lb_max - lb_min) < 1e-6 else random.uniform(lb_min, lb_max)
    direction = random.choice(["left", "right"]) if _movement_config.get("randomize_back_turn", True) else "left"
    result = await look_turn(direction, dur)
    result.update({"action": "look_behind", "randomized": lb_min != lb_max, "min": lb_min, "max": lb_max, "duration": dur})
    return result


async def move_direction(direction: str, duration: Optional[float] = None, run: Optional[bool] = None) -> Dict[str, Any]:
    direction = (direction or "").lower()
    if direction not in {"forward", "backward", "left", "right"}:
        return {"success": False, "message": "direction must be one of forward|backward|left|right"}

    default_move_duration = float(_movement_config.get("move_duration_default", 1.0))
    dur = float(duration if duration is not None else default_move_duration)

    button_map = {
        "forward": "/input/MoveForward",
        "backward": "/input/MoveBackward",
        "left": "/input/MoveLeft",
        "right": "/input/MoveRight",
    }

    address = button_map[direction]

    
    run_enabled = bool(_movement_config.get("allow_run", True))
    should_run = (run is True) or (run is None and bool(_movement_config.get("run_by_default", False)))

    if run_enabled and should_run:
        
        _spawn_unique_press("/input/Run", lambda: _press_button("/input/Run", dur))

    _spawn_unique_press(address, lambda: _press_button(address, dur))
    return {"success": True, "action": "move", "direction": direction, "duration": dur, "run": bool(run_enabled and should_run)}


async def jump() -> Dict[str, Any]:
    _spawn_unique_press("/input/Jump", lambda: _press_button("/input/Jump", 0.05))
    return {"success": True, "action": "jump"}


async def crouch() -> Dict[str, Any]:
    tap = float(_movement_config.get("key_tap_duration", 0.05))
    try:
        _spawn_unique_press("key:c", lambda: _press_key("c", tap))
        return {"success": True, "action": "crouch", "key": "c", "duration": tap}
    except Exception as e:
        return {"success": False, "message": f"Crouch failed: {e}"}


async def crawl() -> Dict[str, Any]:
    tap = float(_movement_config.get("key_tap_duration", 0.05))
    try:
        _spawn_unique_press("key:z", lambda: _press_key("z", tap))
        return {"success": True, "action": "crawl", "key": "z", "duration": tap}
    except Exception as e:
        return {"success": False, "message": f"Crawl failed: {e}"}


async def stop_all_inputs() -> Dict[str, Any]:
    for addr, task in list(_active_press_tasks.items()):
        if task and not task.done():
            task.cancel()
        _active_press_tasks.pop(addr, None)

    
    try:
        _key_up("c")
    except Exception:
        pass
    try:
        _key_up("z")
    except Exception:
        pass

    return {"success": True, "action": "stop_all_inputs"}



MOVEMENT_FUNCTION_DECLARATIONS = [
    {
        "name": "look_behind",
        "description": "Turn around by holding look left or right for a short duration. Direction is chosen randomly each call.",
        "parameters": {
            "type": "object",
            "properties": {
                "min_seconds": {"type": "number", "description": "Minimum duration to hold turn (omit to use config)"},
                "max_seconds": {"type": "number", "description": "Maximum duration to hold turn (omit to use config)"}
            }
        }
    },
    {
        "name": "look_turn",
        "description": "Turn the view left or right for a duration.",
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["left", "right"], "description": "Turn direction"},
                "duration": {"type": "number", "description": "How long to hold the turn", "default": 1.0}
            },
            "required": ["direction"]
        }
    },
    {
        "name": "move_direction",
        "description": "Move the character in a cardinal direction for a duration, optionally holding Run.",
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["forward", "backward", "left", "right"], "description": "Movement direction"},
                "duration": {"type": "number", "description": "How long to move", "default": 1.0},
                "run": {"type": "boolean", "description": "Hold Run while moving"}
            },
            "required": ["direction"]
        }
    },
    {
        "name": "jump",
        "description": "Trigger a jump press.",
        "parameters": {"type": "object", "properties": {}}
    },
    {
        "name": "crouch",
    "description": "Toggle crouch by tapping the 'C' key.",
    "parameters": {"type": "object", "properties": {}}
    },
    {
        "name": "crawl",
    "description": "Toggle crawl by tapping the 'Z' key.",
    "parameters": {"type": "object", "properties": {}}
    },
    {
        "name": "stop_all_inputs",
        "description": "Release all known movement/look inputs to avoid getting stuck.",
        "parameters": {"type": "object", "properties": {}}
    }
]


async def handle_movement_function_calls(function_call):
    from google.genai import types  
    name = function_call.name
    args = function_call.args or {}

    try:
        if name == "look_behind":
            result = await look_behind(args.get("min_seconds"), args.get("max_seconds"))
        elif name == "look_turn":
            result = await look_turn(args.get("direction"), args.get("duration"))
        elif name == "move_direction":
            result = await move_direction(args.get("direction"), args.get("duration"), args.get("run"))
        elif name == "jump":
            result = await jump()
        elif name == "crouch":
            result = await crouch()
        elif name == "crawl":
            result = await crawl()
        elif name == "stop_all_inputs":
            result = await stop_all_inputs()
        else:
            result = {"success": False, "message": f"Unknown movement function: {name}"}

        return types.FunctionResponse(id=function_call.id, name=name, response=result)

    except Exception as e:
        logger.error(f"Movement function {name} failed: {e}")
        return types.FunctionResponse(
            id=function_call.id,
            name=name,
            response={"success": False, "message": f"Error executing {name}: {str(e)}"}
        )


def get_movement_tools():
    return [{"function_declarations": MOVEMENT_FUNCTION_DECLARATIONS}]

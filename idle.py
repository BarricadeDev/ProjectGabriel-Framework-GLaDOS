import threading
import time
from typing import Optional

import numpy as np
import mss
import cv2

import osc
from vision import vision as vision_module

_idle_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_running = False


def _is_ai_idle() -> bool:
    client = osc.get_osc_client()
    if not client or not client.enabled:
        return True
    st = client.get_status()
    
    try:
        cooldown = float(getattr(vision_module, 'config', {}).get('idle_cooldown_after_speech', 30.0))
    except Exception:
        cooldown = 30.0
    last_speech_end = st.get('last_speech_end_time') or 0
    if last_speech_end > 0 and (time.time() - last_speech_end) < cooldown:
        return False
    if st.get('is_typing') or st.get('has_active_send_task'):
        return False
    last_ts = st.get('last_message_time') or 0
    if last_ts > 0 and (time.time() - last_ts) < 0.4:
        return False
    return True


def _idle_gaze_loop():
    global _running
    cfg = getattr(vision_module, 'config', {})

    try:
        vision_module.initialize_in_background()
    except Exception:
        pass

    for _ in range(120):
        st = vision_module.get_status() if hasattr(vision_module, 'get_status') else {"model_ready": True}
        if st.get('model_ready', False):
            break
        if _stop_event.is_set():
            return
        time.sleep(0.1)

    window = vision_module.get_game_window()
    if not window:
        return
    left, top, width, height = window

    deadzone_frac = float(cfg.get('idle_deadzone', 0.03))
    check_interval = float(cfg.get('idle_poll_interval', 0.06))

    _running = True
    with mss.mss() as sct:
        while not _stop_event.is_set():
            vs = vision_module.get_status() if hasattr(vision_module, 'get_status') else {}
            if not _is_ai_idle() or vs.get('following'):
                time.sleep(0.05)
                continue

            try:
                osc.maybe_send_idle_ui()
            except Exception:
                pass

            monitor = {"top": top, "left": left, "width": width, "height": height}
            try:
                screenshot = sct.grab(monitor)
            except Exception as e:
                
                time.sleep(0.1)
                continue

            frame = np.array(screenshot)
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

            players = vision_module.detect_players(frame)
            if players:
                player = players[0]
                if isinstance(player, dict):
                    x1, y1, x2, y2 = player["x1"], player["y1"], player["x2"], player["y2"]
                else:
                    
                    x1, y1, x2, y2 = player[:4]
                player_center_x = (x1 + x2) // 2
                screen_center_x = width // 2
                deviation = player_center_x - screen_center_x
                deadzone = width * deadzone_frac

                if deviation > deadzone:
                    try:
                        vision_module.rotate_right(steps=1)
                    except Exception:
                        pass
                elif deviation < -deadzone:
                    try:
                        vision_module.rotate_left(steps=1)
                    except Exception:
                        pass

            time.sleep(check_interval)

    _running = False


def start_idle_gaze() -> bool:
    if not getattr(vision_module, 'config', {}).get('enabled', True):
        return False
    if getattr(vision_module, 'get_status', None) and vision_module.get_status().get('following'):
        return False
    global _idle_thread
    if _idle_thread and _idle_thread.is_alive():
        return True
    _stop_event.clear()
    t = threading.Thread(target=_idle_gaze_loop, name="idle-gaze", daemon=True)
    _idle_thread = t
    t.start()
    return True


def stop_idle_gaze() -> bool:
    _stop_event.set()
    return True


def get_status():
    return {"running": _running}

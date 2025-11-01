"""
VRChat OSC API Integration Module

VRChat OSC Documentation:
- Overview: https://docs.vrchat.com/docs/osc-overview
- Input Controller: https://docs.vrchat.com/docs/osc-as-input-controller
"""

import asyncio
import logging
import time
import re
import os
import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Callable, Union
from pythonosc.udp_client import SimpleUDPClient

logger = logging.getLogger(__name__)


class VRChatOSCClient:
    """
    VRChat OSC Client for sending Gabriel's responses to the chatbox.
    
    VRChat defaults:
    - Receiving on port 9000 (where we send messages TO VRChat)
    - Sending on port 9001 (where VRChat sends messages FROM VRChat)
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the VRChat OSC client.
        
        Args:
            config: Configuration dictionary containing OSC settings
        """
        self.config = config.get('osc', {})
        self.enabled = self.config.get('enabled', False)
        
        if not self.enabled:
            logger.info("VRChat OSC integration is disabled")
            return
            
        
        self.host = self.config.get('host', '127.0.0.1')
        self.port = self.config.get('port', 9000)  
        
        
        chatbox_config = self.config.get('chatbox', {})
        self.max_length = chatbox_config.get('max_length', 144)  
        self.send_immediately = chatbox_config.get('send_immediately', True)
        self.notification_sound = chatbox_config.get('notification_sound', True)
        self.auto_clear_delay = chatbox_config.get('auto_clear_delay', 10.0)  
        self.prefix = chatbox_config.get('prefix', '[Gabriel] ')
        self.enable_typing_indicator = chatbox_config.get('enable_typing_indicator', True)
        
        
        filter_config = self.config.get('filter', {})
        self.strip_markdown = filter_config.get('strip_markdown', True)
        self.remove_special_chars = filter_config.get('remove_special_chars', False)
        self.split_long_messages = filter_config.get('split_long_messages', True)
        self.message_delay = filter_config.get('message_delay', 2.0)  

        
        try:
            self.client = SimpleUDPClient(self.host, self.port)
            logger.info(f"VRChat OSC client initialized - sending to {self.host}:{self.port}")
        except Exception as e:
            logger.error(f"Failed to initialize VRChat OSC client: {e}")
            self.enabled = False
            self.client = None
        
        
        self.last_message_time = 0
        self.is_typing = False
        self.last_speech_end_time = 0.0
        self.app_start_time = time.time()
        
        
        self._current_send_task = None
        self._message_counter = 0
        
        
        ui_cfg = self.config.get('chatbox_ui', {})
        self.ui_enabled = bool(ui_cfg.get('enabled', False))
        self.ui_refresh_seconds = float(ui_cfg.get('idle_refresh_seconds', 30))
        self.ui_show_timezone = bool(ui_cfg.get('show_timezone', True))
        self.ui_title = str(ui_cfg.get('title', 'Gabriel - Hoppou.ai'))
        self.ui_divider = str(ui_cfg.get('divider', '---------------------------------------------'))
        self.ui_prompt_line = str(ui_cfg.get('prompt_line', 'Ask Anything!'))
        self.ui_template = ui_cfg.get('message_template')
        self._last_idle_ui_sent = 0.0
        
        self.ui_two_part_enabled = bool(ui_cfg.get('two_part_enabled', False))
        self.marquee_interval_seconds = float(ui_cfg.get('marquee_interval_seconds', 1.0))
        self.marquee_window_chars = int(ui_cfg.get('marquee_window_chars', 40))
        self.marquee_scroll_step = int(ui_cfg.get('marquee_scroll_step', 3))
        self.marquee_mode = str(ui_cfg.get('marquee_mode', 'paginate'))
        self._ui_tasks: Dict[str, asyncio.Task] = {}
        self._ui_states: Dict[str, Dict[str, int]] = {}
        self.ui_empty_ticks_to_idle = int(ui_cfg.get('empty_ticks_to_idle', 2))

    def _paginate_text(self, text: str, size: int) -> list[str]:
        if not text:
            return []
        text = text.strip()
        pages = []
        remaining = text
        while remaining:
            if len(remaining) <= size:
                pages.append(remaining)
                break
            
            split_pos = -1
            for i in range(size, max(size-120, 0), -1):
                if remaining[i-1] in '.!?':
                    split_pos = i
                    break
            if split_pos == -1:
                
                split_pos = remaining.rfind(' ', 0, size)
            if split_pos <= 0:
                split_pos = size
            pages.append(remaining[:split_pos].strip())
            remaining = remaining[split_pos:].strip()
        return pages
        
    def _clean_text(self, text: str) -> str:
        """
        Clean and format text for VRChat chatbox display.
        
        Args:
            text: Raw text to clean
            
        Returns:
            Cleaned text suitable for VRChat chatbox
        """
        if not text:
            return ""
            
        
        if self.strip_markdown:
            
            text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)  
            text = re.sub(r'\*(.*?)\*', r'\1', text)      
            text = re.sub(r'`(.*?)`', r'\1', text)        
            text = re.sub(r'```[\s\S]*?```', '', text)    
            text = re.sub(r'#{1,6}\s*(.*)', r'\1', text)
            text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)  
        
        
        if self.remove_special_chars:
            text = re.sub(r'[^\w\s.,!?;:-]', '', text)
        
        
        try:
            lines = text.splitlines()
            cleaned_lines = []
            for ln in lines:
                
                cleaned = ' '.join(ln.split())
                if cleaned:
                    cleaned_lines.append(cleaned)
            
            if len(cleaned_lines) > 9:
                cleaned_lines = cleaned_lines[-9:]
            result = '\n'.join(cleaned_lines)
            return result.strip()
        except Exception:
            return ' '.join(text.split()).strip()
    
    def _split_message(self, text: str) -> list[str]:
        """
        Split a long message into multiple parts that fit VRChat's character limit.
        
        Args:
            text: Text to split
            
        Returns:
            List of text chunks
        """
        if not text:
            return []
            
        
        available_length = self.max_length - len(self.prefix)
        
        if len(text) <= available_length:
            return [text]
        
        
        chunks = []
        remaining = text
        
        while remaining:
            if len(remaining) <= available_length:
                chunks.append(remaining)
                break
                
            
            sentence_end = -1
            for i in range(available_length, 0, -1):
                if remaining[i-1] in '.!?':
                    sentence_end = i
                    break
            
            if sentence_end > 0:
                chunks.append(remaining[:sentence_end].strip())
                remaining = remaining[sentence_end:].strip()
            else:
                
                space_pos = remaining.rfind(' ', 0, available_length)
                if space_pos > 0:
                    chunks.append(remaining[:space_pos].strip())
                    remaining = remaining[space_pos:].strip()
                else:
                    
                    chunks.append(remaining[:available_length])
                    remaining = remaining[available_length:]
        
        return [chunk for chunk in chunks if chunk.strip()]
    
    def set_typing_indicator(self, typing: bool) -> None:
        """
        Set the typing indicator in VRChat.
        
        Args:
            typing: True to show typing indicator, False to hide
        """
        if not self.enabled or not self.client or not self.enable_typing_indicator:
            return
            
        try:
            self.client.send_message("/chatbox/typing", typing)
            self.is_typing = typing
            logger.debug(f"VRChat typing indicator: {'ON' if typing else 'OFF'}")
        except Exception as e:
            logger.error(f"Failed to set VRChat typing indicator: {e}")
    
    async def _send_chunks_sequentially(self, chunks: list[str], message_id: int) -> None:
        """
        Send message chunks sequentially with delays, but only if this is the current message.
        
        Args:
            chunks: List of text chunks to send
            message_id: Unique ID for this message
        """
        try:
            for i, chunk in enumerate(chunks):
                
                if message_id != self._message_counter:
                    logger.debug(f"Message {message_id} cancelled - superseded by {self._message_counter}")
                    return
                
                chunk_with_prefix = self.prefix + chunk
                if len(chunks) > 1:
                    chunk_with_prefix += f" ({i+1}/{len(chunks)})"
                
                
                if not self.client:
                    return
                self.client.send_message(
                    "/chatbox/input",
                    [chunk_with_prefix, self.send_immediately, self.notification_sound]
                )
                
                logger.info(f"Sent VRChat message chunk {i+1}/{len(chunks)}: {chunk_with_prefix[:50]}...")
                
                
                if i < len(chunks) - 1:
                    await asyncio.sleep(self.message_delay)
                    
                    if message_id != self._message_counter:
                        logger.debug(f"Message {message_id} cancelled during delay")
                        return
                        
        except asyncio.CancelledError:
            logger.debug(f"Message {message_id} sending was cancelled")
            raise
        except Exception as e:
            logger.error(f"Failed to send VRChat message chunks: {e}")

    async def send_message(self, text: str) -> None:
        """
        Send a message to VRChat chatbox, cancelling any previous message.
        
        Args:
            text: Text message to send
        """
        if not self.enabled or not self.client:
            return
            
        if not text or not text.strip():
            return
        
        
        if self._current_send_task and not self._current_send_task.done():
            self._current_send_task.cancel()
            logger.debug("Cancelled previous message sending task")
        
        
        self._message_counter += 1
        current_message_id = self._message_counter
            
        try:
            
            cleaned_text = self._clean_text(text)
            if not cleaned_text:
                return
            
            
            prefixed_text = self.prefix + cleaned_text
            
            
            if len(prefixed_text) > self.max_length and self.split_long_messages:
                chunks = self._split_message(cleaned_text)
                
                
                self._current_send_task = asyncio.create_task(
                    self._send_chunks_sequentially(chunks, current_message_id)
                )
            else:
                
                if len(prefixed_text) > self.max_length:
                    prefixed_text = prefixed_text[:self.max_length-3] + "..."
                
                
                
                try:
                    self.client.send_message(
                        "/chatbox/input",
                        [prefixed_text, self.send_immediately, self.notification_sound]
                    )
                    logger.info(f"Sent VRChat message: {prefixed_text[:50]}...")
                except Exception as osc_send_error:
                    logger.error(f"OSC send error: {osc_send_error}")
                    
            
            
            if self.is_typing:
                try:
                    self.set_typing_indicator(False)
                except Exception as typing_error:
                    logger.warning(f"Error clearing typing indicator: {typing_error}")
            
            self.last_message_time = time.time()
            
        except Exception as e:
            logger.error(f"Failed to send VRChat message: {e}")
            
    
    def clear_chatbox(self) -> None:
        """
        Clear the VRChat chatbox by sending an empty message.
        """
        if not self.enabled or not self.client:
            return
            
        try:
            self.client.send_message("/chatbox/input", ["", True, False])
            logger.debug("Cleared VRChat chatbox")
        except Exception as e:
            logger.error(f"Failed to clear VRChat chatbox: {e}")

    def _format_local_time(self) -> str:
        try:
            now = datetime.now().astimezone()
            t = now.strftime('%I:%M%p').lstrip('0')
            if self.ui_show_timezone:
                tz = now.tzname() or ''
                if tz:
                    return f"{t} {tz}"
            return t
        except Exception:
            return time.strftime('%I:%M%p').lstrip('0')

    def _format_active_time(self) -> str:
        try:
            seconds = int(max(0, time.time() - (self.app_start_time or time.time())))
            h = seconds // 3600
            m = (seconds % 3600) // 60
            s = seconds % 60
            if h > 0:
                return f"{h}:{m:02d}:{s:02d}"
            return f"{m:02d}:{s:02d}"
        except Exception:
            return "00:00"

    def _get_current_avatar_name(self) -> str:
        try:
            path = os.path.join(os.getcwd(), 'last_avatar.json')
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                name = data.get('name') or ''
                if name:
                    return name
        except Exception:
            pass
        return "Unknown"

    def _build_idle_ui_message(self) -> str:
        title = self.ui_title
        now_str = self._format_local_time()
        divider = self.ui_divider
        prompt_line = self.ui_prompt_line
        active_time = self._format_active_time()
        avatar = self._get_current_avatar_name()
        if self.ui_template and isinstance(self.ui_template, str) and self.ui_template.strip():
            try:
                msg = self.ui_template.format(title=title, time=now_str, divider=divider, prompt_line=prompt_line, active_time=active_time, avatar=avatar)
            except Exception:
                msg = f"{title}\n{now_str}\n{divider}\n{prompt_line}\nActive time: {active_time}\nCurrent Avatar: {avatar}"
        else:
            msg = f"{title}\n{now_str}\n{divider}\n{prompt_line}\nActive time: {active_time}\nCurrent Avatar: {avatar}"
        if len(msg) > self.max_length:
            try:
                lines = msg.split('\n')
                if len(lines) >= 6:
                    base = '\n'.join(lines[:5]) + '\nCurrent Avatar: '
                    remain = self.max_length - len(base)
                    if remain > 3:
                        avatar_trim = avatar[:remain]
                        msg = base + avatar_trim
                    else:
                        msg = '\n'.join(lines[:5])
            except Exception:
                msg = msg[:self.max_length]
        return msg

    def maybe_send_idle_ui(self) -> bool:
        if not self.enabled or not self.client or not self.ui_enabled:
            return False
        now = time.time()
        if self.is_typing:
            return False
        if self._current_send_task is not None and not self._current_send_task.done():
            return False
        if self.last_message_time and (now - self.last_message_time) < 0.4:
            return False
        if self._last_idle_ui_sent and (now - self._last_idle_ui_sent) < self.ui_refresh_seconds:
            return False
        try:
            text = self._build_idle_ui_message()
            self.client.send_message("/chatbox/input", [text, True, False])
            self._last_idle_ui_sent = now
            self.last_message_time = now
            return True
        except Exception as e:
            logger.error(f"Failed to send idle UI message: {e}")
            return False
    
    async def send_ai_response(self, text: str) -> None:
        """
        Send Gabriel's response to VRChat with appropriate handling.
        
        This method provides the main interface for sending Gabriel's responses,
        including typing indicators and auto-clearing functionality.
        
        Args:
            text: Gabriel's response text to send
        """
        if not self.enabled:
            return
            
        if not text or not text.strip():
            return
        
        
        if self.enable_typing_indicator:
            self.set_typing_indicator(True)
            await asyncio.sleep(0.5)  
        
        
        await self.send_message(text)
        
        
        if self.auto_clear_delay > 0:
            
            asyncio.create_task(self._auto_clear_after_delay())

    async def send_two_part_ui(self, thinking: str, final: str, divider: Optional[str] = None, send_immediately: Optional[bool] = None, notification_sound: Optional[bool] = None) -> None:
        if not self.enabled or not self.client:
            return
        if not divider:
            divider = self.ui_divider
        thinking_text = self._clean_text(thinking or '')
        final_text = self._clean_text(final or '')
        assembled = f"{thinking_text}\n{divider}\n{final_text}" if (thinking_text or final_text) else ''
        if not assembled:
            return
        if send_immediately is None:
            send_immediately = self.send_immediately
        if notification_sound is None:
            notification_sound = self.notification_sound
        
        try:
            if not self.client:
                return
            prefixed = (self.prefix or '') + assembled
            if len(prefixed) > self.max_length:
                
                prefixed = prefixed[: self.max_length - 3] + '...'
            try:
                self.client.send_message("/chatbox/input", [prefixed, send_immediately, notification_sound])
            except Exception:
                
                await self.send_message(assembled)
        except Exception:
            pass

    def start_ui_marquee(self, key: str, thinking: Union[str, Callable[[], str]], final: Union[str, Callable[[], str]], interval_seconds: Optional[float] = None, window_chars: Optional[int] = None) -> None:
        if not self.enabled or not self.client:
            return
        if interval_seconds is None:
            interval_seconds = self.marquee_interval_seconds
        if window_chars is None:
            window_chars = self.marquee_window_chars
        thinking_getter: Callable[[], str] = thinking if callable(thinking) else (lambda thinking=thinking: thinking)
        final_getter: Callable[[], str] = final if callable(final) else (lambda final=final: final)
        if key in self._ui_tasks:
            self.stop_ui_marquee(key)
        task = asyncio.create_task(self._ui_marquee_task(key, thinking_getter, final_getter, interval_seconds, window_chars))
        self._ui_tasks[key] = task
        self._ui_states[key] = {'thinking_offset': 0, 'final_offset': 0}

    def stop_ui_marquee(self, key: str) -> None:
        t = self._ui_tasks.pop(key, None)
        if t:
            t.cancel()
        try:
            self._ui_states.pop(key, None)
        except Exception:
            pass

    async def _ui_marquee_task(self, key: str, thinking_getter: Callable[[], str], final_getter: Callable[[], str], interval_seconds: float, window_chars: int) -> None:
        try:
            while True:
                try:
                    thinking_text = thinking_getter() or ''
                    final_text = final_getter() or ''
                    thinking_clean = self._clean_text(thinking_text)
                    final_clean = self._clean_text(final_text)
                    state = self._ui_states.get(key)
                    if state is None:
                        state = {'thinking_offset': 0, 'final_offset': 0}
                        self._ui_states[key] = state

                    def _visible(text: str, offset: int, window: int) -> str:
                        if not text:
                            return ''
                        if len(text) <= window:
                            return text
                        padded = text + ' ' * window
                        doubled = padded + text
                        start = offset % (len(text) + window)
                        return doubled[start:start + window]

                    
                    available = max(0, self.max_length - len(self.prefix))
                    divider_len = len(self.ui_divider)
                    label_top = "Thinking: "
                    label_bot = "Response: "
                    
                    reserved = divider_len + 2
                    per_part = max(0, (available - reserved) // 2 - len(label_top))
                    
                    if self.marquee_mode == 'paginate':
                        
                        page_size = per_part if per_part > 0 else window_chars
                        thinking_pages = self._paginate_text(thinking_clean, page_size)
                        final_pages = self._paginate_text(final_clean, page_size)
                        
                        prev_thinking = state.get('last_thinking', '')
                        prev_final = state.get('last_final', '')
                        if thinking_clean != prev_thinking:
                            state['thinking_index'] = 0
                            state['last_thinking'] = thinking_clean
                        if final_clean != prev_final:
                            state['final_index'] = 0
                            state['last_final'] = final_clean
                        thinking_index = state.get('thinking_index', 0)
                        final_index = state.get('final_index', 0)
                        if thinking_pages:
                            tp = thinking_pages[thinking_index % len(thinking_pages)]
                            tp_label = f"({thinking_index % len(thinking_pages) + 1}/{len(thinking_pages)}) "
                            top_line = f"{label_top}{tp_label}{tp}"
                        else:
                            top_line = label_top.strip()
                        if final_pages:
                            fp = final_pages[final_index % len(final_pages)]
                            fp_label = f"({final_index % len(final_pages) + 1}/{len(final_pages)}) "
                            bottom_line = f"{label_bot}{fp_label}{fp}"
                        else:
                            bottom_line = label_bot.strip()
                        assembled = f"{top_line}\n{self.ui_divider}\n{bottom_line}"
                        
                        state['thinking_index'] = (thinking_index + 1) if thinking_pages else 0
                        state['final_index'] = (final_index + 1) if final_pages else 0
                    else:
                        
                        top_window = min(window_chars, per_part) if per_part > 0 else min(window_chars, max(1, available // 2))
                        bot_window = min(window_chars, per_part) if per_part > 0 else min(window_chars, max(1, available // 2))
                        top_visible = _visible(thinking_clean, state.get('thinking_offset', 0), top_window)
                        bottom_visible = _visible(final_clean, state.get('final_offset', 0), bot_window)
                        
                        if (not thinking_clean or not thinking_clean.strip()) and (not final_clean or not final_clean.strip()):
                            empty_count = state.get('empty_count', 0) + 1
                            state['empty_count'] = empty_count
                            if empty_count >= self.ui_empty_ticks_to_idle:
                                try:
                                    self.maybe_send_idle_ui()
                                except Exception:
                                    pass
                                break
                            else:
                                
                                try:
                                    await asyncio.sleep(interval_seconds)
                                except asyncio.CancelledError:
                                    break
                                continue
                        else:
                            
                            if state.get('empty_count', 0):
                                state['empty_count'] = 0
                        top_line = f"{label_top}{top_visible}" if top_visible else label_top.strip()
                        bottom_line = f"{label_bot}{bottom_visible}" if bottom_visible else label_bot.strip()
                        assembled = f"{top_line}\n{self.ui_divider}\n{bottom_line}"
                    
                    try:
                        if not self.client:
                            continue
                        prefixed = (self.prefix or '') + assembled
                        if len(prefixed) > self.max_length:
                            prefixed = prefixed[: self.max_length - 3] + '...'
                        
                        last_sent = state.get('last_sent')
                        if last_sent == prefixed:
                            
                            pass
                        else:
                            try:
                                self.client.send_message("/chatbox/input", [prefixed, self.send_immediately, self.notification_sound])
                                state['last_sent'] = prefixed
                            except Exception:
                                
                                await self.send_message(assembled)
                                state['last_sent'] = prefixed
                    except Exception:
                        pass
                    state['thinking_offset'] = (state.get('thinking_offset', 0) + self.marquee_scroll_step) % max(1, (len(thinking_clean) + window_chars))
                    state['final_offset'] = (state.get('final_offset', 0) + self.marquee_scroll_step) % max(1, (len(final_clean) + window_chars))
                except asyncio.CancelledError:
                    break
                except Exception:
                    pass
                try:
                    await asyncio.sleep(interval_seconds)
                except asyncio.CancelledError:
                    break
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
    
    async def _auto_clear_after_delay(self) -> None:
        """
        Internal method to auto-clear the chatbox after a delay.
        """
        try:
            await asyncio.sleep(self.auto_clear_delay)
            self.clear_chatbox()
            logger.debug(f"Auto-cleared VRChat chatbox after {self.auto_clear_delay} seconds")
        except Exception as e:
            logger.error(f"Failed to auto-clear VRChat chatbox: {e}")
    
    def on_ai_speech_start(self) -> None:
        """
        Called when Gabriel starts speaking (for typing indicator).
        """
        if self.enable_typing_indicator:
            self.set_typing_indicator(True)
    
    def on_ai_speech_end(self) -> None:
        """
        Called when Gabriel finishes speaking.
        """
        if self.is_typing:
            self.set_typing_indicator(False)
        
        try:
            self.last_speech_end_time = time.time()
        except Exception:
            self.last_speech_end_time = 0.0
    
    async def shutdown(self) -> None:
        """
        Shutdown the OSC client and cleanup resources.
        """
        if self._current_send_task and not self._current_send_task.done():
            
            self._current_send_task.cancel()
            try:
                await self._current_send_task
            except asyncio.CancelledError:
                pass

    def get_status(self) -> Dict[str, Any]:
        """
        Get the current status of the OSC client.
        
        Returns:
            Dictionary containing status information
        """
        return {
            'enabled': self.enabled,
            'connected': self.client is not None,
            'host': self.host,
            'port': self.port,
            'is_typing': self.is_typing,
            'last_message_time': self.last_message_time,
            'last_speech_end_time': self.last_speech_end_time,
            'max_length': self.max_length,
            'prefix': self.prefix,
            'current_message_id': self._message_counter,
            'has_active_send_task': self._current_send_task is not None and not self._current_send_task.done()
        }



vrchat_osc_client: Optional[VRChatOSCClient] = None


def initialize_osc_client(config: Dict[str, Any]) -> VRChatOSCClient:
    """
    Initialize the global VRChat OSC client.
    
    Args:
        config: Application configuration dictionary
        
    Returns:
        Initialized VRChatOSCClient instance
    """
    global vrchat_osc_client
    vrchat_osc_client = VRChatOSCClient(config)
    return vrchat_osc_client


def get_osc_client() -> Optional[VRChatOSCClient]:
    """
    Get the global VRChat OSC client instance.
    
    Returns:
        VRChatOSCClient instance or None if not initialized
    """
    return vrchat_osc_client


async def send_to_vrchat(text: str) -> None:
    """
    Convenience function to send text to VRChat chatbox.
    
    Args:
        text: Text to send to VRChat chatbox
    """
    client = get_osc_client()
    if client:
        await client.send_ai_response(text)


def notify_ai_speech_start() -> None:
    """
    Notify OSC client that Gabriel has started speaking.
    """
    client = get_osc_client()
    if client:
        client.on_ai_speech_start()


def notify_ai_speech_end() -> None:
    """
    Notify OSC client that Gabriel has finished speaking.
    """
    client = get_osc_client()
    if client:
        client.on_ai_speech_end()


def maybe_send_idle_ui() -> bool:
    client = get_osc_client()
    if client:
        return client.maybe_send_idle_ui()
    return False

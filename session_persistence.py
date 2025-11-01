import json
import os
import time
import logging
import asyncio
from typing import Optional, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)

SESSION_FILE = "last_session.json"
DEFAULT_SAVE_INTERVAL = 30

class SessionPersistence:
    
    def __init__(self, save_interval: int = DEFAULT_SAVE_INTERVAL):
        self.save_interval = save_interval
        self.session_file = Path(SESSION_FILE)
        self.last_save_time = 0
        self._save_task = None
        self._running = False
        logger.info(f"SessionPersistence initialized with {save_interval}s save interval")
    
    def save_session_handle(self, handle: str, mode: str, metadata: Optional[Dict[str, Any]] = None):
        try:
            data = {
                "handle": handle,
                "mode": mode,
                "timestamp": time.time(),
                "metadata": metadata or {}
            }
            
            with open(self.session_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.info(f"Saved {mode} session handle to {self.session_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to save session handle: {e}")
            return False
    
    def load_session_handle(self) -> Optional[Dict[str, Any]]:
        try:
            if not self.session_file.exists():
                logger.info("No saved session handle found")
                return None
            
            with open(self.session_file, 'r') as f:
                data = json.load(f)
            
            logger.info(f"Loaded {data.get('mode', 'unknown')} session handle from {data.get('timestamp', 0)}")
            return data
        except Exception as e:
            logger.error(f"Failed to load session handle: {e}")
            return None
    
    def get_session_age(self) -> Optional[float]:
        data = self.load_session_handle()
        if data and 'timestamp' in data:
            return time.time() - data['timestamp']
        return None
    
    def clear_session_handle(self):
        try:
            if self.session_file.exists():
                self.session_file.unlink()
                logger.info("Cleared saved session handle")
            return True
        except Exception as e:
            logger.error(f"Failed to clear session handle: {e}")
            return False
    
    async def start_periodic_save(self, handle_getter, mode: str, metadata_getter=None):
        self._running = True
        logger.info(f"Started periodic session handle saving for {mode} mode")
        
        while self._running:
            try:
                await asyncio.sleep(self.save_interval)
                
                if not self._running:
                    break
                
                handle = handle_getter()
                if handle:
                    metadata = metadata_getter() if metadata_getter else None
                    self.save_session_handle(handle, mode, metadata)
                else:
                    logger.debug("No session handle available to save")
                    
            except asyncio.CancelledError:
                logger.info("Periodic save task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in periodic save: {e}")
                await asyncio.sleep(self.save_interval)
    
    def stop_periodic_save(self):
        self._running = False
        logger.info("Stopped periodic session handle saving")
    
    async def save_on_shutdown(self, handle: Optional[str], mode: str, metadata: Optional[Dict[str, Any]] = None):
        if handle:
            self.save_session_handle(handle, mode, metadata)
            logger.info(f"Saved session handle on shutdown for {mode} mode")


_global_persistence = None

def get_persistence_manager(save_interval: int = DEFAULT_SAVE_INTERVAL) -> SessionPersistence:
    global _global_persistence
    if _global_persistence is None:
        _global_persistence = SessionPersistence(save_interval)
    return _global_persistence

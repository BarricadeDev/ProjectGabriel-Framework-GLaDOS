"""
Web UI API Module
"""

import logging
import asyncio
from typing import Dict, Any, Optional
from pythonosc.udp_client import SimpleUDPClient

logger = logging.getLogger(__name__)


class VRChatControlsAPI:
    """
    API class for VRChat OSC controls including safe mode and voice toggle.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize VRChat controls API.
        
        Args:
            config: Configuration dictionary containing OSC settings
        """
        self.config = config.get('osc', {})
        self.enabled = self.config.get('enabled', False)
        
        if not self.enabled:
            logger.info("VRChat OSC controls are disabled")
            return
            
        
        self.host = self.config.get('host', '127.0.0.1')
        self.port = self.config.get('port', 9000)  
        
        
        try:
            self.client = SimpleUDPClient(self.host, self.port)
            logger.info(f"VRChat Controls API initialized - sending to {self.host}:{self.port}")
        except Exception as e:
            logger.error(f"Failed to initialize VRChat Controls API: {e}")
            self.enabled = False
            self.client = None
        
        
        self.safe_mode_enabled = False
        self.voice_enabled = True  
        
    def enable_safe_mode(self) -> Dict[str, Any]:
        """
        Enable VRChat Safe Mode using OSC /input/PanicButton.
        
        Returns:
            Dictionary with success status and message
        """
        if not self.enabled or not self.client:
            return {
                'success': False,
                'message': 'VRChat OSC controls are not available',
                'safe_mode_enabled': self.safe_mode_enabled
            }
            
        try:
            
            
            self.client.send_message("/input/PanicButton", 1)
            
            
            asyncio.create_task(self._reset_panic_button())
            
            self.safe_mode_enabled = True
            logger.info("VRChat Safe Mode enabled via OSC")
            
            return {
                'success': True,
                'message': 'Safe Mode enabled successfully',
                'safe_mode_enabled': self.safe_mode_enabled
            }
            
        except Exception as e:
            logger.error(f"Failed to enable Safe Mode: {e}")
            return {
                'success': False,
                'message': f'Failed to enable Safe Mode: {str(e)}',
                'safe_mode_enabled': self.safe_mode_enabled
            }
    
    async def _reset_panic_button(self) -> None:
        """
        Reset the panic button OSC input to 0 after a brief delay.
        """
        try:
            await asyncio.sleep(0.1)  
            if self.client:
                self.client.send_message("/input/PanicButton", 0)
                logger.debug("Reset PanicButton OSC input to 0")
        except Exception as e:
            logger.error(f"Failed to reset PanicButton: {e}")
    
    def toggle_voice(self, enable: Optional[bool] = None) -> Dict[str, Any]:
        """
        Toggle VRChat voice using OSC /input/Voice.
        
        Args:
            enable: Optional boolean to explicitly set voice state.
                   If None, will toggle current state.
        
        Returns:
            Dictionary with success status and message
        """
        if not self.enabled or not self.client:
            return {
                'success': False,
                'message': 'VRChat OSC controls are not available',
                'voice_enabled': self.voice_enabled
            }
            
        try:
            
            if enable is None:
                new_voice_state = not self.voice_enabled
            else:
                new_voice_state = enable
            
            
            
            
            
            
            
            self.client.send_message("/input/Voice", 1)
            
            
            asyncio.create_task(self._reset_voice_button())
            
            self.voice_enabled = new_voice_state
            action = "enabled" if new_voice_state else "disabled"
            logger.info(f"VRChat Voice {action} via OSC")
            
            return {
                'success': True,
                'message': f'Voice {action} successfully',
                'voice_enabled': self.voice_enabled
            }
            
        except Exception as e:
            logger.error(f"Failed to toggle voice: {e}")
            return {
                'success': False,
                'message': f'Failed to toggle voice: {str(e)}',
                'voice_enabled': self.voice_enabled
            }
    
    async def _reset_voice_button(self) -> None:
        """
        Reset the voice button OSC input to 0 after a brief delay.
        """
        try:
            await asyncio.sleep(0.1)  
            if self.client:
                self.client.send_message("/input/Voice", 0)
                logger.debug("Reset Voice OSC input to 0")
        except Exception as e:
            logger.error(f"Failed to reset Voice button: {e}")
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get the current status of VRChat controls.
        
        Returns:
            Dictionary containing control status information
        """
        return {
            'enabled': self.enabled,
            'connected': self.client is not None,
            'host': self.host,
            'port': self.port,
            'safe_mode_enabled': self.safe_mode_enabled,
            'voice_enabled': self.voice_enabled
        }



vrchat_controls_api: Optional[VRChatControlsAPI] = None


def initialize_vrchat_controls(config: Dict[str, Any]) -> VRChatControlsAPI:
    """
    Initialize the global VRChat controls API.
    
    Args:
        config: Application configuration dictionary
        
    Returns:
        Initialized VRChatControlsAPI instance
    """
    global vrchat_controls_api
    vrchat_controls_api = VRChatControlsAPI(config)
    return vrchat_controls_api


def get_vrchat_controls() -> Optional[VRChatControlsAPI]:
    """
    Get the global VRChat controls API instance.
    
    Returns:
        VRChatControlsAPI instance or None if not initialized
    """
    return vrchat_controls_api


def enable_safe_mode() -> Dict[str, Any]:
    """
    Convenience function to enable VRChat Safe Mode.
    
    Returns:
        Dictionary with success status and message
    """
    controls = get_vrchat_controls()
    if controls:
        return controls.enable_safe_mode()
    else:
        return {
            'success': False,
            'message': 'VRChat controls not initialized',
            'safe_mode_enabled': False
        }


def toggle_voice(enable: Optional[bool] = None) -> Dict[str, Any]:
    """
    Convenience function to toggle VRChat voice.
    
    Args:
        enable: Optional boolean to explicitly set voice state
    
    Returns:
        Dictionary with success status and message
    """
    controls = get_vrchat_controls()
    if controls:
        return controls.toggle_voice(enable)
    else:
        return {
            'success': False,
            'message': 'VRChat controls not initialized',
            'voice_enabled': True
        }


def get_controls_status() -> Dict[str, Any]:
    """
    Convenience function to get VRChat controls status.
    
    Returns:
        Dictionary containing control status information
    """
    controls = get_vrchat_controls()
    if controls:
        return controls.get_status()
    else:
        return {
            'enabled': False,
            'connected': False,
            'host': 'N/A',
            'port': 0,
            'safe_mode_enabled': False,
            'voice_enabled': True
        }
"""
Chat WebUI API
"""

import asyncio
import logging
import json
from typing import Optional, Dict, Any, Set
from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)


_active_session = None
_session_lock = threading.Lock()

_session_manager = None
_manager_lock = threading.Lock()


_websocket_connections: Set[WebSocket] = set()
_websocket_lock = threading.Lock()

class WebSocketMessage(BaseModel):
    """Model for WebSocket messages."""
    type: str
    data: Dict[str, Any]
    timestamp: float

class ChatMessage(BaseModel):
    """Model for incoming chat messages."""
    message: str
    turn_complete: bool = True
    system_instruction: bool = False

class ChatResponse(BaseModel):
    """Model for API responses."""
    success: bool
    message: str
    timestamp: float

class VoiceToggleRequest(BaseModel):
    """Model for voice toggle requests."""
    enable: Optional[bool] = None

class V2ModeToggleRequest(BaseModel):
    """Model for V2 mode toggle requests."""
    enable_v2: bool

class GabrielChatAPI:
    """FastAPI application for Gabriel chat API."""
    
    def __init__(self, host: str = "127.0.0.1", port: int = 8000):
        self.host = host
        self.port = port
        self.app = FastAPI(
            title="Gabriel Chat API",
            description="REST API for sending messages to Gabriel's Gemini Live session",
            version="1.0.0"
        )
        
        
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        
        webui_path = Path(__file__).parent / "webui"
        if webui_path.exists():
            self.app.mount("/ui", StaticFiles(directory=str(webui_path), html=True), name="webui")
        
        
        self._setup_routes()
        
        
        self._server = None
        self._server_task = None
    
    def _setup_routes(self):
        """Set up API routes."""
        
        @self.app.get("/")
        async def root():
            """Root endpoint with API information."""
            return {
                "name": "Gabriel Chat API",
                "version": "1.0.0",
                "description": "Send text messages to Gabriel's Gemini Live session",
                "endpoints": {
                    "POST /api/chat/send": "Send a text message to Gabriel",
                    "GET /api/chat/status": "Get session status",
                    "WS /api/chat/ws": "WebSocket for real-time response monitoring",
                    "GET /api/personalities": "Get all available personalities",
                    "POST /api/personalities/switch/{personality_id}": "Switch to a specific personality",
                    "GET /api/vrchat/controls/status": "Get VRChat controls status",
                    "POST /api/vrchat/controls/safe-mode": "Enable VRChat Safe Mode",
                    "POST /api/vrchat/controls/voice/toggle": "Toggle VRChat voice",
                    "GET /api/v2/status": "Get V2 mode status",
                    "POST /api/v2/toggle": "Toggle between V1 and V2 modes",
                    "POST /api/session/reconnect": "Reconnect using last saved session handle",
                    "POST /api/session/fresh-start": "Clear saved session and restart fresh",
                    "GET /api/memory/list": "List all memories with optional filtering",
                    "GET /api/memory/search": "Search memories by content or key",
                    "GET /api/memory/{key}": "Get a specific memory by key",
                    "POST /api/memory": "Create a new memory",
                    "PUT /api/memory/{key}": "Update an existing memory",
                    "DELETE /api/memory/{key}": "Delete a memory by key",
                    "GET /api/memory/stats": "Get memory statistics",
                    "GET /health": "Health check",
                    "GET /ui/": "WebUI Control Panel"
                }
            }
        
        @self.app.get("/health")
        async def health():
            """Health check endpoint."""
            return {
                "status": "healthy",
                "timestamp": time.time(),
                "session_active": _active_session is not None
            }
        
        @self.app.get("/api/chat/status")
        async def get_status():
            """Get current session status."""
            with _session_lock:
                session_active = _active_session is not None
            
            with _websocket_lock:
                connected_clients = len(_websocket_connections)
            
            return ChatResponse(
                success=True,
                message=f"Session {'active' if session_active else 'inactive'}, {connected_clients} WebSocket clients",
                timestamp=time.time()
            )
        
        @self.app.websocket("/api/chat/ws")
        async def websocket_endpoint(websocket: WebSocket):
            """WebSocket endpoint for real-time response monitoring."""
            await websocket.accept()
            
            with _websocket_lock:
                _websocket_connections.add(websocket)
            
            logger.info(f"WebSocket client connected. Total clients: {len(_websocket_connections)}")
            
            try:
                
                await websocket.send_json({
                    "type": "connection",
                    "data": {
                        "status": "connected",
                        "message": "WebSocket connection established"
                    },
                    "timestamp": time.time()
                })
                
                
                while True:
                    try:
                        
                        message = await websocket.receive_json()
                        
                        if message.get("type") == "ping":
                            await websocket.send_json({
                                "type": "pong",
                                "timestamp": time.time()
                            })
                        
                    except asyncio.TimeoutError:
                        
                        await websocket.send_json({
                            "type": "heartbeat",
                            "timestamp": time.time()
                        })
                        
            except WebSocketDisconnect:
                logger.info("WebSocket client disconnected")
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
            finally:
                with _websocket_lock:
                    _websocket_connections.discard(websocket)
                logger.info(f"WebSocket client removed. Total clients: {len(_websocket_connections)}")
        
        @self.app.post("/api/chat/send")
        async def send_message(chat_message: ChatMessage, background_tasks: BackgroundTasks):
            """Send a text message to the active Gemini Live session."""
            
            if not chat_message.message.strip():
                raise HTTPException(
                    status_code=400,
                    detail="Message cannot be empty"
                )
            
            with _session_lock:
                if _active_session is None:
                    raise HTTPException(
                        status_code=503,
                        detail="No active Gemini Live session"
                    )
                
                session = _active_session
            
            try:
                
                final_message = chat_message.message
                if chat_message.system_instruction:
                    final_message = f"SYSTEM INSTRUCTION: {chat_message.message}"
                
                
                message_type = "system_instruction" if chat_message.system_instruction else "user_message"
                try:
                    await broadcast_to_websockets(message_type, {
                        "text": chat_message.message,
                        "message": f"{'[SYSTEM] ' if chat_message.system_instruction else '[USER] '}{chat_message.message}"
                    })
                except Exception as broadcast_error:
                    logger.warning(f"Failed to broadcast message to WebSocket clients: {broadcast_error}")
                    
                
                
                await self._send_to_session(session, final_message, chat_message.turn_complete)
                
                message_type_desc = "system instruction" if chat_message.system_instruction else "message"
                logger.info(f"Sent {message_type_desc} via API: {final_message[:100]}...")
                
                return ChatResponse(
                    success=True,
                    message=f"{'System instruction' if chat_message.system_instruction else 'Message'} sent successfully",
                    timestamp=time.time()
                )
                
            except Exception as e:
                logger.error(f"Failed to send message via API: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to send message: {str(e)}"
                )
        
        @self.app.get("/api/personalities")
        async def get_personalities():
            """Get all available personalities."""
            try:
                
                import sys
                import os
                sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
                from personalities import personality_manager
                
                result = personality_manager.list_personalities()
                
                if result["success"]:
                    return {
                        "success": True,
                        "personalities": result["personalities"],
                        "count": result["count"],
                        "current": result["current"],
                        "timestamp": time.time()
                    }
                else:
                    raise HTTPException(
                        status_code=500,
                        detail=result["message"]
                    )
                    
            except ImportError as e:
                logger.error(f"Failed to import personalities module: {e}")
                raise HTTPException(
                    status_code=503,
                    detail="Personalities module not available"
                )
            except Exception as e:
                logger.error(f"Failed to get personalities: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to get personalities: {str(e)}"
                )
        
        @self.app.post("/api/personalities/switch/{personality_id}")
        async def switch_personality(personality_id: str):
            """Switch to a specific personality."""
            
            if not personality_id.strip():
                raise HTTPException(
                    status_code=400,
                    detail="Personality ID cannot be empty"
                )
            
            with _session_lock:
                if _active_session is None:
                    raise HTTPException(
                        status_code=503,
                        detail="No active Gemini Live session"
                    )
                
                session = _active_session
            
            try:
                
                import sys
                import os
                sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
                from personalities import personality_manager
                
                
                result = personality_manager.switch_personality(personality_id)
                
                if result["success"]:
                    
                    system_message = f"SYSTEM INSTRUCTION: Switch to {result['personality']['name']} personality mode. {result.get('instruction', '')}"
                    
                    
                    try:
                        await broadcast_to_websockets("system_instruction", {
                            "text": f"Switching to {result['personality']['name']} personality",
                            "message": f"[SYSTEM] Personality switched to: {result['personality']['name']}"
                        })
                    except Exception as broadcast_error:
                        logger.warning(f"Failed to broadcast personality switch to WebSocket clients: {broadcast_error}")
                    
                    
                    await self._send_to_session(session, system_message, True)
                    
                    logger.info(f"Switched to personality: {personality_id}")
                    
                    return {
                        "success": True,
                        "message": f"Switched to {result['personality']['name']} personality",
                        "personality": result['personality'],
                        "personality_id": personality_id,
                        "timestamp": time.time()
                    }
                else:
                    raise HTTPException(
                        status_code=400,
                        detail=result["message"]
                    )
                    
            except ImportError as e:
                logger.error(f"Failed to import personalities module: {e}")
                raise HTTPException(
                    status_code=503,
                    detail="Personalities module not available"
                )
            except Exception as e:
                logger.error(f"Failed to switch personality: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to switch personality: {str(e)}"
                )
        
        @self.app.get("/api/v2/status")
        async def get_v2_mode_status():
            """Get V2 mode status."""
            try:
                
                import sys
                import os
                sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
                
                
                v2_available = False
                try:
                    import main
                    v2_available = getattr(main, 'V2_AVAILABLE', False)
                except ImportError:
                    
                    try:
                        import v2
                        v2_available = True
                    except ImportError:
                        v2_available = False
                
                
                
                current_v2_mode = False
                
                return {
                    "success": True,
                    "v2_available": v2_available,
                    "v2_mode_enabled": current_v2_mode,
                    "message": f"V2 mode is {'available' if v2_available else 'not available'}",
                    "timestamp": time.time()
                }
                
            except Exception as e:
                logger.error(f"Failed to get V2 mode status: {e}")
                return {
                    "success": False,
                    "v2_available": False,
                    "v2_mode_enabled": False,
                    "message": f"Failed to get V2 mode status: {str(e)}",
                    "timestamp": time.time()
                }
        
        @self.app.post("/api/v2/toggle")
        async def toggle_v2_mode(request: V2ModeToggleRequest):
            """Toggle between V1 and V2 modes."""
            
            with _session_lock:
                if _active_session is None:
                    raise HTTPException(
                        status_code=503,
                        detail="No active Gemini Live session"
                    )
                
                session = _active_session
            
            try:
                
                v2_available = False
                try:
                    import sys
                    import os
                    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
                    import main
                    v2_available = getattr(main, 'V2_AVAILABLE', False)
                except ImportError:
                    
                    try:
                        import v2
                        v2_available = True
                    except ImportError:
                        v2_available = False
                
                if request.enable_v2 and not v2_available:
                    raise HTTPException(
                        status_code=400,
                        detail="V2 mode is not available on this system"
                    )
                
                
                if request.enable_v2:
                    if not v2_available:
                        raise HTTPException(
                            status_code=400,
                            detail="V2 mode is not available"
                        )
                    
                    
                    system_message = "SYSTEM INSTRUCTION: Please switch to V2 mode for enhanced voice quality. Use the switch_to_v2_mode function with reason: User requested V2 mode via WebUI"
                    
                    
                    try:
                        await broadcast_to_websockets("system", {
                            "message": "Requesting switch to V2 mode with enhanced voice quality..."
                        })
                    except Exception as broadcast_error:
                        logger.warning(f"Failed to broadcast V2 mode switch to WebSocket clients: {broadcast_error}")
                    
                    
                    await self._send_to_session(session, system_message, True)
                    
                    logger.info("V2 mode switch requested via API")
                    
                    return {
                        "success": True,
                        "message": "Requesting switch to V2 mode with enhanced voice quality",
                        "v2_mode_enabled": True,
                        "mode": "V2",
                        "timestamp": time.time()
                    }
                else:
                    
                    system_message = "SYSTEM INSTRUCTION: Please switch to V1 mode. Use the switch_to_v1_mode function with reason: User requested V1 mode via WebUI"
                    
                    
                    try:
                        await broadcast_to_websockets("system", {
                            "message": "Requesting switch to V1 mode..."
                        })
                    except Exception as broadcast_error:
                        logger.warning(f"Failed to broadcast V1 mode switch to WebSocket clients: {broadcast_error}")
                    
                    
                    await self._send_to_session(session, system_message, True)
                    
                    logger.info("V1 mode switch requested via API")
                    
                    return {
                        "success": True,
                        "message": "Requesting switch to V1 mode",
                        "v2_mode_enabled": False,
                        "mode": "V1",
                        "timestamp": time.time()
                    }
                    
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Failed to toggle V2 mode: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to toggle V2 mode: {str(e)}"
                )
        
        @self.app.post("/api/session/reconnect")
        async def reconnect_with_saved_session():
            """Attempt to reconnect using the last saved session handle."""
            try:
                with _manager_lock:
                    manager = _session_manager
                
                if not manager:
                    raise HTTPException(
                        status_code=503,
                        detail="Session manager not available"
                    )
                
                if not manager.persistence:
                    raise HTTPException(
                        status_code=503,
                        detail="Session persistence is not enabled"
                    )
                
                saved_data = manager.persistence.load_session_handle()
                
                if not saved_data:
                    raise HTTPException(
                        status_code=404,
                        detail="No saved session handle found"
                    )
                
                session_age = manager.persistence.get_session_age()
                if session_age and session_age > 3600:
                    logger.warning(f"Saved session is {session_age:.0f}s old, reconnection may fail")
                
                mode = saved_data.get('mode', 'unknown')
                handle = saved_data.get('handle')
                
                if not handle:
                    raise HTTPException(
                        status_code=400,
                        detail="Saved session data is invalid"
                    )
                
                manager.request_reconnect()
                logger.info(f"Reconnection requested with saved {mode} session handle (age: {session_age:.0f}s)")
                
                await broadcast_to_websockets("system", {
                    "message": f"Reconnecting with saved {mode} session..."
                })
                
                return {
                    "success": True,
                    "message": f"Reconnection initiated with saved {mode} session",
                    "mode": mode,
                    "session_age_seconds": session_age,
                    "handle_preview": handle[:20] + "..." if len(handle) > 20 else handle,
                    "timestamp": time.time()
                }
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Failed to reconnect with saved session: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to reconnect: {str(e)}"
                )
        
        @self.app.post("/api/session/fresh-start")
        async def fresh_start():
            """Clear saved session handle and restart with a fresh session."""
            try:
                with _manager_lock:
                    manager = _session_manager
                
                if not manager:
                    raise HTTPException(
                        status_code=503,
                        detail="Session manager not available"
                    )
                
                manager.request_fresh_start()
                logger.info("Fresh start requested via API endpoint")
                
                await broadcast_to_websockets("system", {
                    "message": "Fresh start requested - disconnecting and restarting..."
                })
                
                return {
                    "success": True,
                    "message": "Fresh start initiated - AI will disconnect and restart with fresh session",
                    "timestamp": time.time()
                }
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Failed to request fresh start: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to request fresh start: {str(e)}"
                )
        
        @self.app.get("/api/vrchat/controls/status")
        async def get_vrchat_controls_status():
            """Get VRChat controls status."""
            try:
                
                import sys
                import os
                sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
                from api.webui import get_controls_status
                
                status = get_controls_status()
                return {
                    "success": True,
                    "controls": status,
                    "timestamp": time.time()
                }
                
            except ImportError as e:
                logger.error(f"Failed to import webui module: {e}")
                raise HTTPException(
                    status_code=503,
                    detail="VRChat controls module not available"
                )
            except Exception as e:
                logger.error(f"Failed to get VRChat controls status: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to get VRChat controls status: {str(e)}"
                )
        
        @self.app.post("/api/vrchat/controls/safe-mode")
        async def enable_vrchat_safe_mode():
            """Enable VRChat Safe Mode."""
            try:
                
                import sys
                import os
                sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
                from api.webui import enable_safe_mode
                
                result = enable_safe_mode()
                
                
                try:
                    await broadcast_to_websockets("system", {
                        "message": f"VRChat Safe Mode: {result['message']}"
                    })
                except Exception as broadcast_error:
                    logger.warning(f"Failed to broadcast safe mode action to WebSocket clients: {broadcast_error}")
                
                if result["success"]:
                    logger.info("VRChat Safe Mode enabled via API")
                    return {
                        "success": True,
                        "message": result["message"],
                        "safe_mode_enabled": result["safe_mode_enabled"],
                        "timestamp": time.time()
                    }
                else:
                    raise HTTPException(
                        status_code=500,
                        detail=result["message"]
                    )
                    
            except ImportError as e:
                logger.error(f"Failed to import webui module: {e}")
                raise HTTPException(
                    status_code=503,
                    detail="VRChat controls module not available"
                )
            except Exception as e:
                logger.error(f"Failed to enable VRChat Safe Mode: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to enable VRChat Safe Mode: {str(e)}"
                )
        
        @self.app.post("/api/vrchat/controls/voice/toggle")
        async def toggle_vrchat_voice(request: VoiceToggleRequest):
            """Toggle VRChat voice."""
            try:
                
                import sys
                import os
                sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
                from api.webui import toggle_voice
                
                result = toggle_voice(request.enable)
                
                
                try:
                    await broadcast_to_websockets("system", {
                        "message": f"VRChat Voice: {result['message']}"
                    })
                except Exception as broadcast_error:
                    logger.warning(f"Failed to broadcast voice toggle action to WebSocket clients: {broadcast_error}")
                
                if result["success"]:
                    action = "enabled" if result["voice_enabled"] else "disabled"
                    logger.info(f"VRChat Voice {action} via API")
                    return {
                        "success": True,
                        "message": result["message"],
                        "voice_enabled": result["voice_enabled"],
                        "timestamp": time.time()
                    }
                else:
                    raise HTTPException(
                        status_code=500,
                        detail=result["message"]
                    )
                    
            except ImportError as e:
                logger.error(f"Failed to import webui module: {e}")
                raise HTTPException(
                    status_code=503,
                    detail="VRChat controls module not available"
                )
            except Exception as e:
                logger.error(f"Failed to toggle VRChat voice: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to toggle VRChat voice: {str(e)}"
                )
        
        
        @self.app.get("/api/memory/list")
        async def list_memories(category: Optional[str] = None, memory_type: Optional[str] = None, limit: int = 50):
            """List all memories with optional filtering."""
            try:
                
                import sys
                import os
                sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
                from tools.memory import memory_system
                
                result = memory_system.list_memories(category=category, memory_type=memory_type, limit=limit)
                
                if result["success"]:
                    return {
                        "success": True,
                        "memories": result["memories"],
                        "count": result["count"],
                        "timestamp": time.time()
                    }
                else:
                    raise HTTPException(
                        status_code=500,
                        detail=result["message"]
                    )
                    
            except ImportError as e:
                logger.error(f"Failed to import memory module: {e}")
                raise HTTPException(
                    status_code=503,
                    detail="Memory module not available"
                )
            except Exception as e:
                logger.error(f"Failed to list memories: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to list memories: {str(e)}"
                )
        
        @self.app.get("/api/memory/search")
        async def search_memories(q: str, memory_type: Optional[str] = None, limit: int = 20):
            """Search memories by content or key."""
            try:
                if not q.strip():
                    raise HTTPException(
                        status_code=400,
                        detail="Search query cannot be empty"
                    )
                
                
                import sys
                import os
                sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
                from tools.memory import memory_system
                
                result = memory_system.search_memories(search_term=q, memory_type=memory_type, limit=limit)
                
                if result["success"]:
                    return {
                        "success": True,
                        "memories": result["memories"],
                        "count": result["count"],
                        "search_term": result["search_term"],
                        "timestamp": time.time()
                    }
                else:
                    raise HTTPException(
                        status_code=500,
                        detail=result["message"]
                    )
                    
            except ImportError as e:
                logger.error(f"Failed to import memory module: {e}")
                raise HTTPException(
                    status_code=503,
                    detail="Memory module not available"
                )
            except Exception as e:
                logger.error(f"Failed to search memories: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to search memories: {str(e)}"
                )
        
        @self.app.get("/api/memory/stats")
        async def get_memory_stats():
            """Get memory statistics."""
            try:
                
                import sys
                import os
                sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
                
                
                try:
                    from tools.memory import memory_system
                    logger.debug("Successfully imported memory_system")
                except ImportError as import_error:
                    logger.error(f"Failed to import memory module: {import_error}")
                    logger.error(f"Current working directory: {os.getcwd()}")
                    logger.error(f"Python path: {sys.path}")
                    raise HTTPException(
                        status_code=503,
                        detail=f"Memory module not available: {str(import_error)}"
                    )
                
                
                if not hasattr(memory_system, 'get_memory_stats'):
                    logger.error("Memory system doesn't have get_memory_stats method")
                    raise HTTPException(
                        status_code=503,
                        detail="Memory system not properly initialized"
                    )
                
                
                try:
                    result = memory_system.get_memory_stats()
                    logger.debug(f"Memory stats result: {result}")
                except Exception as stats_error:
                    logger.error(f"Error calling get_memory_stats: {stats_error}")
                    logger.error(f"Memory system type: {type(memory_system)}")
                    logger.error(f"Memory system db_path: {getattr(memory_system, 'db_path', 'Not found')}")
                    raise HTTPException(
                        status_code=500,
                        detail=f"Error getting memory stats: {str(stats_error)}"
                    )
                
                if result.get("success"):
                    return {
                        "success": True,
                        "stats": result["stats"],
                        "timestamp": time.time()
                    }
                else:
                    logger.error(f"Memory stats returned failure: {result}")
                    raise HTTPException(
                        status_code=500,
                        detail=result.get("message", "Unknown error in memory stats")
                    )
                    
            except HTTPException:
                
                raise
            except Exception as e:
                logger.error(f"Unexpected error in get_memory_stats: {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Unexpected error: {str(e)}"
                )
        
        @self.app.get("/api/memory/{key}")
        async def get_memory(key: str):
            """Get a specific memory by key."""
            try:
                
                import sys
                import os
                sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
                from tools.memory import memory_system
                
                result = memory_system.read_memory(key)
                
                if result["success"]:
                    return {
                        "success": True,
                        "memory": result["memory"],
                        "timestamp": time.time()
                    }
                else:
                    raise HTTPException(
                        status_code=404,
                        detail=result["message"]
                    )
                    
            except ImportError as e:
                logger.error(f"Failed to import memory module: {e}")
                raise HTTPException(
                    status_code=503,
                    detail="Memory module not available"
                )
            except Exception as e:
                logger.error(f"Failed to get memory: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to get memory: {str(e)}"
                )
        
        @self.app.post("/api/memory")
        async def create_memory(memory_data: dict):
            """Create a new memory."""
            try:
                
                if not memory_data.get("key"):
                    raise HTTPException(
                        status_code=400,
                        detail="Memory key is required"
                    )
                if not memory_data.get("content"):
                    raise HTTPException(
                        status_code=400,
                        detail="Memory content is required"
                    )
                
                
                import sys
                import os
                sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
                from tools.memory import memory_system
                
                result = memory_system.save_memory(
                    key=memory_data["key"],
                    content=memory_data["content"],
                    category=memory_data.get("category", "general"),
                    memory_type=memory_data.get("memory_type", "long_term"),
                    tags=memory_data.get("tags")
                )
                
                if result["success"]:
                    return {
                        "success": True,
                        "message": result["message"],
                        "id": result.get("id"),
                        "key": result["key"],
                        "memory_type": result["memory_type"],
                        "timestamp": time.time()
                    }
                else:
                    raise HTTPException(
                        status_code=400,
                        detail=result["message"]
                    )
                    
            except ImportError as e:
                logger.error(f"Failed to import memory module: {e}")
                raise HTTPException(
                    status_code=503,
                    detail="Memory module not available"
                )
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Failed to create memory: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to create memory: {str(e)}"
                )
        
        @self.app.put("/api/memory/{key}")
        async def update_memory(key: str, memory_data: dict):
            """Update an existing memory."""
            try:
                
                import sys
                import os
                sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
                from tools.memory import memory_system
                
                result = memory_system.update_memory(
                    key=key,
                    content=memory_data.get("content"),
                    category=memory_data.get("category"),
                    memory_type=memory_data.get("memory_type"),
                    tags=memory_data.get("tags")
                )
                
                if result["success"]:
                    return {
                        "success": True,
                        "message": result["message"],
                        "timestamp": time.time()
                    }
                else:
                    raise HTTPException(
                        status_code=404,
                        detail=result["message"]
                    )
                    
            except ImportError as e:
                logger.error(f"Failed to import memory module: {e}")
                raise HTTPException(
                    status_code=503,
                    detail="Memory module not available"
                )
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Failed to update memory: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to update memory: {str(e)}"
                )
        
        @self.app.delete("/api/memory/{key}")
        async def delete_memory(key: str):
            """Delete a memory by key."""
            try:
                
                import sys
                import os
                sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
                from tools.memory import memory_system
                
                result = memory_system.delete_memory(key)
                
                if result["success"]:
                    return {
                        "success": True,
                        "message": result["message"],
                        "timestamp": time.time()
                    }
                else:
                    raise HTTPException(
                        status_code=404,
                        detail=result["message"]
                    )
                    
            except ImportError as e:
                logger.error(f"Failed to import memory module: {e}")
                raise HTTPException(
                    status_code=503,
                    detail="Memory module not available"
                )
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Failed to delete memory: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to delete memory: {str(e)}"
                )
    
    async def _send_to_session(self, session, message: str, turn_complete: bool = True):
        """Send a text message to the Gemini Live session."""
        try:
            
            await session.send_client_content(
                turns={"role": "user", "parts": [{"text": message}]},
                turn_complete=turn_complete
            )
        except Exception as e:
            logger.error(f"Error sending to session: {e}")
            raise
    
    async def start_server(self):
        """Start the FastAPI server."""
        try:
            config = uvicorn.Config(
                app=self.app,
                host=self.host,
                port=self.port,
                log_level="info",
                access_log=True
            )
            self._server = uvicorn.Server(config)
            logger.info(f"Starting Gabriel Chat API server on {self.host}:{self.port}")
            await self._server.serve()
        except Exception as e:
            logger.error(f"Failed to start API server: {e}")
            raise
    
    def start_server_in_background(self):
        """Start the server in a background thread."""
        def run_server():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self.start_server())
            except Exception as e:
                logger.error(f"API server error: {e}")
            finally:
                loop.close()
        
        if self._server_task is None or not self._server_task.is_alive():
            self._server_task = threading.Thread(target=run_server, daemon=True)
            self._server_task.start()
            logger.info("API server started in background thread")
    
    async def stop_server(self):
        """Stop the FastAPI server."""
        if self._server:
            try:
                self._server.should_exit = True
                logger.info("API server stop requested")
            except Exception as e:
                logger.error(f"Error stopping API server: {e}")


_api_instance = None

def register_session(session):
    """Register the active Gemini Live session with the API."""
    global _active_session
    with _session_lock:
        _active_session = session
        logger.info("Gemini Live session registered with Chat API")

def unregister_session():
    """Unregister the active Gemini Live session."""
    global _active_session
    with _session_lock:
        _active_session = None
        logger.info("Gemini Live session unregistered from Chat API")

def register_session_manager(manager):
    """Register the session manager with the API."""
    global _session_manager
    with _manager_lock:
        _session_manager = manager
        logger.info("Session manager registered with Chat API")

def unregister_session_manager():
    """Unregister the session manager."""
    global _session_manager
    with _manager_lock:
        _session_manager = None
        logger.info("Session manager unregistered from Chat API")

def start_chat_api(config: Dict[str, Any]):
    """Start the Chat API server."""
    global _api_instance
    
    
    api_config = config.get('api', {})
    chat_config = api_config.get('chat', {})
    
    
    if not chat_config.get('enabled', False):
        logger.info("Chat API is disabled in configuration")
        return
    
    
    host = chat_config.get('host', '127.0.0.1')
    port = chat_config.get('port', 8000)
    
    try:
        
        _api_instance = GabrielChatAPI(host=host, port=port)
        _api_instance.start_server_in_background()
        logger.info(f"Gabriel Chat API started on http://{host}:{port}")
        
    except Exception as e:
        logger.error(f"Failed to start Chat API: {e}")

def stop_chat_api():
    """Stop the Chat API server."""
    global _api_instance
    if _api_instance:
        try:
            
            
            if _api_instance._server:
                _api_instance._server.should_exit = True
            logger.info("Chat API stop requested")
        except Exception as e:
            logger.error(f"Error stopping Chat API: {e}")

def get_api_status() -> Dict[str, Any]:
    """Get the current API status."""
    global _api_instance, _active_session, _websocket_connections, _websocket_lock
    
    with _session_lock:
        session_active = _active_session is not None
    
    with _websocket_lock:
        connected_clients = len(_websocket_connections)
    
    return {
        "api_instance_active": _api_instance is not None,
        "server_running": _api_instance is not None and _api_instance._server is not None,
        "session_registered": session_active,
        "websocket_clients": connected_clients,
        "host": _api_instance.host if _api_instance else None,
        "port": _api_instance.port if _api_instance else None
    }

async def broadcast_to_websockets(message_type: str, data: Dict[str, Any]):
    """Broadcast a message to all connected WebSocket clients."""
    global _websocket_connections, _websocket_lock
    
    try:
        
        if _websocket_connections is None:
            logger.warning("_websocket_connections is None, initializing empty set")
            _websocket_connections = set()
        
        if not _websocket_connections:
            logger.debug("No WebSocket connections to broadcast to")
            return
        
        message = {
            "type": message_type,
            "data": data,
            "timestamp": time.time()
        }
        
        disconnected_clients = set()
        
        with _websocket_lock:
            connections_copy = _websocket_connections.copy()
        
        logger.debug(f"Broadcasting message type '{message_type}' to {len(connections_copy)} clients")
        
        for websocket in connections_copy:
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to send to WebSocket client: {e}")
                disconnected_clients.add(websocket)
        
        
        if disconnected_clients:
            with _websocket_lock:
                _websocket_connections -= disconnected_clients
            logger.info(f"Removed {len(disconnected_clients)} disconnected WebSocket clients")
    
    except Exception as e:
        logger.error(f"Error in broadcast_to_websockets: {e}")
        import traceback
        logger.error(traceback.format_exc())

def broadcast_gabriel_response(response_text: str, response_type: str = "response"):
    """Broadcast Gabriel's response to all WebSocket clients (sync wrapper)."""
    global _websocket_connections
    
    if not _websocket_connections:
        return
    
    
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    
    try:
        if loop.is_running():
            
            asyncio.create_task(broadcast_to_websockets(response_type, {
                "text": response_text,
                "message": response_text
            }))
        else:
            
            loop.run_until_complete(broadcast_to_websockets(response_type, {
                "text": response_text,
                "message": response_text
            }))
    except Exception as e:
        logger.error(f"Failed to broadcast Gabriel response: {e}")

def broadcast_system_message(message: str, message_type: str = "system"):
    """Broadcast a system message to all WebSocket clients."""
    global _websocket_connections
    
    if not _websocket_connections:
        return
    
    
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    
    try:
        if loop.is_running():
            
            asyncio.create_task(broadcast_to_websockets(message_type, {
                "message": message
            }))
        else:
            
            loop.run_until_complete(broadcast_to_websockets(message_type, {
                "message": message
            }))
    except Exception as e:
        logger.error(f"Failed to broadcast system message: {e}")

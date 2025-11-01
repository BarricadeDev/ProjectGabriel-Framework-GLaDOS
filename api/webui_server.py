import logging
import threading
import http.server
import socketserver
import os
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)

_webui_server = None
_server_thread = None

class WebUIHandler(http.server.SimpleHTTPRequestHandler):
    
    def __init__(self, *args, **kwargs):
        webui_directory = str(Path(__file__).parent / "webui")
        super().__init__(*args, directory=webui_directory, **kwargs)
    
    def log_message(self, format, *args):
        logger.debug(f"WebUI Request: {format % args}")
    
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        self.send_header('Expires', '0')
        super().end_headers()

def start_webui_server(config: Dict[str, Any]):
    global _webui_server, _server_thread
    
    api_config = config.get('api', {})
    webui_config = api_config.get('webui', {})
    
    if not webui_config.get('enabled', True):
        logger.info("WebUI server is disabled in configuration")
        return
    
    host = webui_config.get('host', '0.0.0.0')
    port = webui_config.get('port', 5069)
    
    webui_path = Path(__file__).parent / "webui"
    if not webui_path.exists():
        logger.warning(f"WebUI directory not found at {webui_path}")
        return
    
    try:
        socketserver.TCPServer.allow_reuse_address = True
        _webui_server = socketserver.TCPServer((host, port), WebUIHandler)
        
        def run_server():
            try:
                logger.info(f"WebUI server started on http://{host}:{port}")
                logger.info(f"Access the WebUI at: http://localhost:{port}/")
                _webui_server.serve_forever()
            except Exception as e:
                logger.error(f"WebUI server error: {e}")
        
        _server_thread = threading.Thread(target=run_server, daemon=True)
        _server_thread.start()
        
    except Exception as e:
        logger.error(f"Failed to start WebUI server: {e}")

def stop_webui_server():
    global _webui_server, _server_thread
    
    if _webui_server:
        try:
            _webui_server.shutdown()
            _webui_server.server_close()
            logger.info("WebUI server stopped")
        except Exception as e:
            logger.error(f"Error stopping WebUI server: {e}")
        finally:
            _webui_server = None
            _server_thread = None

def get_webui_status() -> Dict[str, Any]:
    global _webui_server, _server_thread
    
    return {
        "server_active": _webui_server is not None,
        "thread_alive": _server_thread is not None and _server_thread.is_alive(),
    }

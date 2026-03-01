import threading
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone
import json

logger = logging.getLogger(__name__)

# Shared state for health tracking
_health_state = {
    "last_sync": None,
    "status": "starting",
    "error": None,
}
_lock = threading.Lock()

HEALTHCHECK_PORT = 8080


def update_health(status="ok", error=None):
    """Update health state after a sync cycle."""
    with _lock:
        _health_state["last_sync"] = datetime.now(timezone.utc).isoformat()
        _health_state["status"] = status
        _health_state["error"] = str(error) if error else None


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/health":
            self.send_response(404)
            self.end_headers()
            return

        with _lock:
            state = _health_state.copy()

        # Consider unhealthy if no sync has completed yet
        if state["status"] == "starting":
            code = 503
        elif state["status"] == "error":
            code = 500
        else:
            code = 200

        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(state).encode())

    def log_message(self, format, *args):
        # Suppress default request logging
        pass


def start_health_server(port=HEALTHCHECK_PORT):
    """Start the health check HTTP server in a background daemon thread."""
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"Health check server started on port {port}")
    return server

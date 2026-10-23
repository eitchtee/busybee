import threading
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone
import json

logger = logging.getLogger(__name__)

# Shared state for health tracking
_health_state = {
    "last_sync": None,
    "last_success": None,
    "status": "starting",
    "error": None,
}
_lock = threading.Lock()

HEALTHCHECK_PORT = 8080

# Seconds without a successful sync before reporting unhealthy, so a single
# transient failure doesn't flip the container to unhealthy
_max_success_age = None


def update_health(status="ok", error=None):
    """Update health state after a sync cycle."""
    with _lock:
        now = datetime.now(timezone.utc).isoformat()
        _health_state["last_sync"] = now
        if status == "ok":
            _health_state["last_success"] = now
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
        elif state["status"] == "ok":
            code = 200
        elif state["last_success"] and _max_success_age is not None:
            # Tolerate errors as long as a sync succeeded recently
            age = (
                datetime.now(timezone.utc)
                - datetime.fromisoformat(state["last_success"])
            ).total_seconds()
            code = 200 if age <= _max_success_age else 500
        else:
            code = 500

        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(state).encode())

    def log_message(self, format, *args):
        # Suppress default request logging
        pass


def start_health_server(port=HEALTHCHECK_PORT, max_success_age=None):
    """Start the health check HTTP server in a background daemon thread."""
    global _max_success_age
    _max_success_age = max_success_age
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"Health check server started on port {port}")
    return server

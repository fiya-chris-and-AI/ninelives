"""
F10's kill mechanism: a tiny control server co-located with each worker
process. POST /kill (with the shared secret header) SIGKILLs THIS process
immediately — real death, not a flag: the KILL AGENT button SIGKILLs the
active worker's process via a tiny control endpoint on each worker host.

Stdlib http.server only — this is a single-purpose control plane, not
worth a second FastAPI process per worker.
"""
import os
import signal
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import config


def discover_host() -> str:
    """The address the arena (possibly in another AWS region) should use
    to reach this worker's control server. CONTROL_HOST overrides for
    local/dev use; otherwise ask a public IP echo service — no AWS IAM
    permissions required, good enough for a demo-scale deployment."""
    override = os.environ.get("CONTROL_HOST")
    if override:
        return override
    try:
        with urllib.request.urlopen("https://checkip.amazonaws.com", timeout=3) as r:
            return r.read().decode().strip()
    except Exception:
        return "127.0.0.1"


class _KillHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # the worker's own stdout is the demo terminal; keep it clean

    def do_POST(self):
        if self.path != "/kill":
            self.send_response(404)
            self.end_headers()
            return
        if self.headers.get("X-Control-Secret") != config.CONTROL_SHARED_SECRET:
            self.send_response(403)
            self.end_headers()
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"dying")
        self.wfile.flush()
        os.kill(os.getpid(), signal.SIGKILL)  # real death — nothing after this line runs

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"alive")
        else:
            self.send_response(404)
            self.end_headers()


def start_control_server(port: int) -> HTTPServer:
    server = HTTPServer(("0.0.0.0", port), _KillHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server

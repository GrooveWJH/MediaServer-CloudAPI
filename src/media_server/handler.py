import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

from .handlers import (
    handle_fast_upload,
    handle_sts,
    handle_tiny_fingerprints,
    handle_upload_callback,
)
from .http_layer.error_codes import ERR_INVALID_TOKEN, ERR_MISSING_TOKEN, ERR_NOT_FOUND
from .utils.http import error_response, ok_response
from .http_layer.router import resolve_route


class MediaRequestHandler(BaseHTTPRequestHandler):
    server_version = "FCMediaServer/0.1"
    config = None
    db = None

    def log_message(self, fmt, *args):
        logging.getLogger("access").debug("%s - %s", self.address_string(), fmt % args)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            ok_response(self, {}, message="ok", status=HTTPStatus.OK)
            return
        error_response(self, ERR_NOT_FOUND)

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, x-auth-token")
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        route_name, workspace_id = resolve_route("POST", parsed.path)
        if not route_name or not workspace_id:
            error_response(self, ERR_NOT_FOUND)
            return
        handlers = {
            "fast-upload": handle_fast_upload,
            "tiny-fingerprints": handle_tiny_fingerprints,
            "upload-callback": handle_upload_callback,
            "sts": handle_sts,
        }
        handler = handlers.get(route_name)
        if not handler:
            error_response(self, ERR_NOT_FOUND)
            return
        handler(self, workspace_id)

    def read_json(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length) if content_length > 0 else b""
        if not raw:
            return {}
        payload = json.loads(raw.decode("utf-8"))
        if logging.getLogger().isEnabledFor(logging.DEBUG):
            summary = {"keys": sorted(payload.keys())}
            if "fingerprint" in payload:
                summary["fingerprint"] = f"{payload['fingerprint'][:8]}..."
            if "tiny_fingerprints" in payload and isinstance(payload["tiny_fingerprints"], list):
                summary["tiny_count"] = len(payload["tiny_fingerprints"])
            if "object_key" in payload:
                summary["object_key"] = payload["object_key"]
            logging.debug("request %s %s payload=%s", self.command, self.path, summary)
        return payload

    def require_token(self):
        token = self.headers.get("x-auth-token")
        if not token:
            error_response(self, ERR_MISSING_TOKEN)
            return None
        if token != self.config.server.token:
            error_response(self, ERR_INVALID_TOKEN)
            return None
        return token

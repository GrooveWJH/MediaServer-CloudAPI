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
from .http_utils import json_response
from .router import match_fast_upload, match_sts, match_tiny_fingerprints, match_upload_callback


class MediaRequestHandler(BaseHTTPRequestHandler):
    server_version = "FCMediaServer/0.1"
    tiny_fingerprint_index = {}
    pending_tiny_by_fingerprint = {}
    uploaded_fingerprints = set()
    object_key_by_fingerprint = {}
    object_key_by_tiny = {}
    upload_records = []
    config = None
    db = None

    def log_message(self, fmt, *args):
        logging.getLogger("access").debug("%s - %s", self.address_string(), fmt % args)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            json_response(self, HTTPStatus.OK, {"code": 0, "message": "ok", "data": {}})
            return
        json_response(self, HTTPStatus.NOT_FOUND, {"code": 404, "message": "not found", "data": {}})

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, x-auth-token")
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        workspace_id = match_fast_upload(parsed.path)
        if workspace_id:
            handle_fast_upload(self, workspace_id)
            return
        workspace_id = match_tiny_fingerprints(parsed.path)
        if workspace_id:
            handle_tiny_fingerprints(self, workspace_id)
            return
        workspace_id = match_upload_callback(parsed.path)
        if workspace_id:
            handle_upload_callback(self, workspace_id)
            return
        workspace_id = match_sts(parsed.path)
        if workspace_id:
            handle_sts(self, workspace_id)
            return
        json_response(self, HTTPStatus.NOT_FOUND, {"code": 404, "message": "not found", "data": {}})

    def read_json(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length) if content_length > 0 else b""
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def require_token(self):
        token = self.headers.get("x-auth-token")
        if not token:
            json_response(self, HTTPStatus.UNAUTHORIZED, {"code": 401, "message": "missing x-auth-token", "data": {}})
            return None
        if token != self.config.token:
            json_response(self, HTTPStatus.UNAUTHORIZED, {"code": 401, "message": "invalid x-auth-token", "data": {}})
            return None
        return token

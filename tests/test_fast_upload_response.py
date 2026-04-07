import json
import sys
import unittest
from io import BytesIO
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from media_server.handlers.fast_upload import handle_fast_upload


class _FakeDB:
    def __init__(self):
        self.upserts = []

    def upsert_fingerprint_tiny(self, *args, **kwargs):
        self.upserts.append((args, kwargs))

    def get_object_key_by_fingerprint(self, workspace_id, fingerprint):
        return None


class _FakeHandler:
    def __init__(self, payload):
        self.command = "POST"
        self.path = "/media/api/v1/workspaces/ws1/fast-upload"
        self.headers = {
            "x-auth-token": "demo-token",
            "Content-Length": str(len(payload)),
        }
        self.rfile = BytesIO(payload)
        self.wfile = BytesIO()
        self.db = _FakeDB()
        self.config = type(
            "Config",
            (),
            {"server": type("Server", (), {"token": "demo-token"})()},
        )()
        self.status = None
        self.sent_headers = []

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.sent_headers.append((key, value))

    def end_headers(self):
        return None

    def read_json(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        return json.loads(raw.decode("utf-8"))

    def require_token(self):
        token = self.headers.get("x-auth-token")
        return token if token == self.config.server.token else None


class FastUploadResponseTest(unittest.TestCase):
    def test_miss_response_matches_dji_error_shape(self):
        payload = json.dumps(
            {
                "fingerprint": "fp-miss",
                "name": "DJI_20260407180330_0001_V.JPG",
                "path": "DJI_202604071650_024_上云API",
                "ext": {
                    "tinny_fingerprint": "tiny-miss",
                    "is_original": True,
                },
            }
        ).encode("utf-8")
        handler = _FakeHandler(payload)

        handle_fast_upload(handler, "ws1")

        body = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(200, handler.status)
        self.assertEqual(-1, body["code"])
        self.assertEqual("fp-miss don't exist.", body["message"])
        self.assertEqual("", body["data"])


if __name__ == "__main__":
    unittest.main()

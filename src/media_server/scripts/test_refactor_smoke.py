#!/usr/bin/env python3
import os
import sys
import tempfile

repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
src_root = os.path.join(repo_root, "src")
sys.path.insert(0, src_root)

from media_server.config import AppConfig, ServerConfig, StorageConfig, STSConfig
from media_server.http_layer.request_models import parse_fast_upload, parse_tiny_fingerprints, parse_upload_callback
from media_server.http_layer.router import resolve_route
from media_server.storage.db import MediaDB
from media_server.storage.s3_client import S3Client
from media_server.utils.http import build_object_key


def assert_true(expr, message):
    if not expr:
        raise AssertionError(message)


def main():
    route_name, workspace_id = resolve_route("POST", "/media/api/v1/workspaces/ws1/fast-upload")
    assert_true(route_name == "fast-upload" and workspace_id == "ws1", "route resolution failed")

    req, err = parse_fast_upload({"fingerprint": "fp1", "name": "a.jpg", "ext": {"tinny_fingerprint": "tf1"}})
    assert_true(err is None and req.fingerprint == "fp1" and req.tiny_fingerprint == "tf1", "fast upload parse failed")

    req, err = parse_tiny_fingerprints({"tiny_fingerprints": ["t1", "t2"]})
    assert_true(err is None and req.tiny_fingerprints == ["t1", "t2"], "tiny fingerprints parse failed")

    req, err = parse_upload_callback({"object_key": "k1", "fingerprint": "f1"})
    assert_true(err is None and req.object_key == "k1", "upload callback parse failed")

    key = build_object_key("ws1", "a/b.txt")
    assert_true(key.startswith("ws1/"), "object key build failed")
    assert_true("/" not in key.split("/")[-1], "object key filename not sanitized")

    storage = StorageConfig(
        endpoint="http://127.0.0.1:9000",
        bucket="media",
        region="us-east-1",
        access_key="key",
        secret_key="secret",
        session_token="",
        provider="minio",
    )
    S3Client(storage)

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "media.db")
        db = MediaDB(db_path, pool_size=1)
        db.upsert_fingerprint_tiny("ws1", "fp1", "tf1", file_name="a.jpg", file_path="/a")
        tiny = db.get_tiny_by_fingerprint("ws1", "fp1")
        assert_true(tiny == "tf1", "tiny lookup failed")
        db.upsert_file("ws1", "fp1", "tf1", "obj1", "a.jpg", "/a")
        obj = db.get_object_key_by_fingerprint("ws1", "fp1")
        assert_true(obj == "obj1", "object key lookup failed")
        db.delete_by_fingerprint("ws1", "fp1")
        obj = db.get_object_key_by_fingerprint("ws1", "fp1")
        assert_true(obj is None, "delete by fingerprint failed")
        db.close()

    _ = AppConfig(
        server=ServerConfig(host="0.0.0.0", port=8090, token="t"),
        storage=storage,
        sts=STSConfig(role_arn="arn", policy="", duration=3600),
        db_path=":memory:",
        log_level="info",
    )

    print("[test] refactor smoke OK")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[test] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

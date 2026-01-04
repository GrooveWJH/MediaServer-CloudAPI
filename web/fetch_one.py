import argparse
import os
import sqlite3
import sys
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(repo_root, "src"))

from media_server.utils.aws_sigv4 import aws_v4_headers


def _encode_path(path):
    return quote(path, safe="/-_.~")


def s3_request(config, method, object_key, payload=b""):
    path = f"/{config.storage_bucket}/{object_key.lstrip('/')}"
    canonical_uri = _encode_path(path)
    url = f"{config.storage_scheme}://{config.storage_host}{canonical_uri}"
    extra_headers = {}
    if config.storage_session_token:
        extra_headers["x-amz-security-token"] = config.storage_session_token
    headers = aws_v4_headers(
        config.storage_access_key,
        config.storage_secret_key,
        config.storage_region,
        "s3",
        method,
        config.storage_host,
        canonical_uri,
        payload,
        extra_headers,
    )
    req = Request(url, data=payload if method in {"PUT", "POST"} else None, headers=headers, method=method)
    with urlopen(req, timeout=15) as resp:
        return resp.status, resp.read(), resp.headers


def open_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def parse_args():
    parser = argparse.ArgumentParser(description="Fetch one object from SQLite + MinIO")
    parser.add_argument("--db-path", default="data/media.db", help="SQLite DB path")
    parser.add_argument("--storage-endpoint", default="http://127.0.0.1:9000", help="Object storage endpoint")
    parser.add_argument("--storage-bucket", default="media", help="Object storage bucket")
    parser.add_argument("--storage-region", default="us-east-1", help="Object storage region")
    parser.add_argument("--storage-access-key", default="minioadmin", help="Object storage access key")
    parser.add_argument("--storage-secret-key", default="minioadmin", help="Object storage secret key")
    parser.add_argument("--storage-session-token", default="", help="Object storage session token")
    parser.add_argument("--object-key", default="", help="Optional object_key override")
    parser.add_argument("--output", default="", help="Output filename (default from object_key)")
    return parser.parse_args()


def main():
    config = parse_args()
    parsed = urlparse(config.storage_endpoint)
    if not parsed.scheme or not parsed.netloc:
        raise RuntimeError(f"invalid storage endpoint: {config.storage_endpoint}")
    config.storage_scheme = parsed.scheme
    config.storage_host = parsed.netloc

    object_key = config.object_key
    if not object_key:
        with open_db(config.db_path) as conn:
            row = conn.execute(
                """
                SELECT object_key, file_name
                FROM media_files
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
        if not row:
            raise RuntimeError("no records found in database")
        object_key = row["object_key"]

    status, body, headers = s3_request(config, "GET", object_key)
    if status != 200:
        raise RuntimeError(f"GET failed status={status}")
    filename = config.output or os.path.basename(object_key)
    with open(filename, "wb") as f:
        f.write(body)
    print(f"Downloaded {object_key} -> {filename} ({len(body)} bytes)")


if __name__ == "__main__":
    main()

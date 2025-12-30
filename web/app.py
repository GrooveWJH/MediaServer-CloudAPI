import argparse
import os
import sqlite3
import sys
from datetime import datetime
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from flask import Flask, Response, jsonify, render_template, request, url_for

repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(repo_root, "src"))

from media_server.aws_sigv4 import aws_v4_headers


def _encode_path(path):
    return quote(path, safe="/-_.~")


def build_s3_headers(config, method, canonical_uri, payload=b""):
    extra_headers = {}
    if config.storage_session_token:
        extra_headers["x-amz-security-token"] = config.storage_session_token
    return aws_v4_headers(
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


def s3_request(config, method, object_key, payload=b""):
    path = f"/{config.storage_bucket}/{object_key.lstrip('/')}"
    canonical_uri = _encode_path(path)
    url = f"{config.storage_scheme}://{config.storage_host}{canonical_uri}"
    headers = build_s3_headers(config, method, canonical_uri, payload)
    req = Request(url, data=payload if method in {"PUT", "POST"} else None, headers=headers, method=method)
    with urlopen(req, timeout=30) as resp:
        return resp.status, resp.read(), resp.headers


def open_db(db_path):
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def parse_args():
    parser = argparse.ArgumentParser(description="Media browser for SQLite + MinIO")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    parser.add_argument("--port", type=int, default=8088, help="Bind port")
    parser.add_argument("--db-path", default="data/media.db", help="SQLite DB path")
    parser.add_argument("--storage-endpoint", default="http://127.0.0.1:9000", help="Object storage endpoint")
    parser.add_argument("--storage-bucket", default="media", help="Object storage bucket")
    parser.add_argument("--storage-region", default="us-east-1", help="Object storage region")
    parser.add_argument("--storage-access-key", default="minioadmin", help="Object storage access key")
    parser.add_argument("--storage-secret-key", default="minioadmin", help="Object storage secret key")
    parser.add_argument("--storage-session-token", default="", help="Object storage session token")
    return parser.parse_args()


def create_app(config):
    app = Flask(__name__)
    parsed = urlparse(config.storage_endpoint)
    if not parsed.scheme or not parsed.netloc:
        raise RuntimeError(f"invalid storage endpoint: {config.storage_endpoint}")
    config.storage_scheme = parsed.scheme
    config.storage_host = parsed.netloc

    def _row_to_item(row):
        created = datetime.fromtimestamp(row["created_at"]).strftime("%Y-%m-%d %H:%M:%S")
        return {**dict(row), "created_at": created}

    @app.route("/")
    def index():
        with open_db(config.db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, workspace_id, fingerprint, tiny_fingerprint, object_key,
                       file_name, file_path, created_at
                FROM media_files
                ORDER BY created_at DESC
                """
            ).fetchall()
        items = [_row_to_item(row) for row in rows]
        return render_template("index.html", items=items)

    @app.route("/api/media")
    def api_media():
        since_id = request.args.get("since_id", "0")
        try:
            since_id = int(since_id)
        except ValueError:
            return jsonify({"error": "invalid since_id"}), 400
        with open_db(config.db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, workspace_id, fingerprint, tiny_fingerprint, object_key,
                       file_name, file_path, created_at
                FROM media_files
                WHERE id > ?
                ORDER BY id ASC
                """,
                (since_id,),
            ).fetchall()
        items = [_row_to_item(row) for row in rows]
        return jsonify({"items": items})

    @app.route("/preview")
    def preview():
        object_key = request.args.get("object_key", "")
        if not object_key:
            return Response("missing object_key", status=400)
        status, body, headers = s3_request(config, "GET", object_key)
        if status != 200:
            return Response(f"upstream status={status}", status=502)
        content_type = headers.get("Content-Type", "application/octet-stream")
        return Response(body, status=200, content_type=content_type)

    @app.route("/delete", methods=["POST"])
    def delete_item():
        record_id = request.form.get("record_id", "")
        object_key = request.form.get("object_key", "")
        if not record_id or not object_key:
            return jsonify({"ok": False, "error": "missing record_id/object_key"}), 400
        s3_request(config, "DELETE", object_key)
        with open_db(config.db_path) as conn:
            conn.execute("DELETE FROM media_files WHERE id=?", (record_id,))
            conn.commit()
        return jsonify({"ok": True, "id": record_id})

    return app


def main():
    config = parse_args()
    app = create_app(config)
    app.run(host=config.host, port=config.port)


if __name__ == "__main__":
    main()

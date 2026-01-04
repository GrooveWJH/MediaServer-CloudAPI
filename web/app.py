import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

import typer
from flask import Flask, Response, jsonify, render_template, request, url_for

repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(repo_root, "src"))

from media_server.utils.aws_sigv4 import aws_v4_headers


SELECT_FIELDS = """
    id, workspace_id, fingerprint, tiny_fingerprint, object_key,
    file_name, file_path, created_at
"""


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


@dataclass
class WebConfig:
    host: str
    port: int
    db_path: str
    storage_endpoint: str
    storage_bucket: str
    storage_region: str
    storage_access_key: str
    storage_secret_key: str
    storage_session_token: str
    storage_scheme: str = ""
    storage_host: str = ""


def parse_storage_endpoint(config):
    parsed = urlparse(config.storage_endpoint)
    if not parsed.scheme or not parsed.netloc:
        raise RuntimeError(f"invalid storage endpoint: {config.storage_endpoint}")
    config.storage_scheme = parsed.scheme
    config.storage_host = parsed.netloc


def fetch_items(db_path, since_id=None):
    query = f"""
        SELECT {SELECT_FIELDS}
        FROM media_files
        WHERE object_key IS NOT NULL AND object_key != ''
    """
    params = ()
    if since_id is not None:
        query += " AND id > ?"
        params = (since_id,)
        query += " ORDER BY id ASC"
    else:
        query += " ORDER BY created_at DESC"
    with open_db(db_path) as conn:
        return conn.execute(query, params).fetchall()


def create_app(config):
    app = Flask(__name__)
    parse_storage_endpoint(config)

    def _row_to_item(row):
        created = datetime.fromtimestamp(row["created_at"]).strftime("%Y-%m-%d %H:%M:%S")
        return {**dict(row), "created_at": created}

    @app.route("/")
    def index():
        rows = fetch_items(config.db_path)
        items = [_row_to_item(row) for row in rows]
        return render_template("index.html", items=items)

    @app.route("/api/media")
    def api_media():
        since_id = request.args.get("since_id", "0")
        try:
            since_id = int(since_id)
        except ValueError:
            return jsonify({"error": "invalid since_id"}), 400
        rows = fetch_items(config.db_path, since_id=since_id)
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
        resp = Response(body, status=200, content_type=content_type)
        resp.headers["Cache-Control"] = "no-store"
        return resp

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


cli = typer.Typer(add_completion=False)


@cli.callback(invoke_without_command=True)
def main(
    host: str = typer.Option("0.0.0.0", "--host", help="Bind host"),
    port: int = typer.Option(8088, "--port", help="Bind port"),
    db_path: str = typer.Option("data/media.db", "--db-path", help="SQLite DB path"),
    storage_endpoint: str = typer.Option("http://127.0.0.1:9000", "--storage-endpoint", help="Object storage endpoint"),
    storage_bucket: str = typer.Option("media", "--storage-bucket", help="Object storage bucket"),
    storage_region: str = typer.Option("us-east-1", "--storage-region", help="Object storage region"),
    storage_access_key: str = typer.Option("minioadmin", "--storage-access-key", help="Object storage access key"),
    storage_secret_key: str = typer.Option("minioadmin", "--storage-secret-key", help="Object storage secret key"),
    storage_session_token: str = typer.Option("", "--storage-session-token", help="Object storage session token"),
):
    config = WebConfig(
        host,
        port,
        db_path,
        storage_endpoint,
        storage_bucket,
        storage_region,
        storage_access_key,
        storage_secret_key,
        storage_session_token,
    )
    app = create_app(config)
    app.run(host=config.host, port=config.port)


if __name__ == "__main__":
    cli()

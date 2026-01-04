#!/usr/bin/env python3
import json
import os
import sys
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

import typer
repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(repo_root, "src"))

from media_server.utils.aws_sigv4 import aws_v4_headers


def _encode_path(path):
    return quote(path, safe="/-_.~")


def request_json(url, token):
    headers = {"x-auth-token": token, "Content-Type": "application/json"}
    req = Request(url, data=b"{}", headers=headers, method="POST")
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def s3_put(endpoint, bucket, object_key, region, access_key, secret_key, session_token, payload):
    parsed = urlparse(endpoint)
    if not parsed.scheme or not parsed.netloc:
        raise RuntimeError(f"invalid endpoint: {endpoint}")

    path = f"/{bucket}/{object_key.lstrip('/')}"
    canonical_uri = _encode_path(path)
    url = f"{parsed.scheme}://{parsed.netloc}{canonical_uri}"
    extra_headers = {}
    if session_token:
        extra_headers["x-amz-security-token"] = session_token

    headers = aws_v4_headers(
        access_key,
        secret_key,
        region,
        "s3",
        "PUT",
        parsed.netloc,
        canonical_uri,
        payload,
        extra_headers,
    )
    headers["host"] = parsed.netloc
    req = Request(url, data=payload, headers=headers, method="PUT")
    with urlopen(req, timeout=30) as resp:
        return resp.status, resp.read()


cli = typer.Typer(add_completion=False)


@cli.callback(invoke_without_command=True)
def main(
    media_host: str = typer.Option("http://127.0.0.1:8090", "--media-host", help="Media server base URL"),
    workspace_id: str = typer.Option(..., "--workspace-id", help="Workspace ID"),
    token: str = typer.Option("demo-token", "--token", help="x-auth-token for media server"),
    payload: str = typer.Option("hello-sts-put", "--payload", help="Payload string to upload"),
):
    sts_url = f"{media_host}/storage/api/v1/workspaces/{workspace_id}/sts"
    data = request_json(sts_url, token)
    if data.get("code") != 0:
        raise RuntimeError(f"sts failed: {data}")

    sts = data["data"]
    creds = sts["credentials"]
    endpoint = sts["endpoint"]
    bucket = sts["bucket"]
    region = sts["region"]

    object_key = f"{sts['object_key_prefix']}test-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.txt"
    payload = payload.encode("utf-8")

    has_token = bool(creds.get("security_token") or creds.get("session_token"))
    print(f"[test] endpoint={endpoint} bucket={bucket} region={region}")
    print(f"[test] access_key_id={creds['access_key_id']} token_present={has_token}")
    print(f"[test] object_key={object_key} payload_bytes={len(payload)}")

    try:
        status, _ = s3_put(
            endpoint,
            bucket,
            object_key,
            region,
            creds["access_key_id"],
            creds["access_key_secret"],
            creds.get("security_token") or creds.get("session_token", ""),
            payload,
        )
        print(f"[test] PUT status={status}")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"PUT failed {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"PUT failed: {exc}") from exc


if __name__ == "__main__":
    try:
        cli()
    except Exception as exc:
        print(f"[test] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

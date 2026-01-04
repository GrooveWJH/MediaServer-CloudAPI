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
src_root = os.path.join(repo_root, "src")
sys.path.insert(0, src_root)

from media_server.scripts.image_gen import random_png_image
from media_server.utils.aws_sigv4 import aws_v4_headers


def _encode_path(path):
    return quote(path, safe="/-_.~")


def request_json(url, token, method="POST"):
    headers = {"x-auth-token": token, "Content-Type": "application/json"}
    req = Request(url, data=b"{}", headers=headers, method=method)
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def s3_request(method, endpoint, bucket, object_key, region, access_key, secret_key, session_token, payload=b""):
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
        method,
        parsed.netloc,
        canonical_uri,
        payload,
        extra_headers,
    )
    headers["host"] = parsed.netloc

    req = Request(url, data=payload if method in {"PUT", "POST"} else None, headers=headers, method=method)
    with urlopen(req, timeout=30) as resp:
        return resp.status, resp.read()


cli = typer.Typer(add_completion=False)


@cli.callback(invoke_without_command=True)
def main(
    media_host: str = typer.Option("http://127.0.0.1:8090", "--media-host", help="Media server base URL"),
    workspace_id: str = typer.Option(..., "--workspace-id", help="Workspace ID"),
    token: str = typer.Option("demo-token", "--token", help="x-auth-token for media server"),
    payload: str = typer.Option("hello-from-dji", "--payload", help="Payload string to upload"),
    random_image: bool = typer.Option(False, "--random-image", help="Upload a random PNG image instead of text"),
    text: bool = typer.Option(False, "--text", help="Upload text payload instead of random image"),
    image_size: str = typer.Option("", "--image-size", help="Random image size WxH, overrides --image-mb"),
    image_mb: int = typer.Option(10, "--image-mb", help="Target image size in MB (default 10MB)"),
):
    sts_url = f"{media_host}/storage/api/v1/workspaces/{workspace_id}/sts"
    print(f"[test] STS request: {sts_url}")
    data = request_json(sts_url, token)
    if data.get("code") != 0:
        raise RuntimeError(f"sts failed: {data}")

    sts = data["data"]
    creds = sts["credentials"]
    endpoint = sts["endpoint"]
    bucket = sts["bucket"]
    region = sts["region"]
    use_image = random_image or not text
    if use_image:
        size = image_size or f"{image_mb}MB"
        object_key = f"{sts['object_key_prefix']}test-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
        payload = random_png_image(size, image_mb)
        content_desc = f"random PNG {size}"
    else:
        object_key = f"{sts['object_key_prefix']}test-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
        payload_bytes = payload.encode("utf-8")
        content_desc = f"text payload ({len(payload_bytes)} bytes)"

    if use_image:
        payload_bytes = payload
    print(f"[test] Payload type: {content_desc}, size={len(payload_bytes)} bytes")
    print(f"[test] Uploading to {endpoint}/{bucket}/{object_key}")
    try:
        status, _ = s3_request(
            "PUT",
            endpoint,
            bucket,
            object_key,
            region,
            creds["access_key_id"],
            creds["access_key_secret"],
            creds.get("security_token", ""),
            payload=payload_bytes,
        )
        print(f"[test] PUT status={status}")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"PUT failed {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"PUT failed: {exc}") from exc

    try:
        status, _ = s3_request(
            "HEAD",
            endpoint,
            bucket,
            object_key,
            region,
            creds["access_key_id"],
            creds["access_key_secret"],
            creds.get("security_token", ""),
        )
        print(f"[test] HEAD status={status}")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HEAD failed {exc.code}: {detail}") from exc

    try:
        status, _ = s3_request(
            "DELETE",
            endpoint,
            bucket,
            object_key,
            region,
            creds["access_key_id"],
            creds["access_key_secret"],
            creds.get("security_token", ""),
        )
        print(f"[test] DELETE status={status}")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"DELETE failed {exc.code}: {detail}") from exc

    print("[test] Success. Upload + cleanup completed.")


if __name__ == "__main__":
    try:
        cli()
    except Exception as exc:
        print(f"[test] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

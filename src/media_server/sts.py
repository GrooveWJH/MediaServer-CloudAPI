import uuid
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from .aws_sigv4 import aws_v4_headers


def fetch_minio_sts(config, workspace_id):
    endpoint = urlparse(config.storage_endpoint)
    if not endpoint.scheme or not endpoint.netloc:
        raise RuntimeError(f"invalid storage endpoint: {config.storage_endpoint}")

    role_arn = config.storage_sts_role_arn
    session_name = f"dji-{workspace_id[:8]}-{uuid.uuid4().hex[:8]}"
    params = {
        "Action": "AssumeRole",
        "Version": "2011-06-15",
        "DurationSeconds": str(config.storage_sts_duration),
        "RoleSessionName": session_name,
        "RoleArn": role_arn,
    }
    if config.storage_sts_policy:
        params["Policy"] = config.storage_sts_policy

    body = urlencode(params).encode("utf-8")
    host = endpoint.netloc
    headers = aws_v4_headers(
        config.storage_access_key,
        config.storage_secret_key,
        config.storage_region,
        "sts",
        "POST",
        host,
        endpoint.path or "/",
        body,
        {"content-type": "application/x-www-form-urlencoded"},
    )
    headers["content-type"] = "application/x-www-form-urlencoded"

    request = Request(config.storage_endpoint, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=10) as response:
            raw = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"minio sts http {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"minio sts unreachable: {exc}") from exc

    access_key, secret_key, session_token, expire_seconds = parse_sts_response(raw)
    if not (access_key and secret_key and session_token):
        raise RuntimeError(f"incomplete sts response: {raw.decode('utf-8', errors='ignore')}")
    return session_token, access_key, secret_key, expire_seconds


def parse_sts_response(raw):
    try:
        from xml.etree import ElementTree
        root = ElementTree.fromstring(raw)
    except Exception as exc:
        raise RuntimeError(f"invalid sts xml: {exc}") from exc

    def find_text(tag_suffix):
        for element in root.iter():
            if element.tag.endswith(tag_suffix):
                return element.text
        return ""

    access_key = find_text("AccessKeyId")
    secret_key = find_text("SecretAccessKey")
    session_token = find_text("SessionToken")
    expiration = find_text("Expiration")
    expire_seconds = 3600
    if expiration:
        try:
            exp_time = datetime.strptime(expiration, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            expire_seconds = max(0, int((exp_time - datetime.now(timezone.utc)).total_seconds()))
        except ValueError:
            pass
    return access_key, secret_key, session_token, expire_seconds

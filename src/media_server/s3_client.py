from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from .aws_sigv4 import aws_v4_headers


def _encode_path(path):
    return quote(path, safe="/-_.~")


def head_object(config, object_key):
    parsed = urlparse(config.storage_endpoint)
    if not parsed.scheme or not parsed.netloc:
        raise RuntimeError(f"invalid storage endpoint: {config.storage_endpoint}")

    path = f"/{config.storage_bucket}/{object_key.lstrip('/')}"
    canonical_uri = _encode_path(path)
    url = f"{parsed.scheme}://{parsed.netloc}{canonical_uri}"
    headers = aws_v4_headers(
        config.storage_access_key,
        config.storage_secret_key,
        config.storage_region,
        "s3",
        "HEAD",
        parsed.netloc,
        canonical_uri,
        b"",
    )
    headers["host"] = parsed.netloc
    req = Request(url, headers=headers, method="HEAD")
    try:
        with urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except HTTPError as exc:
        if exc.code == 404:
            return False
        raise RuntimeError(f"head object failed {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"head object failed: {exc}") from exc

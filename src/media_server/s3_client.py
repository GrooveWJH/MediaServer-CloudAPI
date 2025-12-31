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

    bucket_prefix = f"{config.storage_bucket}/"
    candidates = [object_key.lstrip("/")]
    if not object_key.startswith(bucket_prefix):
        candidates.append(f"{bucket_prefix}{object_key.lstrip('/')}")

    for candidate in candidates:
        path = f"/{config.storage_bucket}/{candidate}"
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
                continue
            raise RuntimeError(f"head object failed {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(f"head object failed: {exc}") from exc
    return False

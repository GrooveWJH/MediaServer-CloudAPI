from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from ..utils.aws_sigv4 import aws_v4_headers


def _encode_path(path):
    return quote(path, safe="/-_.~")


class S3Client:
    def __init__(self, storage_config):
        self._storage = storage_config
        parsed = urlparse(storage_config.endpoint)
        if not parsed.scheme or not parsed.netloc:
            raise RuntimeError(f"invalid storage endpoint: {storage_config.endpoint}")
        self._endpoint = parsed

    def head_object(self, object_key):
        bucket_prefix = f"{self._storage.bucket}/"
        candidates = [object_key.lstrip("/")]
        if not object_key.startswith(bucket_prefix):
            candidates.append(f"{bucket_prefix}{object_key.lstrip('/')}")

        for candidate in candidates:
            path = f"/{self._storage.bucket}/{candidate}"
            canonical_uri = _encode_path(path)
            url = f"{self._endpoint.scheme}://{self._endpoint.netloc}{canonical_uri}"
            headers = aws_v4_headers(
                self._storage.access_key,
                self._storage.secret_key,
                self._storage.region,
                "s3",
                "HEAD",
                self._endpoint.netloc,
                canonical_uri,
                b"",
            )
            headers["host"] = self._endpoint.netloc
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

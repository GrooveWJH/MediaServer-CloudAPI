#!/usr/bin/env python3
import os
import sys

repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
src_root = os.path.join(repo_root, "src")
sys.path.insert(0, src_root)

from media_server.config.storage import StorageConfig
from media_server.handlers.sts import _resolve_public_endpoint


class _FakeConfig:
    def __init__(self, storage):
        self.storage = storage


class _FakeHandler:
    def __init__(self, storage, headers):
        self.config = _FakeConfig(storage)
        self.headers = headers


def _assert_equal(actual, expected, message):
    if actual != expected:
        raise AssertionError(f"{message}: expected={expected}, actual={actual}")


def _make_storage(**kwargs):
    base = dict(
        endpoint="http://127.0.0.1:9000",
        bucket="media",
        region="us-east-1",
        access_key="minioadmin",
        secret_key="minioadmin",
        session_token="",
        provider="minio",
        public_endpoint="",
        public_port=9000,
        trust_forwarded_headers=False,
    )
    base.update(kwargs)
    return StorageConfig(**base)


def main():
    storage = _make_storage(public_endpoint="https://minio.example.com")
    handler = _FakeHandler(storage, {"Host": "192.168.10.228:8090"})
    _assert_equal(
        _resolve_public_endpoint(handler),
        "https://minio.example.com:9000",
        "explicit endpoint should win and append default public port",
    )

    storage = _make_storage(trust_forwarded_headers=True)
    handler = _FakeHandler(
        storage,
        {
            "Host": "10.0.0.5:8090",
            "X-Forwarded-Host": "192.168.10.228:18090",
            "X-Forwarded-Proto": "https",
        },
    )
    _assert_equal(
        _resolve_public_endpoint(handler),
        "https://192.168.10.228:9000",
        "forwarded headers should use host and configured public port",
    )

    storage = _make_storage(trust_forwarded_headers=False)
    handler = _FakeHandler(
        storage,
        {
            "Host": "10.0.0.5:8090",
            "X-Forwarded-Host": "192.168.10.228:18090",
            "X-Forwarded-Proto": "https",
        },
    )
    _assert_equal(
        _resolve_public_endpoint(handler),
        "http://10.0.0.5:9000",
        "Host should use configured public port when forwarded headers are not trusted",
    )

    storage = _make_storage(public_port=9000)
    handler = _FakeHandler(storage, {"Host": "192.168.10.228"})
    _assert_equal(
        _resolve_public_endpoint(handler),
        "http://192.168.10.228:9000",
        "Host without port should use configured public port",
    )

    storage = _make_storage()
    handler = _FakeHandler(storage, {"Host": "[2001:db8::1]:8090"})
    _assert_equal(
        _resolve_public_endpoint(handler),
        "http://[2001:db8::1]:9000",
        "IPv6 host should use configured public port",
    )

    storage = _make_storage()
    handler = _FakeHandler(storage, {"Host": "bad/host"})
    _assert_equal(
        _resolve_public_endpoint(handler),
        "http://127.0.0.1:9000",
        "invalid host should fallback to internal storage endpoint",
    )

    storage = _make_storage(trust_forwarded_headers=True)
    handler = _FakeHandler(
        storage,
        {
            "Host": "192.168.10.228:8090",
            "X-Forwarded-Host": "proxy-a:9000, proxy-b:9000",
            "X-Forwarded-Proto": "http,https",
        },
    )
    _assert_equal(
        _resolve_public_endpoint(handler),
        "http://proxy-a:9000",
        "forwarded headers should use first value and configured public port",
    )

    print("[test] sts endpoint resolver OK")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[test] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

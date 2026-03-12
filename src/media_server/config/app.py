import argparse
from dataclasses import dataclass

from .server import ServerConfig
from .storage import StorageConfig
from .sts import STSConfig


@dataclass(frozen=True)
class AppConfig:
    server: ServerConfig
    storage: StorageConfig
    sts: STSConfig
    db_path: str
    log_level: str


def parse_bool(value):
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"invalid boolean value: {value}")


def parse_args():
    parser = argparse.ArgumentParser(description="DJI Media Management Server (Fast Upload)")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    parser.add_argument("--port", type=int, default=8090, help="Bind port")
    parser.add_argument("--token", default="demo-token", help="Fixed x-auth-token")
    parser.add_argument("--storage-endpoint", default="http://127.0.0.1:9000", help="Object storage endpoint")
    parser.add_argument("--storage-bucket", default="media", help="Object storage bucket")
    parser.add_argument("--storage-region", default="us-east-1", help="Object storage region")
    parser.add_argument("--storage-access-key", default="minioadmin", help="Object storage access key")
    parser.add_argument("--storage-secret-key", default="minioadmin", help="Object storage secret key")
    parser.add_argument("--storage-session-token", default="", help="Object storage session token")
    parser.add_argument("--storage-provider", default="minio", help="Object storage provider")
    parser.add_argument(
        "--storage-public-endpoint",
        default="",
        help="Public object storage endpoint returned to clients in STS response",
    )
    parser.add_argument(
        "--storage-public-port",
        type=int,
        default=9000,
        help="Public object storage endpoint port when Host has no explicit port",
    )
    parser.add_argument(
        "--trust-forwarded-headers",
        type=parse_bool,
        default=False,
        help="Trust X-Forwarded-Host/Proto headers for public endpoint resolution",
    )
    parser.add_argument("--storage-sts-role-arn", default="arn:aws:iam::minio:role/dji-pilot", help="MinIO STS role ARN")
    parser.add_argument("--storage-sts-policy", default="", help="MinIO STS policy JSON")
    parser.add_argument("--storage-sts-duration", type=int, default=3600, help="MinIO STS duration seconds")
    parser.add_argument("--db-path", default="data/media.db", help="SQLite DB path")
    parser.add_argument("--log-level", default="info", help="Log level: debug/info/warning/error/critical")
    args = parser.parse_args()
    return AppConfig(
        server=ServerConfig(
            host=args.host,
            port=args.port,
            token=args.token,
        ),
        storage=StorageConfig(
            endpoint=args.storage_endpoint,
            bucket=args.storage_bucket,
            region=args.storage_region,
            access_key=args.storage_access_key,
            secret_key=args.storage_secret_key,
            session_token=args.storage_session_token,
            provider=args.storage_provider,
            public_endpoint=args.storage_public_endpoint,
            public_port=args.storage_public_port,
            trust_forwarded_headers=args.trust_forwarded_headers,
        ),
        sts=STSConfig(
            role_arn=args.storage_sts_role_arn,
            policy=args.storage_sts_policy,
            duration=args.storage_sts_duration,
        ),
        db_path=args.db_path,
        log_level=args.log_level,
    )

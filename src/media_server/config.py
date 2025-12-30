import argparse
from dataclasses import dataclass


@dataclass
class ServerConfig:
    host: str
    port: int
    token: str
    storage_endpoint: str
    storage_bucket: str
    storage_region: str
    storage_access_key: str
    storage_secret_key: str
    storage_session_token: str
    storage_provider: str
    storage_sts_role_arn: str
    storage_sts_policy: str
    storage_sts_duration: int
    db_path: str


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
    parser.add_argument("--storage-sts-role-arn", default="arn:aws:iam::minio:role/dji-pilot", help="MinIO STS role ARN")
    parser.add_argument("--storage-sts-policy", default="", help="MinIO STS policy JSON")
    parser.add_argument("--storage-sts-duration", type=int, default=3600, help="MinIO STS duration seconds")
    parser.add_argument("--db-path", default="data/media.db", help="SQLite DB path")
    args = parser.parse_args()
    return ServerConfig(
        host=args.host,
        port=args.port,
        token=args.token,
        storage_endpoint=args.storage_endpoint,
        storage_bucket=args.storage_bucket,
        storage_region=args.storage_region,
        storage_access_key=args.storage_access_key,
        storage_secret_key=args.storage_secret_key,
        storage_session_token=args.storage_session_token,
        storage_provider=args.storage_provider,
        storage_sts_role_arn=args.storage_sts_role_arn,
        storage_sts_policy=args.storage_sts_policy,
        storage_sts_duration=args.storage_sts_duration,
        db_path=args.db_path,
    )

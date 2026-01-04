#!/usr/bin/env python3
"""
Entry point for the DJI media management server.
Keep this file thin to match the project layout.
"""

import os
import sys
from contextlib import contextmanager

import typer

if __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from media_server.app import main as app_main

cli = typer.Typer(add_completion=False)


@contextmanager
def _override_argv(args):
    original = sys.argv[:]
    sys.argv = args
    try:
        yield
    finally:
        sys.argv = original


@cli.callback(invoke_without_command=True)
def run(
    host: str = typer.Option("0.0.0.0", "--host", help="Bind host"),
    port: int = typer.Option(8090, "--port", help="Bind port"),
    token: str = typer.Option("demo-token", "--token", help="Fixed x-auth-token"),
    storage_endpoint: str = typer.Option("http://127.0.0.1:9000", "--storage-endpoint", help="Object storage endpoint"),
    storage_bucket: str = typer.Option("media", "--storage-bucket", help="Object storage bucket"),
    storage_region: str = typer.Option("us-east-1", "--storage-region", help="Object storage region"),
    storage_access_key: str = typer.Option("minioadmin", "--storage-access-key", help="Object storage access key"),
    storage_secret_key: str = typer.Option("minioadmin", "--storage-secret-key", help="Object storage secret key"),
    storage_session_token: str = typer.Option("", "--storage-session-token", help="Object storage session token"),
    storage_provider: str = typer.Option("minio", "--storage-provider", help="Object storage provider"),
    storage_sts_role_arn: str = typer.Option(
        "arn:aws:iam::minio:role/dji-pilot", "--storage-sts-role-arn", help="MinIO STS role ARN"
    ),
    storage_sts_policy: str = typer.Option("", "--storage-sts-policy", help="MinIO STS policy JSON"),
    storage_sts_duration: int = typer.Option(3600, "--storage-sts-duration", help="MinIO STS duration seconds"),
    db_path: str = typer.Option("data/media.db", "--db-path", help="SQLite DB path"),
    log_level: str = typer.Option("info", "--log-level", help="Log level: debug/info/warning/error/critical"),
):
    argv = [
        sys.argv[0],
        "--host",
        host,
        "--port",
        str(port),
        "--token",
        token,
        "--storage-endpoint",
        storage_endpoint,
        "--storage-bucket",
        storage_bucket,
        "--storage-region",
        storage_region,
        "--storage-access-key",
        storage_access_key,
        "--storage-secret-key",
        storage_secret_key,
        "--storage-session-token",
        storage_session_token,
        "--storage-provider",
        storage_provider,
        "--storage-sts-role-arn",
        storage_sts_role_arn,
        "--storage-sts-policy",
        storage_sts_policy,
        "--storage-sts-duration",
        str(storage_sts_duration),
        "--db-path",
        db_path,
        "--log-level",
        log_level,
    ]
    with _override_argv(argv):
        app_main()


if __name__ == "__main__":
    cli()

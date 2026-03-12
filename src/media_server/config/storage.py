from dataclasses import dataclass


@dataclass(frozen=True)
class StorageConfig:
    endpoint: str
    bucket: str
    region: str
    access_key: str
    secret_key: str
    session_token: str
    provider: str
    public_endpoint: str = ""
    public_port: int = 9000
    trust_forwarded_headers: bool = False

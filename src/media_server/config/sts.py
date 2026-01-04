from dataclasses import dataclass


@dataclass(frozen=True)
class STSConfig:
    role_arn: str
    policy: str
    duration: int

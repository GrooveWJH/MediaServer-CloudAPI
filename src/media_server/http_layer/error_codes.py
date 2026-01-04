from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorDef:
    status: int
    code: int
    message: str


ERR_NOT_FOUND = ErrorDef(404, 404, "not found")
ERR_INVALID_JSON = ErrorDef(400, 400, "invalid json")
ERR_MISSING_TOKEN = ErrorDef(401, 401, "missing x-auth-token")
ERR_INVALID_TOKEN = ErrorDef(401, 401, "invalid x-auth-token")
ERR_MISSING_FINGERPRINT_NAME = ErrorDef(400, 400, "missing fingerprint/name")
ERR_INVALID_TINY_FINGERPRINTS = ErrorDef(400, 400, "invalid tiny_fingerprints")
ERR_MISSING_OBJECT_KEY = ErrorDef(400, 400, "missing object_key")
ERR_STS_FAILED = ErrorDef(500, 500, "sts failed")
ERR_OBJECT_CHECK_FAILED = ErrorDef(502, 502, "object check failed")
ERR_OBJECT_NOT_FOUND = ErrorDef(404, 404, "object not found")

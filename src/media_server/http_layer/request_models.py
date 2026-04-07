from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .error_codes import (
    ERR_INVALID_TINY_FINGERPRINTS,
    ERR_MISSING_FINGERPRINT_NAME,
    ERR_MISSING_OBJECT_KEY,
)


@dataclass(frozen=True)
class FastUploadRequest:
    fingerprint: str
    name: str
    path: Optional[str]
    tiny_fingerprint: Optional[str]
    is_original: Optional[bool]
    sub_file_type: Optional[str]
    metadata: Optional[Dict[str, Any]]


@dataclass(frozen=True)
class TinyFingerprintsRequest:
    tiny_fingerprints: List[str]


@dataclass(frozen=True)
class UploadCallbackRequest:
    object_key: str
    fingerprint: Optional[str]
    tiny_fingerprint: Optional[str]
    name: Optional[str]
    path: Optional[str]
    is_original: Optional[bool]
    sub_file_type: Optional[str]
    metadata: Optional[Dict[str, Any]]


def _normalize_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    return None


def _normalize_sub_file_type(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_metadata(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    return value


def parse_fast_upload(payload: Dict[str, Any]) -> Tuple[Optional[FastUploadRequest], Optional[object]]:
    fingerprint = payload.get("fingerprint")
    name = payload.get("name")
    if not fingerprint or not name:
        return None, ERR_MISSING_FINGERPRINT_NAME

    ext = payload.get("ext") or {}
    if not isinstance(ext, dict):
        ext = {}
    tiny_fingerprint = ext.get("tinny_fingerprint")
    return FastUploadRequest(
        fingerprint=fingerprint,
        name=name,
        path=payload.get("path"),
        tiny_fingerprint=tiny_fingerprint,
        is_original=_normalize_bool(ext.get("is_original")),
        sub_file_type=_normalize_sub_file_type(payload.get("sub_file_type")),
        metadata=_normalize_metadata(payload.get("metadata")),
    ), None


def parse_tiny_fingerprints(payload: Dict[str, Any]) -> Tuple[Optional[TinyFingerprintsRequest], Optional[object]]:
    requested = payload.get("tiny_fingerprints") or []
    if not isinstance(requested, list):
        return None, ERR_INVALID_TINY_FINGERPRINTS
    return TinyFingerprintsRequest(tiny_fingerprints=requested), None


def parse_upload_callback(payload: Dict[str, Any]) -> Tuple[Optional[UploadCallbackRequest], Optional[object]]:
    object_key = payload.get("object_key")
    if not object_key:
        return None, ERR_MISSING_OBJECT_KEY
    tiny_fingerprint = payload.get("tiny_fingerprint") or payload.get("tinny_fingerprint")
    ext = payload.get("ext") or {}
    if not isinstance(ext, dict):
        ext = {}
    return UploadCallbackRequest(
        object_key=object_key,
        fingerprint=payload.get("fingerprint"),
        tiny_fingerprint=tiny_fingerprint,
        name=payload.get("name"),
        path=payload.get("path"),
        is_original=_normalize_bool(ext.get("is_original")),
        sub_file_type=_normalize_sub_file_type(payload.get("sub_file_type")),
        metadata=_normalize_metadata(payload.get("metadata")),
    ), None

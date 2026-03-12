import json
import logging
from http import HTTPStatus
from urllib.parse import urlparse

from ..http_layer.error_codes import ERR_STS_FAILED
from ..storage.sts import fetch_minio_sts
from ..utils.http import error_response, json_response


def _first_header_value(raw_value):
    if not raw_value:
        return ""
    return raw_value.split(",", 1)[0].strip()


def _parse_host_port(authority):
    authority = (authority or "").strip()
    if not authority or "/" in authority or "@" in authority:
        return "", None

    host = ""
    port = None

    if authority.startswith("["):
        closing = authority.find("]")
        if closing <= 1:
            return "", None
        host = authority[1:closing].strip()
        tail = authority[closing + 1 :].strip()
        if tail:
            if not tail.startswith(":"):
                return "", None
            tail_port = tail[1:]
            if not tail_port.isdigit():
                return "", None
            port = int(tail_port)
    else:
        colon_count = authority.count(":")
        if colon_count == 0:
            host = authority
        elif colon_count == 1:
            host, maybe_port = authority.rsplit(":", 1)
            host = host.strip()
            maybe_port = maybe_port.strip()
            if not maybe_port.isdigit():
                return "", None
            port = int(maybe_port)
        else:
            # Unbracketed IPv6 without explicit port.
            host = authority

    if not host or any(ch.isspace() for ch in host):
        return "", None
    if port is not None and (port < 1 or port > 65535):
        return "", None
    return host, port


def _format_host_port(host, port):
    rendered_host = host
    if ":" in host and not host.startswith("["):
        rendered_host = f"[{host}]"
    if port is None:
        return rendered_host
    return f"{rendered_host}:{port}"


def _build_endpoint_from_authority(authority, scheme, default_port, preserve_authority_port):
    host, port = _parse_host_port(authority)
    if not host:
        return ""
    normalized_scheme = (scheme or "").lower()
    if normalized_scheme not in {"http", "https"}:
        return ""
    resolved_port = port if (preserve_authority_port and port is not None) else default_port
    if resolved_port < 1 or resolved_port > 65535:
        return ""
    return f"{normalized_scheme}://{_format_host_port(host, resolved_port)}"


def _normalize_endpoint(raw_endpoint, default_scheme, default_port):
    candidate = (raw_endpoint or "").strip()
    if not candidate:
        return ""
    if "://" in candidate:
        parsed = urlparse(candidate)
        if not parsed.scheme or not parsed.netloc:
            return ""
        if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
            return ""
        return _build_endpoint_from_authority(
            parsed.netloc,
            parsed.scheme,
            default_port,
            preserve_authority_port=True,
        )
    return _build_endpoint_from_authority(
        candidate,
        default_scheme,
        default_port,
        preserve_authority_port=True,
    )


def _resolve_public_endpoint(handler):
    storage = handler.config.storage
    parsed_internal = urlparse(storage.endpoint)
    default_scheme = parsed_internal.scheme or "http"
    default_port = storage.public_port if storage.public_port > 0 else 9000

    if storage.public_endpoint:
        resolved = _normalize_endpoint(storage.public_endpoint, default_scheme, default_port)
        if resolved:
            return resolved
        logging.warning(
            "invalid storage_public_endpoint=%s, fallback to header-based resolution",
            storage.public_endpoint,
        )

    if storage.trust_forwarded_headers:
        forwarded_host = _first_header_value(handler.headers.get("X-Forwarded-Host", ""))
        if forwarded_host:
            forwarded_proto = _first_header_value(handler.headers.get("X-Forwarded-Proto", ""))
            forwarded_scheme = forwarded_proto or default_scheme
            resolved = _build_endpoint_from_authority(
                forwarded_host,
                forwarded_scheme,
                default_port,
                preserve_authority_port=False,
            )
            if resolved:
                return resolved
            logging.warning(
                "invalid X-Forwarded-Host/Proto host=%s proto=%s, fallback to Host",
                forwarded_host,
                forwarded_scheme,
            )

    host_header = _first_header_value(handler.headers.get("Host", ""))
    if host_header:
        resolved = _build_endpoint_from_authority(
            host_header,
            default_scheme,
            default_port,
            preserve_authority_port=False,
        )
        if resolved:
            return resolved
        logging.warning("invalid Host header=%s, fallback to storage.endpoint", host_header)

    logging.warning("cannot resolve public endpoint from headers, fallback to storage.endpoint=%s", storage.endpoint)
    return storage.endpoint


def handle_sts(handler, workspace_id):
    token = handler.require_token()
    if not token:
        return

    public_endpoint = _resolve_public_endpoint(handler)
    logging.debug(
        "sts request config internal_endpoint=%s public_endpoint=%s bucket=%s region=%s role_arn=%s duration=%s policy_len=%s",
        handler.config.storage.endpoint,
        public_endpoint,
        handler.config.storage.bucket,
        handler.config.storage.region,
        handler.config.sts.role_arn,
        handler.config.sts.duration,
        len(handler.config.sts.policy or ""),
    )
    try:
        security_token, access_key, secret_key, expire_seconds = fetch_minio_sts(
            handler.config.storage,
            handler.config.sts,
            workspace_id,
        )
    except RuntimeError as exc:
        logging.error("sts error=%s", exc)
        error_response(handler, ERR_STS_FAILED)
        return

    logging.debug(
        "sts issued access_key_id=%s token_len=%s expire_seconds=%s",
        access_key,
        len(security_token or ""),
        expire_seconds,
    )

    payload = {
        "code": 0,
        "message": "success",
        "data": {
            "provider": handler.config.storage.provider,
            "endpoint": public_endpoint,
            "bucket": handler.config.storage.bucket,
            "region": handler.config.storage.region,
            "object_key_prefix": f"{workspace_id}/",
            "access_key_id": access_key,
            "access_key_secret": secret_key,
            "security_token": security_token,
            "session_token": security_token,
            "accessKeyId": access_key,
            "accessKeySecret": secret_key,
            "securityToken": security_token,
            "sessionToken": security_token,
            "expire": expire_seconds,
            "credentials": {
                "access_key_id": access_key,
                "access_key_secret": secret_key,
                "security_token": security_token,
                "session_token": security_token,
                "accessKeyId": access_key,
                "accessKeySecret": secret_key,
                "securityToken": security_token,
                "sessionToken": security_token,
                "expire": expire_seconds
            }
        }
    }

    logging.debug(
        "sts response fields=%s",
        sorted(payload["data"]["credentials"].keys()),
    )
    logging.debug("sts response payload=%s", json.dumps(payload, ensure_ascii=True))
    logging.info(
        "sts workspace_id=%s token=%s",
        workspace_id,
        token,
    )
    json_response(handler, HTTPStatus.OK, payload)

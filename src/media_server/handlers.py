import json
import logging
from http import HTTPStatus

from .http_utils import build_object_key, json_response
from .s3_client import head_object
from .sts import fetch_minio_sts


def handle_fast_upload(handler, workspace_id):
    token = handler.require_token()
    if not token:
        return

    try:
        payload = handler.read_json()
    except json.JSONDecodeError:
        json_response(handler, HTTPStatus.BAD_REQUEST, {"code": 400, "message": "invalid json", "data": {}})
        return

    fingerprint = payload.get("fingerprint")
    name = payload.get("name")
    if not fingerprint or not name:
        json_response(handler, HTTPStatus.BAD_REQUEST, {"code": 400, "message": "missing fingerprint/name", "data": {}})
        return

    ext = payload.get("ext") or {}
    tiny_fingerprint = ext.get("tinny_fingerprint")
    object_key = build_object_key(workspace_id, name)
    if tiny_fingerprint:
        handler.pending_tiny_by_fingerprint[fingerprint] = tiny_fingerprint

    logging.info(
        "fast-upload workspace_id=%s name=%s path=%s fingerprint=%s tiny=%s token=%s",
        workspace_id,
        name,
        payload.get("path"),
        fingerprint,
        tiny_fingerprint,
        token,
    )
    logging.debug("fast-upload fingerprints: fingerprint=%s tiny=%s", fingerprint, tiny_fingerprint)

    stored_key = handler.db.get_object_key_by_fingerprint(workspace_id, fingerprint)
    if stored_key:
        try:
            exists = head_object(handler.config, stored_key)
        except RuntimeError as exc:
            logging.error("fast-upload head check failed: %s", exc)
            exists = False
        if exists:
            json_response(handler, HTTPStatus.OK, {"code": 0, "message": "success", "data": {"object_key": stored_key}})
            return
        handler.db.delete_by_fingerprint(workspace_id, fingerprint)
    json_response(
        handler,
        HTTPStatus.OK,
        {"code": 1, "message": f"{fingerprint} don't exist.", "data": {}},
    )


def handle_tiny_fingerprints(handler, workspace_id):
    token = handler.require_token()
    if not token:
        return

    try:
        payload = handler.read_json()
    except json.JSONDecodeError:
        json_response(handler, HTTPStatus.BAD_REQUEST, {"code": 400, "message": "invalid json", "data": {}})
        return

    requested = payload.get("tiny_fingerprints") or []
    if not isinstance(requested, list):
        json_response(handler, HTTPStatus.BAD_REQUEST, {"code": 400, "message": "invalid tiny_fingerprints", "data": {}})
        return

    found = []
    for fp in requested:
        object_key = handler.db.get_object_key_by_tiny(workspace_id, fp)
        if not object_key:
            continue
        try:
            exists = head_object(handler.config, object_key)
        except RuntimeError as exc:
            logging.error("tiny-fingerprints head check failed: %s", exc)
            exists = False
        if exists:
            found.append(fp)
            continue
        handler.db.delete_by_tiny(workspace_id, fp)

    logging.info(
        "tiny-fingerprints workspace_id=%s requested=%s found=%s token=%s",
        workspace_id,
        len(requested),
        len(found),
        token,
    )

    json_response(handler, HTTPStatus.OK, {"code": 0, "message": "success", "data": {"tiny_fingerprints": found}})


def handle_sts(handler, workspace_id):
    token = handler.require_token()
    if not token:
        return

    try:
        security_token, access_key, secret_key, expire_seconds = fetch_minio_sts(handler.config, workspace_id)
    except RuntimeError as exc:
        logging.error("sts error=%s", exc)
        json_response(handler, HTTPStatus.INTERNAL_SERVER_ERROR, {"code": 500, "message": "sts failed", "data": {}})
        return

    payload = {
        "code": 0,
        "message": "success",
        "data": {
            "provider": handler.config.storage_provider,
            "endpoint": handler.config.storage_endpoint,
            "bucket": handler.config.storage_bucket,
            "region": handler.config.storage_region,
            "object_key_prefix": f"media/{workspace_id}/",
            "credentials": {
                "access_key_id": access_key,
                "access_key_secret": secret_key,
                "security_token": security_token,
                "expire": expire_seconds
            }
        }
    }

    logging.debug("sts response payload=%s", json.dumps(payload, ensure_ascii=True))
    logging.info(
        "sts workspace_id=%s token=%s",
        workspace_id,
        token,
    )
    json_response(handler, HTTPStatus.OK, payload)


def handle_upload_callback(handler, workspace_id):
    token = handler.require_token()
    if not token:
        return

    try:
        payload = handler.read_json()
    except json.JSONDecodeError:
        json_response(handler, HTTPStatus.BAD_REQUEST, {"code": 400, "message": "invalid json", "data": {}})
        return

    object_key = payload.get("object_key")
    if not object_key:
        json_response(handler, HTTPStatus.BAD_REQUEST, {"code": 400, "message": "missing object_key", "data": {}})
        return

    fingerprint = payload.get("fingerprint")
    tiny_fingerprint = payload.get("tiny_fingerprint") or payload.get("tinny_fingerprint")
    if not tiny_fingerprint and fingerprint:
        tiny_fingerprint = handler.pending_tiny_by_fingerprint.pop(fingerprint, None)
    if fingerprint:
        handler.db.upsert_file(
            workspace_id,
            fingerprint,
            tiny_fingerprint,
            object_key,
            payload.get("name"),
            payload.get("path"),
        )

    handler.upload_records.append(
        {
            "workspace_id": workspace_id,
            "name": payload.get("name"),
            "object_key": object_key,
            "fingerprint": fingerprint,
        }
    )

    logging.info(
        "upload-callback workspace_id=%s name=%s object_key=%s token=%s",
        workspace_id,
        payload.get("name"),
        object_key,
        token,
    )
    logging.debug("upload-callback fingerprints: fingerprint=%s tiny=%s", fingerprint, tiny_fingerprint)

    json_response(handler, HTTPStatus.OK, {"code": 0, "message": "success", "data": object_key})

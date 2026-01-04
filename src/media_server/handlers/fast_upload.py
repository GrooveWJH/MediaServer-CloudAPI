import logging
from http import HTTPStatus

from ..utils.http import ok_response
from ..http_layer.request_models import parse_fast_upload
from ..storage.s3_client import S3Client
from .common import parse_request, read_payload


def handle_fast_upload(handler, workspace_id):
    token = handler.require_token()
    if not token:
        return

    payload = read_payload(handler)
    if payload is None:
        return

    req = parse_request(handler, payload, parse_fast_upload)
    if not req:
        return

    if req.tiny_fingerprint:
        handler.db.upsert_fingerprint_tiny(
            workspace_id,
            req.fingerprint,
            req.tiny_fingerprint,
            file_name=req.name,
            file_path=req.path,
        )

    logging.info(
        "fast-upload workspace_id=%s name=%s path=%s fingerprint=%s tiny=%s token=%s",
        workspace_id,
        req.name,
        req.path,
        req.fingerprint,
        req.tiny_fingerprint,
        token,
    )
    logging.debug("fast-upload fingerprints: fingerprint=%s tiny=%s", req.fingerprint, req.tiny_fingerprint)

    stored_key = handler.db.get_object_key_by_fingerprint(workspace_id, req.fingerprint)
    if stored_key:
        try:
            exists = S3Client(handler.config.storage).head_object(stored_key)
        except RuntimeError as exc:
            logging.error("fast-upload head check failed: %s", exc)
            exists = False
        if exists:
            ok_response(handler, {"object_key": stored_key}, status=HTTPStatus.OK)
            return
        handler.db.delete_by_fingerprint(workspace_id, req.fingerprint)
    ok_response(handler, {}, message=f"{req.fingerprint} don't exist.", code=1, status=HTTPStatus.OK)

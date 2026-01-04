import logging
from http import HTTPStatus

from ..http_layer.error_codes import ERR_OBJECT_CHECK_FAILED, ERR_OBJECT_NOT_FOUND
from ..utils.http import error_response, ok_response
from ..http_layer.request_models import parse_upload_callback
from ..storage.s3_client import S3Client
from .common import parse_request, read_payload


def handle_upload_callback(handler, workspace_id):
    token = handler.require_token()
    if not token:
        return

    payload = read_payload(handler)
    if payload is None:
        return

    req = parse_request(handler, payload, parse_upload_callback)
    if not req:
        return

    try:
        object_exists = S3Client(handler.config.storage).head_object(req.object_key)
    except RuntimeError as exc:
        logging.error("upload-callback head check failed: %s", exc)
        error_response(handler, ERR_OBJECT_CHECK_FAILED)
        return

    if not object_exists:
        logging.warning("upload-callback object missing: %s", req.object_key)
        error_response(handler, ERR_OBJECT_NOT_FOUND)
        return

    tiny_fingerprint = req.tiny_fingerprint
    with handler.db.transaction() as conn:
        if not tiny_fingerprint and req.fingerprint:
            tiny_fingerprint = handler.db.get_tiny_by_fingerprint(workspace_id, req.fingerprint, conn=conn)
        if req.fingerprint:
            handler.db.upsert_file(
                workspace_id,
                req.fingerprint,
                tiny_fingerprint,
                req.object_key,
                req.name,
                req.path,
                conn=conn,
            )

    logging.info(
        "upload-callback workspace_id=%s name=%s object_key=%s token=%s",
        workspace_id,
        req.name,
        req.object_key,
        token,
    )
    logging.debug("upload-callback fingerprints: fingerprint=%s tiny=%s", req.fingerprint, tiny_fingerprint)

    ok_response(handler, req.object_key, status=HTTPStatus.OK)

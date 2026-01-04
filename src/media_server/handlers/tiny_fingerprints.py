import logging
from http import HTTPStatus

from ..utils.http import ok_response
from ..http_layer.request_models import parse_tiny_fingerprints
from ..storage.s3_client import S3Client
from .common import parse_request, read_payload


def handle_tiny_fingerprints(handler, workspace_id):
    token = handler.require_token()
    if not token:
        return

    payload = read_payload(handler)
    if payload is None:
        return

    req = parse_request(handler, payload, parse_tiny_fingerprints)
    if not req:
        return

    found = []
    s3_client = S3Client(handler.config.storage)
    for fp in req.tiny_fingerprints:
        object_key = handler.db.get_object_key_by_tiny(workspace_id, fp)
        if not object_key:
            continue
        try:
            exists = s3_client.head_object(object_key)
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
        len(req.tiny_fingerprints),
        len(found),
        token,
    )

    ok_response(handler, {"tiny_fingerprints": found}, status=HTTPStatus.OK)

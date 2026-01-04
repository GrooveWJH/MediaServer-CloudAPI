import json
import logging
from http import HTTPStatus

from ..http_layer.error_codes import ERR_STS_FAILED
from ..utils.http import error_response, json_response
from ..storage.sts import fetch_minio_sts


def handle_sts(handler, workspace_id):
    token = handler.require_token()
    if not token:
        return

    logging.debug(
        "sts request config endpoint=%s bucket=%s region=%s role_arn=%s duration=%s policy_len=%s",
        handler.config.storage.endpoint,
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
            "endpoint": handler.config.storage.endpoint,
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

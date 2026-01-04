import json
import logging
import time

from ..http_layer.error_codes import ErrorDef
from ..utils.security import clean_filename


def ok_response(handler, data, message="success", code=0, status=200):
    payload = {"code": code, "message": message, "data": data}
    json_response(handler, status, payload)


def error_response(handler, err, message_override=None):
    if isinstance(err, ErrorDef):
        status = err.status
        code = err.code
        message = err.message
    else:
        status = int(err)
        code = int(err)
        message = message_override or "error"
    if message_override:
        message = message_override
    payload = {"code": code, "message": message, "data": {}}
    if status >= 500:
        logging.error("error response status=%s message=%s path=%s", status, message, getattr(handler, "path", ""))
    elif status >= 400:
        logging.warning("client error status=%s message=%s path=%s", status, message, getattr(handler, "path", ""))
    json_response(handler, status, payload)


def json_response(handler, status, payload):
    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
    if logging.getLogger().isEnabledFor(logging.DEBUG):
        summary = payload
        path = getattr(handler, "path", "")
        if "/storage/api/" in path and path.endswith("/sts"):
            data = payload.get("data") if isinstance(payload, dict) else {}
            summary = {
                "code": payload.get("code") if isinstance(payload, dict) else None,
                "message": payload.get("message") if isinstance(payload, dict) else None,
                "data_keys": sorted(data.keys()) if isinstance(data, dict) else [],
            }
        logging.debug(
            "response %s %s status=%s payload=%s",
            getattr(handler, "command", ""),
            path,
            status,
            summary,
        )


def build_object_key(workspace_id, filename):
    safe_name = clean_filename(filename)
    date_part = time.strftime("%Y%m%d", time.localtime())
    return f"{workspace_id}/{date_part}/{safe_name}"

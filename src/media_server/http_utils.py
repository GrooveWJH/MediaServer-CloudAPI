import json
import logging
import time


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
    safe_name = (filename or "unknown").replace("/", "_")
    date_part = time.strftime("%Y%m%d", time.localtime())
    return f"{workspace_id}/{date_part}/{safe_name}"

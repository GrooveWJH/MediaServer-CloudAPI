import json
import time


def json_response(handler, status, payload):
    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def build_object_key(workspace_id, filename):
    safe_name = (filename or "unknown").replace("/", "_")
    date_part = time.strftime("%Y%m%d", time.localtime())
    return f"media/{workspace_id}/{date_part}/{safe_name}"

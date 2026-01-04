import json
from typing import Callable, Optional, Tuple, TypeVar

from ..http_layer.error_codes import ERR_INVALID_JSON
from ..utils.http import error_response

T = TypeVar("T")


def read_payload(handler) -> Optional[dict]:
    try:
        return handler.read_json()
    except json.JSONDecodeError:
        error_response(handler, ERR_INVALID_JSON)
        return None


def parse_request(handler, payload: dict, parser: Callable[[dict], Tuple[Optional[T], Optional[object]]]) -> Optional[T]:
    req, error = parser(payload)
    if error:
        error_response(handler, error)
        return None
    return req

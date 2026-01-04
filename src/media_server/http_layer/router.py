import re
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class Route:
    name: str
    method: str
    pattern: re.Pattern


ROUTES = (
    Route("fast-upload", "POST", re.compile(r"^/media/api/v1/workspaces/(?P<workspace_id>[^/]+)/fast-upload$")),
    Route(
        "tiny-fingerprints",
        "POST",
        re.compile(r"^/media/api/v1/workspaces/(?P<workspace_id>[^/]+)/files/tiny-fingerprints$"),
    ),
    Route("upload-callback", "POST", re.compile(r"^/media/api/v1/workspaces/(?P<workspace_id>[^/]+)/upload-callback$")),
    Route("sts", "POST", re.compile(r"^/storage/api/v1/workspaces/(?P<workspace_id>[^/]+)/sts$")),
)


def resolve_route(method: str, path: str) -> Tuple[Optional[str], Optional[str]]:
    for route in ROUTES:
        if route.method != method:
            continue
        match = route.pattern.match(path)
        if not match:
            continue
        return route.name, match.group("workspace_id")
    return None, None

def match_fast_upload(path):
    parts = [p for p in path.split("/") if p]
    if len(parts) != 6:
        return None
    if parts[0] != "media" or parts[1] != "api" or parts[2] != "v1":
        return None
    if parts[3] != "workspaces" or parts[5] != "fast-upload":
        return None
    return parts[4]


def match_tiny_fingerprints(path):
    parts = [p for p in path.split("/") if p]
    if len(parts) != 7:
        return None
    if parts[0] != "media" or parts[1] != "api" or parts[2] != "v1":
        return None
    if parts[3] != "workspaces" or parts[5] != "files" or parts[6] != "tiny-fingerprints":
        return None
    return parts[4]


def match_upload_callback(path):
    parts = [p for p in path.split("/") if p]
    if len(parts) != 6:
        return None
    if parts[0] != "media" or parts[1] != "api" or parts[2] != "v1":
        return None
    if parts[3] != "workspaces" or parts[5] != "upload-callback":
        return None
    return parts[4]


def match_sts(path):
    parts = [p for p in path.split("/") if p]
    if len(parts) != 6:
        return None
    if parts[0] != "storage" or parts[1] != "api" or parts[2] != "v1":
        return None
    if parts[3] != "workspaces" or parts[5] != "sts":
        return None
    return parts[4]

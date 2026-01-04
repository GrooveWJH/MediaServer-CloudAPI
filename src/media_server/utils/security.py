import os


def clean_filename(name):
    if not name:
        return "unknown"
    name = name.replace("\x00", "")
    name = name.replace("/", "_").replace("\\", "_")
    name = os.path.basename(name)
    name = name.strip() or "unknown"
    return name

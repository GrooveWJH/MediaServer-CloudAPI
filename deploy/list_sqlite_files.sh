#!/usr/bin/env bash
set -euo pipefail

DB_PATH=""

usage() {
  cat <<'USAGE'
Usage:
  ./deploy/list_sqlite_files.sh --db /path/to/media.db

Description:
  Query SQLite media entries and print file name + time fields.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --db)
      DB_PATH="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "${DB_PATH}" ]]; then
  echo "Error: --db is required" >&2
  usage
  exit 1
fi

if [[ ! -f "${DB_PATH}" ]]; then
  echo "Error: DB file not found: ${DB_PATH}" >&2
  exit 1
fi

if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "Error: sqlite3 command not found. Please install sqlite3 first." >&2
  exit 1
fi

sqlite3 -header -column "${DB_PATH}" "
SELECT
  id,
  workspace_id,
  file_name,
  file_path,
  object_key,
  created_at AS created_at_raw,
  CASE
    WHEN created_at > 20000000000 THEN datetime(created_at / 1000, 'unixepoch', 'localtime')
    ELSE datetime(created_at, 'unixepoch', 'localtime')
  END AS created_at_local
FROM media_files
ORDER BY created_at DESC;
"

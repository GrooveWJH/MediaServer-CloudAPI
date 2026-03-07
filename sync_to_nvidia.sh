#!/usr/bin/env bash
set -euo pipefail

# Mirror this repository to a remote host using rsync.
# - Respects .gitignore rules
# - Deletes remote files removed locally
# - Excludes local git metadata
# - Preserves remote runtime dependencies (.venv / node_modules / pnpm store)

REMOTE_USER_HOST="${REMOTE_USER_HOST:-nvidia@192.168.10.228}"
SSH_KEY="${SSH_KEY:-${HOME}/.ssh/saved_key/fpg}"
REMOTE_DIR="${REMOTE_DIR:-~/mediaserver-cloudapi}"

DRY_RUN="false"

for arg in "$@"; do
  case "$arg" in
    --dry-run|-n)
      DRY_RUN="true"
      ;;
    --help|-h)
      cat <<'USAGE'
Usage: ./sync_to_target.sh [--dry-run]

Options:
  -n, --dry-run   Show changes without applying
  -h, --help      Show this help

Environment overrides:
  REMOTE_USER_HOST   Default: nvidia@192.168.10.228
  SSH_KEY            Default: $HOME/.ssh/saved_key/fpg
  REMOTE_DIR         Default: ~/mediaserver-cloudapi
USAGE
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Resolve repo root robustly:
# - prefer git toplevel
# - fallback to script dir (if script is placed in repo root)
# - fallback to parent dir (if script is placed in scripts/)
if REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null)"; then
  :
elif [[ -f "${SCRIPT_DIR}/.gitignore" ]]; then
  REPO_ROOT="${SCRIPT_DIR}"
elif [[ -f "${SCRIPT_DIR}/../.gitignore" ]]; then
  REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
else
  echo "Error: failed to locate git repo root from: ${SCRIPT_DIR}" >&2
  exit 1
fi

if [[ ! -f "${REPO_ROOT}/.gitignore" ]]; then
  echo "Error: .gitignore not found in repo root: ${REPO_ROOT}" >&2
  exit 1
fi

if [[ ! -f "${SSH_KEY}" ]]; then
  echo "Error: SSH key not found: ${SSH_KEY}" >&2
  exit 1
fi

RSYNC_FLAGS=(
  -az
  --delete
  --force
  --itemize-changes
  --human-readable
  # Keep --delete for tracked files.
  # Do not use --delete-excluded to avoid deleting excluded runtime deps.
  --exclude='.venv/'
  --exclude='**/.venv/'
  --exclude='node_modules/'
  --exclude='**/node_modules/'
  --exclude='.pnpm-store/'
  --exclude='**/.pnpm-store/'
  --exclude='.pnpm/'
  --exclude='**/.pnpm/'
  --filter=':- .gitignore'
  --exclude='.git/'
)

if [[ "${DRY_RUN}" == "true" ]]; then
  RSYNC_FLAGS+=(--dry-run)
fi

SSH_CMD=(ssh -i "${SSH_KEY}" -o StrictHostKeyChecking=accept-new)

echo "[sync] repo: ${REPO_ROOT}"
echo "[sync] remote: ${REMOTE_USER_HOST}:${REMOTE_DIR}"
echo "[sync] mode: $([[ "${DRY_RUN}" == "true" ]] && echo 'dry-run' || echo 'apply')"

"${SSH_CMD[@]}" "${REMOTE_USER_HOST}" "mkdir -p ${REMOTE_DIR}"

cd "${REPO_ROOT}"
rsync "${RSYNC_FLAGS[@]}" -e "${SSH_CMD[*]}" ./ "${REMOTE_USER_HOST}:${REMOTE_DIR}/"

echo "[sync] done"

#!/usr/bin/env bash
set -u

RED="\033[31m"
GREEN="\033[32m"
YELLOW="\033[33m"
BLUE="\033[34m"
RESET="\033[0m"

PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0

say() { printf "%b\n" "$1"; }
ok() { PASS_COUNT=$((PASS_COUNT + 1)); say "${GREEN}OK${RESET} $1"; }
warn() { WARN_COUNT=$((WARN_COUNT + 1)); say "${YELLOW}WARN${RESET} $1"; }
fail() { FAIL_COUNT=$((FAIL_COUNT + 1)); say "${RED}FAIL${RESET} $1"; }
info() { say "${BLUE}INFO${RESET} $1"; }

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/deploy/media-server.env"

if [[ -f "${ENV_FILE}" ]]; then
  info "Loading env: ${ENV_FILE}"
  # shellcheck disable=SC1090
  set -a
  source "${ENV_FILE}"
  set +a
else
  warn "Env file not found: ${ENV_FILE}, using defaults"
fi

MEDIA_SERVER_PORT="${MEDIA_SERVER_PORT:-8090}"
WEB_PORT="${WEB_PORT:-8088}"
STORAGE_ENDPOINT="${STORAGE_ENDPOINT:-http://127.0.0.1:9000}"
MINIO_HEALTH_URL="${STORAGE_ENDPOINT%/}/minio/health/ready"
MEDIA_HEALTH_URL="http://127.0.0.1:${MEDIA_SERVER_PORT}/health"
WEB_URL="http://127.0.0.1:${WEB_PORT}/"

require_cmd() {
  local cmd="$1"
  if command -v "${cmd}" >/dev/null 2>&1; then
    ok "Command exists: ${cmd}"
  else
    fail "Command missing: ${cmd}"
  fi
}

http_code() {
  local url="$1"
  curl -sS -o /dev/null -m 5 -w "%{http_code}" "${url}" 2>/dev/null || true
}

check_python_version() {
  if ! command -v python3 >/dev/null 2>&1; then
    fail "python3 not found, cannot verify version"
    return
  fi

  local version
  version="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")' 2>/dev/null || true)"
  if [[ -z "${version}" ]]; then
    fail "Unable to read python3 version"
    return
  fi

  local ver_major ver_minor
  ver_major="$(printf "%s" "${version}" | cut -d. -f1)"
  ver_minor="$(printf "%s" "${version}" | cut -d. -f2)"

  if (( ver_major > 3 || (ver_major == 3 && ver_minor >= 12) )); then
    ok "Python version is ${version} (>= 3.12)"
  elif (( ver_major == 3 && ver_minor >= 8 )); then
    warn "Python version is ${version} (README says >=3.8, pyproject requires >=3.12)"
  else
    fail "Python version is ${version}, too old"
  fi
}

check_python_modules() {
  if ! command -v python3 >/dev/null 2>&1; then
    fail "python3 not found, cannot verify Python packages"
    return
  fi

  local missing
  missing="$(
    python3 - <<'PY'
import importlib.util
mods = ["typer", "flask"]
missing = [m for m in mods if importlib.util.find_spec(m) is None]
print(",".join(missing))
PY
  )"
  if [[ -z "${missing}" ]]; then
    ok "Python packages available: typer, flask"
  else
    fail "Missing Python packages: ${missing}"
  fi
}

check_docker_runtime() {
  if ! command -v docker >/dev/null 2>&1; then
    fail "docker not found, cannot verify runtime"
    return
  fi

  if docker info >/dev/null 2>&1; then
    ok "Docker daemon is reachable"
  else
    fail "Docker daemon unreachable (is service running and current user in docker group?)"
  fi

  if docker compose version >/dev/null 2>&1; then
    ok "Docker Compose plugin is available"
  else
    fail "Docker Compose plugin unavailable"
  fi
}

check_minio_container_hint() {
  if ! command -v docker >/dev/null 2>&1; then
    return
  fi
  local names
  names="$(docker ps --format '{{.Names}}' 2>/dev/null || true)"
  if printf "%s\n" "${names}" | grep -Eq '^(mediaserver-minio|fc-minio)$'; then
    ok "Detected MinIO container (mediaserver-minio/fc-minio)"
  else
    warn "MinIO container name not detected in running containers"
  fi
}

check_minio_health() {
  local code
  code="$(http_code "${MINIO_HEALTH_URL}")"
  if [[ "${code}" == "200" ]]; then
    ok "MinIO health OK: ${MINIO_HEALTH_URL}"
  else
    fail "MinIO health check failed: ${MINIO_HEALTH_URL} (HTTP ${code:-N/A})"
  fi
}

check_media_health() {
  local body code
  body="$(curl -sS -m 5 "${MEDIA_HEALTH_URL}" 2>/dev/null || true)"
  code="$(http_code "${MEDIA_HEALTH_URL}")"

  if [[ "${code}" != "200" ]]; then
    fail "Media service health failed: ${MEDIA_HEALTH_URL} (HTTP ${code:-N/A})"
    return
  fi

  if python3 - "$body" <<'PY'
import json
import sys
raw = sys.argv[1]
try:
    data = json.loads(raw)
except Exception:
    raise SystemExit(1)
if data.get("code") != 0:
    raise SystemExit(2)
if data.get("message") != "ok":
    raise SystemExit(3)
if not isinstance(data.get("data"), dict):
    raise SystemExit(4)
print("ok")
PY
  then
    ok "Media health response is valid JSON: ${MEDIA_HEALTH_URL}"
  else
    fail "Media health response format invalid: ${MEDIA_HEALTH_URL} body=${body}"
  fi
}

check_web_endpoint() {
  local code
  code="$(http_code "${WEB_URL}")"
  if [[ "${code}" == "200" ]]; then
    ok "Web endpoint reachable: ${WEB_URL}"
  elif [[ "${code}" == "000" || -z "${code}" ]]; then
    warn "Web endpoint unreachable: ${WEB_URL} (web module may be intentionally disabled)"
  else
    warn "Web endpoint returned HTTP ${code}: ${WEB_URL}"
  fi
}

check_systemd_units() {
  if ! command -v systemctl >/dev/null 2>&1; then
    warn "systemctl not found, skip systemd checks"
    return
  fi

  local unit state
  for unit in media-server.service media-web.service; do
    state="$(systemctl is-active "${unit}" 2>/dev/null || true)"
    if [[ "${state}" == "active" ]]; then
      ok "systemd unit active: ${unit}"
      continue
    fi
    if systemctl list-unit-files "${unit}" --no-legend 2>/dev/null | grep -q "^${unit}"; then
      warn "systemd unit installed but not active: ${unit} (state=${state:-unknown})"
    else
      warn "systemd unit not installed: ${unit}"
    fi
  done
}

info "Checking required commands"
require_cmd python3
require_cmd curl
require_cmd docker

info "Checking Python runtime"
check_python_version
check_python_modules

info "Checking Docker runtime"
check_docker_runtime
check_minio_container_hint

info "Checking service responses"
check_minio_health
check_media_health
check_web_endpoint

info "Checking systemd deployment status"
check_systemd_units

say ""
info "Summary: pass=${PASS_COUNT}, warn=${WARN_COUNT}, fail=${FAIL_COUNT}"
if (( FAIL_COUNT > 0 )); then
  exit 1
fi
exit 0

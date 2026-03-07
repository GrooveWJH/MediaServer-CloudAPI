#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="${ROOT_DIR}/deploy"
RUN_DIR="${ROOT_DIR}/tmp/run"
LOG_DIR="${ROOT_DIR}/tmp/logs"
ENV_FILE="${DEPLOY_DIR}/media-server.env"
COMPOSE_FILE="${DEPLOY_DIR}/docker-compose.yml"

MEDIA_PID_FILE="${RUN_DIR}/media-server.pid"
WEB_PID_FILE="${RUN_DIR}/media-web.pid"

RED="\033[31m"
GREEN="\033[32m"
YELLOW="\033[33m"
BLUE="\033[34m"
RESET="\033[0m"

say() { printf "%b\n" "$1"; }
ok() { say "${GREEN}OK${RESET} $1"; }
warn() { say "${YELLOW}WARN${RESET} $1"; }
info() { say "${BLUE}INFO${RESET} $1"; }
err() { say "${RED}ERR${RESET} $1"; }

usage() {
  cat <<'USAGE'
Usage: ./deploy/one_click.sh <command>

Commands:
  start      Start MinIO + media-server + media-web
  stop       Stop media-server + media-web + MinIO
  restart    Restart all components
  status     Show component status
  logs       Tail media-server and media-web logs
  check      Run deployment checks
USAGE
}

require_cmd() {
  local c="$1"
  command -v "${c}" >/dev/null 2>&1 || { err "Command not found: ${c}"; exit 1; }
}

load_env() {
  if [[ ! -f "${ENV_FILE}" ]]; then
    err "Env file missing: ${ENV_FILE}"
    exit 1
  fi
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
}

ensure_dirs() {
  mkdir -p "${RUN_DIR}" "${LOG_DIR}" "${DEPLOY_DIR}/minio-data"
}

is_pid_running() {
  local pid="$1"
  [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null
}

start_minio() {
  info "Starting MinIO via docker compose"
  (cd "${DEPLOY_DIR}" && docker compose -f "${COMPOSE_FILE}" up -d)
  ok "MinIO compose started"
}

wait_minio() {
  local endpoint="${STORAGE_ENDPOINT:-http://127.0.0.1:9000}"
  local health_url="${endpoint%/}/minio/health/ready"
  local i
  for i in $(seq 1 30); do
    if curl -sSf "${health_url}" >/dev/null 2>&1; then
      ok "MinIO ready: ${health_url}"
      return 0
    fi
    sleep 1
  done
  warn "MinIO not ready after timeout: ${health_url}"
}

start_media_server() {
  if [[ -f "${MEDIA_PID_FILE}" ]] && is_pid_running "$(cat "${MEDIA_PID_FILE}")"; then
    ok "media-server already running (pid=$(cat "${MEDIA_PID_FILE}"))"
    return
  fi

  info "Starting media-server"
  (
    cd "${ROOT_DIR}"
    nohup python3 src/media_server/server.py \
      --host "${MEDIA_SERVER_HOST:-0.0.0.0}" \
      --port "${MEDIA_SERVER_PORT:-8090}" \
      --token "${MEDIA_SERVER_TOKEN:-demo-token}" \
      --storage-endpoint "${STORAGE_ENDPOINT:-http://127.0.0.1:9000}" \
      --storage-bucket "${STORAGE_BUCKET:-media}" \
      --storage-region "${STORAGE_REGION:-us-east-1}" \
      --storage-access-key "${STORAGE_ACCESS_KEY:-minioadmin}" \
      --storage-secret-key "${STORAGE_SECRET_KEY:-minioadmin}" \
      --storage-sts-role-arn "${STORAGE_STS_ROLE_ARN:-arn:aws:iam::minio:role/dji-pilot}" \
      --storage-sts-policy "${STORAGE_STS_POLICY:-}" \
      --storage-sts-duration "${STORAGE_STS_DURATION:-3600}" \
      --db-path "${DB_PATH:-data/media.db}" \
      --log-level "${LOG_LEVEL:-info}" \
      > "${LOG_DIR}/media-server.log" 2>&1 &
    echo $! > "${MEDIA_PID_FILE}"
  )
  ok "media-server started (pid=$(cat "${MEDIA_PID_FILE}"))"
}

start_media_web() {
  if [[ -f "${WEB_PID_FILE}" ]] && is_pid_running "$(cat "${WEB_PID_FILE}")"; then
    ok "media-web already running (pid=$(cat "${WEB_PID_FILE}"))"
    return
  fi

  info "Starting media-web"
  (
    cd "${ROOT_DIR}"
    nohup python3 web/app.py \
      --host 0.0.0.0 \
      --port "${WEB_PORT:-8088}" \
      --db-path "${DB_PATH:-data/media.db}" \
      --storage-endpoint "${STORAGE_ENDPOINT:-http://127.0.0.1:9000}" \
      --storage-bucket "${STORAGE_BUCKET:-media}" \
      --storage-region "${STORAGE_REGION:-us-east-1}" \
      --storage-access-key "${STORAGE_ACCESS_KEY:-minioadmin}" \
      --storage-secret-key "${STORAGE_SECRET_KEY:-minioadmin}" \
      > "${LOG_DIR}/media-web.log" 2>&1 &
    echo $! > "${WEB_PID_FILE}"
  )
  ok "media-web started (pid=$(cat "${WEB_PID_FILE}"))"
}

stop_by_pid_file() {
  local name="$1"
  local file="$2"
  if [[ ! -f "${file}" ]]; then
    warn "${name} pid file not found"
    return
  fi
  local pid
  pid="$(cat "${file}")"
  if is_pid_running "${pid}"; then
    kill "${pid}" 2>/dev/null || true
    sleep 1
    if is_pid_running "${pid}"; then
      kill -9 "${pid}" 2>/dev/null || true
    fi
    ok "${name} stopped"
  else
    warn "${name} not running"
  fi
  rm -f "${file}"
}

status_component() {
  local name="$1"
  local pid_file="$2"
  if [[ -f "${pid_file}" ]] && is_pid_running "$(cat "${pid_file}")"; then
    ok "${name}: running (pid=$(cat "${pid_file}"))"
  else
    warn "${name}: stopped"
  fi
}

status_ports() {
  local mport="${MEDIA_SERVER_PORT:-8090}"
  local wport="${WEB_PORT:-8088}"
  local sport
  sport="$(echo "${STORAGE_ENDPOINT:-http://127.0.0.1:9000}" | sed -E 's#^https?://[^:]+:([0-9]+).*$#\1#')"

  curl -sS -o /dev/null -m 3 "http://127.0.0.1:${mport}/health" && ok "media health reachable :${mport}" || warn "media health not reachable :${mport}"
  curl -sS -o /dev/null -m 3 "http://127.0.0.1:${wport}/" && ok "web reachable :${wport}" || warn "web not reachable :${wport}"
  curl -sS -o /dev/null -m 3 "http://127.0.0.1:${sport}/minio/health/ready" && ok "minio health reachable :${sport}" || warn "minio health not reachable :${sport}"
}

cmd_start() {
  require_cmd python3
  require_cmd docker
  require_cmd curl
  load_env
  ensure_dirs
  start_minio
  wait_minio
  start_media_server
  start_media_web
  sleep 1
  status_component "media-server" "${MEDIA_PID_FILE}"
  status_component "media-web" "${WEB_PID_FILE}"
  status_ports
  info "Logs: ${LOG_DIR}/media-server.log , ${LOG_DIR}/media-web.log"
}

cmd_stop() {
  stop_by_pid_file "media-web" "${WEB_PID_FILE}"
  stop_by_pid_file "media-server" "${MEDIA_PID_FILE}"
  if [[ -f "${COMPOSE_FILE}" ]]; then
    info "Stopping MinIO compose"
    (cd "${DEPLOY_DIR}" && docker compose -f "${COMPOSE_FILE}" down)
    ok "MinIO compose stopped"
  fi
}

cmd_status() {
  load_env
  status_component "media-server" "${MEDIA_PID_FILE}"
  status_component "media-web" "${WEB_PID_FILE}"
  status_ports
}

cmd_logs() {
  ensure_dirs
  touch "${LOG_DIR}/media-server.log" "${LOG_DIR}/media-web.log"
  tail -n 100 -f "${LOG_DIR}/media-server.log" "${LOG_DIR}/media-web.log"
}

cmd_check() {
  "${DEPLOY_DIR}/check_deployment.sh"
}

main() {
  local cmd="${1:-}"
  case "${cmd}" in
    start) cmd_start ;;
    stop) cmd_stop ;;
    restart) cmd_stop; cmd_start ;;
    status) cmd_status ;;
    logs) cmd_logs ;;
    check) cmd_check ;;
    -h|--help|"") usage ;;
    *) err "Unknown command: ${cmd}"; usage; exit 2 ;;
  esac
}

main "$@"

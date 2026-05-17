#!/usr/bin/env bash
set -euo pipefail

RED="\033[31m"
GREEN="\033[32m"
YELLOW="\033[33m"
BLUE="\033[34m"
GRAY="\033[90m"
RESET="\033[0m"

say() { printf "%b\n" "$1"; }
ok() { say "${GREEN}OK${RESET} $1"; }
warn() { say "${YELLOW}WARN${RESET} $1"; }
err() { say "${RED}ERR${RESET} $1"; }
info() { say "${BLUE}INFO${RESET} $1"; }

ENABLE_WEB="false"

require_sudo() {
  if ! sudo -v; then
    err "sudo privileges required"
    exit 1
  fi
}

get_user() {
  if [[ -n "${SUDO_USER-}" && "${SUDO_USER}" != "root" ]]; then
    echo "${SUDO_USER}"
  else
    echo "${USER}"
  fi
}

get_user_home() {
  local user_name="$1"
  local home_dir
  home_dir="$(getent passwd "${user_name}" 2>/dev/null | cut -d: -f6)"
  if [[ -n "${home_dir}" ]]; then
    echo "${home_dir}"
  else
    echo "/home/${user_name}"
  fi
}

confirm() {
  local prompt="$1"
  read -r -p "${prompt} [y/N] " ans
  [[ "${ans}" == "y" || "${ans}" == "Y" ]]
}

ensure_docker_enabled() {
  if command -v systemctl >/dev/null 2>&1; then
    if ! systemctl is-enabled docker >/dev/null 2>&1; then
      sudo systemctl enable --now docker >/dev/null 2>&1 || true
    fi
  fi
}

require_cmd_or_exit() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    err "required command not found: ${cmd}"
    exit 1
  fi
}

usage() {
  cat <<'USAGE'
Usage:
  ./deploy/setup.sh [--enable-web]

Options:
  --enable-web  Install and start media-web.service on WEB_PORT
  -h, --help    Show this help
USAGE
}

ensure_uv_installed() {
  local user_name="$1"
  local user_home="$2"
  local user_path="${user_home}/.local/bin:${PATH}"

  if sudo -u "${user_name}" -H env PATH="${user_path}" bash -lc 'command -v uv >/dev/null 2>&1'; then
    ok "uv already installed for ${user_name}"
    return
  fi

  info "Installing uv for ${user_name}"
  sudo -u "${user_name}" -H bash -lc 'curl -LsSf https://astral.sh/uv/install.sh | sh'
  if ! sudo -u "${user_name}" -H env PATH="${user_path}" bash -lc 'command -v uv >/dev/null 2>&1'; then
    err "uv install failed for ${user_name}"
    exit 1
  fi
  ok "Installed uv for ${user_name}"
}

repair_or_reset_venv() {
  local target_root="$1"
  local user_name="$2"
  local venv_root="${target_root}/.venv"
  local venv_python3="${venv_root}/bin/python3"

  if [[ ! -e "${venv_root}" ]]; then
    return
  fi

  info "Checking existing virtual environment at ${venv_root}"
  sudo chown -R "${user_name}:${user_name}" "${target_root}/.venv" || true

  if sudo -u "${user_name}" -H env VENV_ROOT="${venv_root}" VENV_PYTHON3="${venv_python3}" bash -lc '
    [[ -d "${VENV_ROOT}" ]] || exit 1
    if [[ -e "${VENV_PYTHON3}" ]]; then
      readlink -f "${VENV_PYTHON3}" >/dev/null
    else
      find "${VENV_ROOT}" -maxdepth 2 -mindepth 1 >/dev/null
    fi
  '; then
    return
  fi

  warn "stale virtual environment is not accessible; recreating ${venv_root}"
  sudo rm -rf "${target_root}/.venv"
}

prepare_python_runtime() {
  local target_root="$1"
  local user_name="$2"
  local user_home="$3"
  local user_path="${user_home}/.local/bin:${PATH}"
  local venv_python="${target_root}/.venv/bin/python"

  if ! command -v python3 >/dev/null 2>&1; then
    err "required command not found: python3"
    exit 1
  fi
  require_cmd_or_exit curl
  ensure_uv_installed "${user_name}" "${user_home}"
  repair_or_reset_venv "${target_root}" "${user_name}"

  info "Syncing Python dependencies with uv"
  sudo -u "${user_name}" -H env PATH="${user_path}" UV_PROJECT_ENVIRONMENT="${target_root}/.venv" \
    bash -lc "cd '${target_root}' && uv sync --frozen"

  if [[ ! -x "${venv_python}" ]]; then
    err "virtual environment python not found: ${venv_python}"
    exit 1
  fi

  if ! sudo -u "${user_name}" -H "${venv_python}" -c 'import flask, typer'; then
    err "project virtual environment missing flask/typer after uv sync"
    exit 1
  fi

  ok "Project virtual environment ready at ${venv_python}"
}

wait_for_minio() {
  local endpoint="$1"
  local retries=30
  local wait_sec=2
  for _ in $(seq 1 "${retries}"); do
    if curl -sSf "${endpoint}/minio/health/ready" >/dev/null 2>&1; then
      return 0
    fi
    sleep "${wait_sec}"
  done
  return 1
}

mc_container_prefix() {
  local endpoint="$1"
  local mc_config_dir="$2"
  local -a args=(sudo docker run --rm -v "${mc_config_dir}:/root/.mc")
  case "${endpoint}" in
    http://127.0.0.1:*|https://127.0.0.1:*|http://localhost:*|https://localhost:*)
      args+=(--network host)
      ;;
  esac
  printf '%s\n' "${args[@]}"
}

ensure_bucket() {
  local endpoint="$1"
  local access_key="$2"
  local secret_key="$3"
  local bucket="$4"
  local mc_config_dir="$5"
  local retries=10
  local wait_sec=2
  local -a mc_cmd=()

  info "Ensuring bucket exists: ${bucket}"
  if ! docker image inspect minio/mc:latest >/dev/null 2>&1; then
    info "Pulling minio/mc image"
    sudo docker pull minio/mc:latest
  fi

  sudo mkdir -p "${mc_config_dir}"
  mapfile -t mc_cmd < <(mc_container_prefix "${endpoint}" "${mc_config_dir}")
  for _ in $(seq 1 "${retries}"); do
    if "${mc_cmd[@]}" minio/mc \
      alias set local "${endpoint}" "${access_key}" "${secret_key}" >/dev/null 2>&1 \
      && "${mc_cmd[@]}" minio/mc \
      mb --ignore-existing "local/${bucket}" >/dev/null 2>&1; then
      return 0
    fi
    sleep "${wait_sec}"
  done
  return 1
}

check_port_available() {
  local port="$1"
  if command -v ss >/dev/null 2>&1 && ss -lnt "( sport = :${port} )" 2>/dev/null | grep -q LISTEN; then
    err "port ${port} is already in use"
    exit 1
  fi
  if command -v lsof >/dev/null 2>&1 && lsof -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1; then
    err "port ${port} is already in use"
    exit 1
  fi
}

verify_minio_access() {
  local endpoint="$1"
  local access_key="$2"
  local secret_key="$3"
  local bucket="$4"
  local mc_config_dir="$5"
  local -a mc_cmd=()

  info "Verifying MinIO IAM and bucket access"
  mapfile -t mc_cmd < <(mc_container_prefix "${endpoint}" "${mc_config_dir}")
  if ! "${mc_cmd[@]}" minio/mc \
    alias set local "${endpoint}" "${access_key}" "${secret_key}" >/dev/null 2>&1; then
    err "failed to configure MinIO client alias"
    exit 1
  fi

  if ! "${mc_cmd[@]}" minio/mc \
    admin info local >/dev/null 2>&1; then
    err "MinIO admin API is not healthy enough for IAM access"
    exit 1
  fi

  if ! "${mc_cmd[@]}" minio/mc \
    ls "local/${bucket}" >/dev/null 2>&1; then
    err "MinIO bucket access failed for ${bucket}"
    exit 1
  fi

  ok "MinIO IAM/API access OK"
  ok "MinIO bucket access OK"
}

print_summary() {
  local -n actions_ref=$1
  say ""
  info "Summary of actions:"
  for action in "${actions_ref[@]}"; do
    say "  - ${action}"
  done
}

remove_systemd_units() {
  info "Stopping services"
  if command -v systemctl >/dev/null 2>&1; then
    sudo systemctl disable --now media-web.service media-server.service >/dev/null 2>&1 || true
  fi
  sudo rm -f /etc/systemd/system/media-web.service /etc/systemd/system/media-server.service
  if command -v systemctl >/dev/null 2>&1; then
    sudo systemctl daemon-reload
  fi
}

cleanup_all() {
  local target_root="/opt/mediaserver/MediaServer-CloudAPI"
  local data_root="/opt/mediaserver/data"
  local actions=()

  remove_systemd_units
  actions+=("disabled systemd services")

  if [[ -d "${target_root}/deploy" ]]; then
    info "Stopping docker compose"
    sudo docker compose -f "${target_root}/deploy/docker-compose.yml" down >/dev/null 2>&1 || true
    actions+=("docker compose down")
  fi

  if confirm "Remove MinIO data at ${target_root}/deploy/minio-data?"; then
    sudo rm -rf "${target_root}/deploy/minio-data"
    actions+=("removed MinIO data")
  else
    actions+=("kept MinIO data")
  fi

  if confirm "Remove SQLite database at ${data_root}?"; then
    sudo rm -rf "${data_root}"
    actions+=("removed DB data")
  else
    actions+=("kept DB data")
  fi

  if confirm "Remove application files at ${target_root}?"; then
    sudo rm -rf "${target_root}"
    actions+=("removed application files")
  else
    actions+=("kept application files")
  fi

  print_summary actions
}

install_or_update() {
  local repo_root
  repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  local target_root="/opt/mediaserver/MediaServer-CloudAPI"
  local data_root="/opt/mediaserver/data"
  local user_name
  user_name="$(get_user)"
  local user_home
  user_home="$(get_user_home "${user_name}")"
  local storage_bucket="media"
  local storage_region="us-east-1"
  local storage_access_key="minioadmin"
  local storage_secret_key="minioadmin"
  local storage_endpoint_internal="http://127.0.0.1:9000"
  local storage_public_endpoint=""
  local storage_public_port="9000"
  local trust_forwarded_headers="false"
  local storage_sts_role_arn="arn:aws:iam::minio:role/dji-pilot"
  local storage_sts_policy=""
  local storage_sts_duration="3600"
  local log_level="warning"
  local web_enabled="${ENABLE_WEB}"
  local web_port="8088"
  local actions=()

  info "Preparing directories"
  sudo mkdir -p /opt/mediaserver
  sudo mkdir -p "${data_root}"
  sudo chown -R "${user_name}:${user_name}" /opt/mediaserver
  actions+=("created /opt/mediaserver and ${data_root}")

  remove_systemd_units
  actions+=("reinstalled systemd units")

  if [[ -f "${target_root}/deploy/docker-compose.yml" ]]; then
    info "Stopping docker compose before syncing repository"
    sudo docker compose -f "${target_root}/deploy/docker-compose.yml" down >/dev/null 2>&1 || true
    actions+=("docker compose down before sync")
  fi

  info "Syncing repository to ${target_root}"
  sudo rsync -a --delete \
    --exclude '.venv/' \
    --exclude 'deploy/minio-data/' \
    --exclude 'deploy/.mc/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    "${repo_root}/" "${target_root}/"
  sudo chown -R "${user_name}:${user_name}" "${target_root}"
  actions+=("synced repository to ${target_root}")

  prepare_python_runtime "${target_root}" "${user_name}" "${user_home}"
  actions+=("synced Python dependencies with uv")

  info "Writing environment file"
  sudo tee "${target_root}/deploy/media-server.env" >/dev/null <<EOF
MEDIA_SERVER_HOST=0.0.0.0
MEDIA_SERVER_PORT=8090
MEDIA_SERVER_TOKEN=demo-token

STORAGE_ENDPOINT=${storage_endpoint_internal}
STORAGE_PUBLIC_ENDPOINT=${storage_public_endpoint}
STORAGE_PUBLIC_PORT=${storage_public_port}
TRUST_FORWARDED_HEADERS=${trust_forwarded_headers}
STORAGE_BUCKET=${storage_bucket}
STORAGE_REGION=${storage_region}
STORAGE_ACCESS_KEY=${storage_access_key}
STORAGE_SECRET_KEY=${storage_secret_key}
STORAGE_STS_ROLE_ARN=${storage_sts_role_arn}
STORAGE_STS_POLICY=${storage_sts_policy}
STORAGE_STS_DURATION=${storage_sts_duration}

DB_PATH=/opt/mediaserver/data/media.db
LOG_LEVEL=${log_level}

WEB_ENABLED=${web_enabled}
WEB_PORT=${web_port}
EOF
  actions+=("wrote ${target_root}/deploy/media-server.env")
  ok "STORAGE_ENDPOINT set to ${storage_endpoint_internal}"
  info "STS public endpoint mode: auto by request headers (public port ${storage_public_port})"

  info "Writing MinIO compose env"
  sudo tee "${target_root}/deploy/.env" >/dev/null <<EOF
MINIO_ROOT_USER=${storage_access_key}
MINIO_ROOT_PASSWORD=${storage_secret_key}
MINIO_BUCKET=${storage_bucket}
EOF
  actions+=("wrote ${target_root}/deploy/.env")

  info "Installing systemd units"
  sed -e "s|^WorkingDirectory=.*|WorkingDirectory=${target_root}|" \
      -e "s|^EnvironmentFile=.*|EnvironmentFile=${target_root}/deploy/media-server.env|" \
      -e "s|^ExecStart=.*|ExecStart=${target_root}/.venv/bin/python ${target_root}/src/media_server/server.py \\\\|" \
      -e "s|^User=.*|User=${user_name}|" \
      -e "s|^Group=.*|Group=${user_name}|" \
      "${target_root}/deploy/media-server.service" > /tmp/media-server.service
  sed -e "s|^WorkingDirectory=.*|WorkingDirectory=${target_root}|" \
      -e "s|^EnvironmentFile=.*|EnvironmentFile=${target_root}/deploy/media-server.env|" \
      -e "s|^ExecStart=.*|ExecStart=${target_root}/.venv/bin/python ${target_root}/web/app.py \\\\|" \
      -e "s|^User=.*|User=${user_name}|" \
      -e "s|^Group=.*|Group=${user_name}|" \
      "${target_root}/deploy/media-web.service" > /tmp/media-web.service
  sudo mv /tmp/media-server.service /etc/systemd/system/media-server.service
  sudo mv /tmp/media-web.service /etc/systemd/system/media-web.service
  sudo systemctl daemon-reload
  actions+=("installed systemd units")

  info "Preparing MinIO data directory"
  sudo mkdir -p "${target_root}/deploy/minio-data"
  sudo chown -R 1000:1000 "${target_root}/deploy/minio-data" || true
  actions+=("prepared MinIO data directory")

  ensure_docker_enabled
  actions+=("ensured docker service enabled")

  info "Starting MinIO with docker compose"
  sudo docker compose -f "${target_root}/deploy/docker-compose.yml" up -d
  actions+=("started MinIO via docker compose")

  info "Waiting for MinIO to be ready"
  # Load env values to use the same endpoint/credentials for bucket creation.
  set -a
  # shellcheck disable=SC1090
  source "${target_root}/deploy/media-server.env"
  set +a
  if wait_for_minio "${STORAGE_ENDPOINT}"; then
    if ensure_bucket "${STORAGE_ENDPOINT}" "${STORAGE_ACCESS_KEY}" "${STORAGE_SECRET_KEY}" "${STORAGE_BUCKET}" "${target_root}/deploy/.mc"; then
      actions+=("created bucket ${STORAGE_BUCKET} (if missing)")
      verify_minio_access "${STORAGE_ENDPOINT}" "${STORAGE_ACCESS_KEY}" "${STORAGE_SECRET_KEY}" "${STORAGE_BUCKET}" "${target_root}/deploy/.mc"
      actions+=("verified MinIO IAM and bucket access")
    else
      err "Bucket init failed after retries"
      exit 1
    fi
  else
    err "MinIO not ready after startup"
    exit 1
  fi

  info "Enabling services"
  sudo systemctl enable --now media-server.service
  actions+=("enabled media-server service")
  sudo systemctl enable media-web.service >/dev/null 2>&1 || true
  if [[ "${web_enabled}" == "true" ]]; then
    check_port_available "${web_port}"
    sudo systemctl enable --now media-web.service
    actions+=("enabled media-web service")
  else
    sudo systemctl disable --now media-web.service >/dev/null 2>&1 || true
    actions+=("installed but left media-web service disabled by default")
  fi

  print_summary actions
  if [[ "${web_enabled}" == "true" ]]; then
    ok "Done. Media server at :8090, web at :${web_port}, MinIO at :9000/:9001"
  else
    ok "Done. Media server at :8090, web disabled by default, MinIO at :9000/:9001"
  fi
}

main() {
  require_sudo

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --enable-web)
        ENABLE_WEB="true"
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        err "Unknown argument: $1"
        usage
        exit 2
        ;;
    esac
  done

  say ""
  say "Choose action:"
  say "  [1] Install or update deployment"
  say "  [2] Cleanup deployment"
  read -r -p "Enter choice (1/2): " action
  case "${action}" in
    1) install_or_update ;;
    2) cleanup_all ;;
    *) warn "Invalid choice" ;;
  esac
}

main "$@"

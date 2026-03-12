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

ensure_bucket() {
  local endpoint="$1"
  local access_key="$2"
  local secret_key="$3"
  local bucket="$4"
  local mc_config_dir="$5"
  local retries=10
  local wait_sec=2

  info "Ensuring bucket exists: ${bucket}"
  if ! docker image inspect minio/mc:latest >/dev/null 2>&1; then
    info "Pulling minio/mc image"
    sudo docker pull minio/mc:latest
  fi

  sudo mkdir -p "${mc_config_dir}"
  for _ in $(seq 1 "${retries}"); do
    if sudo docker run --rm -v "${mc_config_dir}:/root/.mc" minio/mc \
      alias set local "${endpoint}" "${access_key}" "${secret_key}" >/dev/null 2>&1 \
      && sudo docker run --rm -v "${mc_config_dir}:/root/.mc" minio/mc \
      mb --ignore-existing "local/${bucket}" >/dev/null 2>&1; then
      return 0
    fi
    sleep "${wait_sec}"
  done
  return 1
}

print_summary() {
  local -n actions_ref=$1
  say ""
  info "Summary of actions:"
  for action in "${actions_ref[@]}"; do
    say "  - ${action}"
  done
}

cleanup_all() {
  local target_root="/opt/mediaserver/MediaServer-CloudAPI"
  local data_root="/opt/mediaserver/data"
  local actions=()

  info "Stopping services"
  sudo systemctl disable --now media-web.service media-server.service >/dev/null 2>&1 || true
  sudo rm -f /etc/systemd/system/media-web.service /etc/systemd/system/media-server.service
  sudo systemctl daemon-reload
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
  local log_level="debug"
  local actions=()

  info "Preparing directories"
  sudo mkdir -p /opt/mediaserver
  sudo mkdir -p "${data_root}"
  sudo chown -R "${user_name}:${user_name}" /opt/mediaserver
  actions+=("created /opt/mediaserver and ${data_root}")

  info "Syncing repository to ${target_root}"
  sudo rsync -a --delete "${repo_root}/" "${target_root}/"
  sudo chown -R "${user_name}:${user_name}" "${target_root}"
  actions+=("synced repository to ${target_root}")

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

WEB_PORT=8088
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
      -e "s|^ExecStart=.*|ExecStart=/usr/bin/python3 ${target_root}/src/media_server/server.py \\\\|" \
      -e "s|^User=.*|User=${user_name}|" \
      -e "s|^Group=.*|Group=${user_name}|" \
      "${target_root}/deploy/media-server.service" > /tmp/media-server.service
  sed -e "s|^WorkingDirectory=.*|WorkingDirectory=${target_root}|" \
      -e "s|^EnvironmentFile=.*|EnvironmentFile=${target_root}/deploy/media-server.env|" \
      -e "s|^ExecStart=.*|ExecStart=/usr/bin/python3 ${target_root}/web/app.py \\\\|" \
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
    else
      warn "Bucket init failed after retries; continue (compose minio-init may still create bucket)"
      actions+=("skipped bucket creation (mc alias/mb failed)")
    fi
  else
    warn "MinIO not ready; skipped bucket creation"
    actions+=("skipped bucket creation (MinIO not ready)")
  fi

  info "Enabling services"
  sudo systemctl enable --now media-server.service
  sudo systemctl enable --now media-web.service
  actions+=("enabled media-server and media-web services")

  print_summary actions
  ok "Done. Media server at :8090, web at :8088, MinIO at :9000/:9001"
}

main() {
  require_sudo

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

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

detect_ips() {
  if command -v hostname >/dev/null 2>&1; then
    hostname -I 2>/dev/null | tr ' ' '\n' | rg -v '^$' || true
    return
  fi
  if command -v ip >/dev/null 2>&1; then
    ip -4 addr show | rg -o "inet ([0-9.]+)" -r '$1' | rg -v '^127\.' || true
  fi
}

choose_ip() {
  local ips
  mapfile -t ips < <(detect_ips)
  if [[ ${#ips[@]} -eq 0 ]]; then
    warn "No LAN IP detected"
  else
    info "Detected IPs:"
    for i in "${!ips[@]}"; do
      say "  [$((i+1))] ${ips[$i]}"
    done
  fi

  while true; do
    say ""
    say "Choose storage endpoint IP:"
    say "  [L] Use detected LAN IP"
    say "  [C] Custom IP"
    read -r -p "> " choice
    case "${choice}" in
      L|l)
        if [[ ${#ips[@]} -eq 0 ]]; then
          warn "No LAN IP available, choose custom"
          continue
        fi
        echo "${ips[0]}"
        return
        ;;
      C|c)
        read -r -p "Enter IP address: " custom_ip
        if [[ -n "${custom_ip}" ]]; then
          echo "${custom_ip}"
          return
        fi
        ;;
      *)
        warn "Invalid choice"
        ;;
    esac
  done
}

confirm() {
  local prompt="$1"
  read -r -p "${prompt} [y/N] " ans
  [[ "${ans}" == "y" || "${ans}" == "Y" ]]
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

  local storage_ip
  storage_ip="$(choose_ip)"
  info "Selected IP: ${storage_ip}"

  info "Writing environment file"
  cat > "${target_root}/deploy/media-server.env" <<EOF
MEDIA_SERVER_HOST=0.0.0.0
MEDIA_SERVER_PORT=8090
MEDIA_SERVER_TOKEN=demo-token

STORAGE_ENDPOINT=http://${storage_ip}:9000
STORAGE_BUCKET=media
STORAGE_REGION=us-east-1
STORAGE_ACCESS_KEY=minioadmin
STORAGE_SECRET_KEY=minioadmin
STORAGE_STS_ROLE_ARN=arn:aws:iam::minio:role/dji-pilot
STORAGE_STS_POLICY=
STORAGE_STS_DURATION=3600

DB_PATH=/opt/mediaserver/data/media.db
LOG_LEVEL=info

WEB_PORT=8088
EOF
  actions+=("wrote ${target_root}/deploy/media-server.env")

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

  info "Starting MinIO with docker compose"
  sudo docker compose -f "${target_root}/deploy/docker-compose.yml" up -d
  actions+=("started MinIO via docker compose")

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
  say "  [1] Install/Update deployment"
  say "  [2] Cleanup deployment"
  read -r -p "> " action
  case "${action}" in
    1) install_or_update ;;
    2) cleanup_all ;;
    *) warn "Invalid choice" ;;
  esac
}

main "$@"

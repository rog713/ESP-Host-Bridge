#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
  shift
else
  DRY_RUN="${ESP_HOST_BRIDGE_DRY_RUN:-0}"
fi

if [[ "${EUID}" -ne 0 && "${DRY_RUN}" != "1" ]]; then
  echo "Run as root. Example: curl -fsSL <install-url> | sudo bash" >&2
  exit 1
fi

APP_NAME="ESP Host Bridge"
SERVICE_NAME="esp-host-bridge"
INSTALL_DIR="${ESP_HOST_BRIDGE_INSTALL_DIR:-/opt/esp-host-bridge}"
DATA_DIR="${INSTALL_DIR}/data"
VENV_DIR="${INSTALL_DIR}/.venv"
SRC_DIR="${INSTALL_DIR}/src"
WEBUI_HOST="${ESP_HOST_BRIDGE_HOST:-0.0.0.0}"
WEBUI_PORT="${ESP_HOST_BRIDGE_PORT:-8654}"
ENABLE_SERVICE="${ESP_HOST_BRIDGE_ENABLE_SERVICE:-1}"
WITH_LIBVIRT="${ESP_HOST_BRIDGE_WITH_LIBVIRT:-1}"
SKIP_APT="${ESP_HOST_BRIDGE_SKIP_APT:-0}"
ARCHIVE_URL="${ESP_HOST_BRIDGE_ARCHIVE_URL:-https://github.com/rog713/ESP-Host-Bridge/archive/refs/heads/dev.tar.gz}"
SOURCE_DIR="${ESP_HOST_BRIDGE_SOURCE_DIR:-}"
SYSTEMD_DIR="/etc/systemd/system"
SERVICE_PATH="${SYSTEMD_DIR}/${SERVICE_NAME}.service"
INSTALL_USER="${ESP_HOST_BRIDGE_USER:-${SUDO_USER:-esp-host-bridge}}"
INSTALL_GROUP="${ESP_HOST_BRIDGE_GROUP:-}"
SUPPLEMENTARY_GROUPS=""

log() {
  printf '[%s] %s\n' "${SERVICE_NAME}" "$*"
}

have_command() {
  command -v "$1" >/dev/null 2>&1
}

run() {
  if [[ "${DRY_RUN}" == "1" ]]; then
    printf '[dry-run] %s\n' "$*"
    return 0
  fi
  eval "$@"
}

apt_install() {
  local packages=("$@")
  if [[ "${#packages[@]}" -eq 0 ]]; then
    return 0
  fi
  run "DEBIAN_FRONTEND=noninteractive apt-get install -y ${packages[*]}"
}

have_required_tooling() {
  have_command python3 || return 1
  python3 -c 'import venv' >/dev/null 2>&1 || return 1
  have_command tar || return 1
  have_command systemctl || return 1
  return 0
}

apt_update_with_retry() {
  local attempts="${ESP_HOST_BRIDGE_APT_UPDATE_RETRIES:-3}"
  local delay=3
  local i
  if [[ "${DRY_RUN}" == "1" ]]; then
    run "apt-get update"
    return 0
  fi
  for ((i=1; i<=attempts; i++)); do
    if apt-get update; then
      return 0
    fi
    if (( i < attempts )); then
      log "apt-get update failed (attempt ${i}/${attempts}); retrying in ${delay}s"
      sleep "${delay}"
      delay=$((delay * 2))
    fi
  done
  return 1
}

detect_group() {
  if [[ -n "${INSTALL_GROUP}" ]]; then
    printf '%s\n' "${INSTALL_GROUP}"
    return
  fi
  if id -u "${INSTALL_USER}" >/dev/null 2>&1; then
    id -gn "${INSTALL_USER}"
    return
  fi
  printf '%s\n' "${INSTALL_USER}"
}

ensure_user() {
  if id -u "${INSTALL_USER}" >/dev/null 2>&1; then
    return 0
  fi
  log "creating service user ${INSTALL_USER}"
  run "useradd --system --create-home --home-dir ${INSTALL_DIR} --shell /usr/sbin/nologin ${INSTALL_USER}"
}

ensure_dir() {
  local path="$1"
  run "install -d -m 0755 -o ${INSTALL_USER} -g ${INSTALL_GROUP} ${path}"
}

ensure_group_membership() {
  local group="$1"
  if ! getent group "${group}" >/dev/null 2>&1; then
    return 0
  fi
  if [[ " ${SUPPLEMENTARY_GROUPS} " != *" ${group} "* ]]; then
    SUPPLEMENTARY_GROUPS="${SUPPLEMENTARY_GROUPS} ${group}"
  fi
  run "usermod -aG ${group} ${INSTALL_USER}"
}

render_supplementary_groups() {
  if [[ -z "${SUPPLEMENTARY_GROUPS}" ]]; then
    return 0
  fi
  printf 'SupplementaryGroups=%s\n' "${SUPPLEMENTARY_GROUPS}"
}

prepare_source_tree() {
  if [[ -n "${SOURCE_DIR}" ]]; then
    if [[ ! -f "${SOURCE_DIR}/pyproject.toml" ]]; then
      echo "ESP_HOST_BRIDGE_SOURCE_DIR does not contain pyproject.toml: ${SOURCE_DIR}" >&2
      exit 1
    fi
    printf '%s\n' "${SOURCE_DIR}"
    return 0
  fi

  local tmp_dir archive_path extract_dir discovered
  tmp_dir="$(mktemp -d)"
  archive_path="${tmp_dir}/esp-host-bridge.tar.gz"
  extract_dir="${tmp_dir}/src"
  run "curl -fsSL ${ARCHIVE_URL} -o ${archive_path}"
  run "mkdir -p ${extract_dir}"
  run "tar -xzf ${archive_path} -C ${extract_dir}"
  discovered="$(find "${extract_dir}" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  if [[ -z "${discovered}" || ! -f "${discovered}/pyproject.toml" ]]; then
    echo "Downloaded archive does not contain a Python package with pyproject.toml" >&2
    exit 1
  fi
  printf '%s\n' "${discovered}"
}

write_service() {
  cat <<EOF
[Unit]
Description=${APP_NAME}
After=network-online.target libvirtd.service
Wants=network-online.target

[Service]
Type=simple
User=${INSTALL_USER}
Group=${INSTALL_GROUP}
$(render_supplementary_groups)
WorkingDirectory=${INSTALL_DIR}
Environment=WEBUI_HOST=${WEBUI_HOST}
Environment=WEBUI_PORT=${WEBUI_PORT}
Environment=WEBUI_CONFIG=${DATA_DIR}/config.json
ExecStart=${VENV_DIR}/bin/esp-host-bridge webui
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF
}

if [[ "${SKIP_APT}" != "1" ]]; then
  log "installing system packages"
  if apt_update_with_retry; then
    apt_install ca-certificates curl python3 python3-pip python3-venv
    if [[ "${WITH_LIBVIRT}" == "1" ]]; then
      apt_install libvirt-clients libvirt-daemon-system
    fi
  else
    if have_required_tooling; then
      log "apt-get update failed, but Python tooling is already available; continuing without apt"
      SKIP_APT=1
    else
      echo "apt-get update failed and required tooling is missing." >&2
      echo "Fix your apt sources, or install python3 and python3-venv manually, then rerun with ESP_HOST_BRIDGE_SKIP_APT=1." >&2
      exit 1
    fi
  fi
fi

INSTALL_GROUP="$(detect_group)"
ensure_user
INSTALL_GROUP="$(detect_group)"

log "preparing directories in ${INSTALL_DIR}"
ensure_dir "${INSTALL_DIR}"
ensure_dir "${DATA_DIR}"
ensure_dir "${SRC_DIR}"
run "chown -R ${INSTALL_USER}:${INSTALL_GROUP} ${INSTALL_DIR}"

log "granting serial and libvirt access to ${INSTALL_USER}"
ensure_group_membership dialout
ensure_group_membership libvirt

SOURCE_PATH="$(prepare_source_tree)"

if [[ "${DRY_RUN}" != "1" ]]; then
  find "${SRC_DIR}" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  cp -a "${SOURCE_PATH}/." "${SRC_DIR}/"
else
  printf '[dry-run] find %s -mindepth 1 -maxdepth 1 -exec rm -rf {} + && cp -a %s/. %s/\n' "${SRC_DIR}" "${SOURCE_PATH}" "${SRC_DIR}"
fi

if [[ ! -x "${VENV_DIR}/bin/python3" ]]; then
  log "creating virtual environment"
  run "python3 -m venv ${VENV_DIR}"
fi

log "installing Python package"
run "${VENV_DIR}/bin/python3 -m pip install --upgrade pip setuptools wheel"
run "${VENV_DIR}/bin/python3 -m pip install --upgrade ${SRC_DIR}"

if [[ "${WITH_LIBVIRT}" == "1" && "${DRY_RUN}" != "1" ]] && ! have_command virsh; then
  log "virsh not found; VM polling will stay unavailable until libvirt tools are installed"
fi

log "writing systemd service"
if [[ "${DRY_RUN}" == "1" ]]; then
  printf '[dry-run] write %s\n' "${SERVICE_PATH}"
  write_service
else
  write_service > "${SERVICE_PATH}"
fi

run "systemctl daemon-reload"

if [[ "${ENABLE_SERVICE}" == "1" ]]; then
  if [[ "${DRY_RUN}" == "1" ]]; then
    log "enabling ${SERVICE_NAME}.service and restarting it if already running"
    printf '[dry-run] if systemctl is-active --quiet %s.service; then systemctl enable %s.service && systemctl restart %s.service; else systemctl enable --now %s.service; fi\n' "${SERVICE_NAME}" "${SERVICE_NAME}" "${SERVICE_NAME}" "${SERVICE_NAME}"
  elif systemctl is-active --quiet "${SERVICE_NAME}.service"; then
    log "enabling and restarting ${SERVICE_NAME}.service"
    run "systemctl enable ${SERVICE_NAME}.service"
    run "systemctl restart ${SERVICE_NAME}.service"
  else
    log "enabling and starting ${SERVICE_NAME}.service"
    run "systemctl enable --now ${SERVICE_NAME}.service"
  fi
else
  log "service file installed but not started (ESP_HOST_BRIDGE_ENABLE_SERVICE=0)"
fi

log "install complete"
log "Web UI: http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo 127.0.0.1):${WEBUI_PORT}"
log "Service: systemctl status ${SERVICE_NAME}.service"
log "If you need host power commands, add a narrow sudoers rule for ${INSTALL_USER}."

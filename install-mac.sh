#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
  shift
else
  DRY_RUN="${ESP_HOST_BRIDGE_DRY_RUN:-0}"
fi

APP_NAME="ESP Host Bridge"
SERVICE_NAME="esp-host-bridge"
LAUNCH_AGENT_LABEL="com.rog713.esp-host-bridge"
INSTALL_DIR="${ESP_HOST_BRIDGE_INSTALL_DIR:-$HOME/Applications/esp-host-bridge}"
DATA_DIR="${ESP_HOST_BRIDGE_DATA_DIR:-$HOME/Library/Application Support/ESP Host Bridge}"
VENV_DIR="${INSTALL_DIR}/.venv"
SRC_DIR="${INSTALL_DIR}/src"
LOG_DIR="${INSTALL_DIR}/logs"
PLIST_DIR="${HOME}/Library/LaunchAgents"
PLIST_PATH="${PLIST_DIR}/${LAUNCH_AGENT_LABEL}.plist"
WEBUI_HOST="${ESP_HOST_BRIDGE_HOST:-0.0.0.0}"
WEBUI_PORT="${ESP_HOST_BRIDGE_PORT:-8654}"
ENABLE_LAUNCH_AGENT="${ESP_HOST_BRIDGE_ENABLE_LAUNCH_AGENT:-1}"
INSTALL_HOMEBREW_TOOLS="${ESP_HOST_BRIDGE_INSTALL_BREW_TOOLS:-0}"
ARCHIVE_URL="${ESP_HOST_BRIDGE_ARCHIVE_URL:-https://github.com/rog713/ESP-Host-Bridge/archive/refs/heads/main.tar.gz}"
SOURCE_DIR="${ESP_HOST_BRIDGE_SOURCE_DIR:-}"
CONFIG_PATH="${DATA_DIR}/config.json"
STDOUT_LOG="${LOG_DIR}/webui.log"
STDERR_LOG="${LOG_DIR}/webui.err.log"

log() {
  printf '[%s] %s\n' "${SERVICE_NAME}" "$*"
}

have_command() {
  command -v "$1" >/dev/null 2>&1
}

run_cmd() {
  if [[ "${DRY_RUN}" == "1" ]]; then
    printf '[dry-run]'
    printf ' %q' "$@"
    printf '\n'
    return 0
  fi
  "$@"
}

ensure_dir() {
  run_cmd mkdir -p "$1"
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
  run_cmd curl -fsSL "${ARCHIVE_URL}" -o "${archive_path}"
  run_cmd mkdir -p "${extract_dir}"
  run_cmd tar -xzf "${archive_path}" -C "${extract_dir}"
  discovered="$(find "${extract_dir}" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  if [[ -z "${discovered}" || ! -f "${discovered}/pyproject.toml" ]]; then
    echo "Downloaded archive does not contain a Python package with pyproject.toml" >&2
    exit 1
  fi
  printf '%s\n' "${discovered}"
}

install_homebrew_tools() {
  if [[ "${INSTALL_HOMEBREW_TOOLS}" != "1" ]]; then
    return 0
  fi
  if ! have_command brew; then
    log "Homebrew not found; skipping optional tool install"
    return 0
  fi
  log "installing optional Homebrew tools"
  run_cmd brew install macmon libvirt
}

write_launch_agent() {
  cat <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LAUNCH_AGENT_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${VENV_DIR}/bin/esp-host-bridge-mac</string>
    <string>webui</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>WEBUI_HOST</key>
    <string>${WEBUI_HOST}</string>
    <key>WEBUI_PORT</key>
    <string>${WEBUI_PORT}</string>
    <key>WEBUI_CONFIG</key>
    <string>${CONFIG_PATH}</string>
  </dict>
  <key>WorkingDirectory</key>
  <string>${INSTALL_DIR}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${STDOUT_LOG}</string>
  <key>StandardErrorPath</key>
  <string>${STDERR_LOG}</string>
</dict>
</plist>
PLIST
}

load_launch_agent() {
  local domain="gui/$(id -u)"
  if [[ "${DRY_RUN}" == "1" ]]; then
    log "writing LaunchAgent ${PLIST_PATH}"
    printf '[dry-run] write %s\n' "${PLIST_PATH}"
    write_launch_agent
    printf '[dry-run] launchctl bootout %s %s || true\n' "${domain}" "${PLIST_PATH}"
    printf '[dry-run] launchctl bootstrap %s %s\n' "${domain}" "${PLIST_PATH}"
    printf '[dry-run] launchctl enable %s/%s\n' "${domain}" "${LAUNCH_AGENT_LABEL}"
    printf '[dry-run] launchctl kickstart -k %s/%s\n' "${domain}" "${LAUNCH_AGENT_LABEL}"
    return 0
  fi

  ensure_dir "${PLIST_DIR}"
  write_launch_agent > "${PLIST_PATH}"
  launchctl bootout "${domain}" "${PLIST_PATH}" >/dev/null 2>&1 || true
  launchctl bootstrap "${domain}" "${PLIST_PATH}"
  launchctl enable "${domain}/${LAUNCH_AGENT_LABEL}" >/dev/null 2>&1 || true
  launchctl kickstart -k "${domain}/${LAUNCH_AGENT_LABEL}" >/dev/null 2>&1 || true
}

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "install-mac.sh must be run on macOS" >&2
  exit 1
fi

if [[ "${EUID}" -eq 0 ]]; then
  echo "Do not run as root. Example: curl -fsSL <install-url> | bash" >&2
  exit 1
fi

if ! have_command python3; then
  echo "python3 is required" >&2
  exit 1
fi
if ! python3 -c 'import venv' >/dev/null 2>&1; then
  echo "python3 venv support is required" >&2
  exit 1
fi
if ! have_command curl; then
  echo "curl is required" >&2
  exit 1
fi
if ! have_command tar; then
  echo "tar is required" >&2
  exit 1
fi

log "preparing directories in ${INSTALL_DIR}"
ensure_dir "${INSTALL_DIR}"
ensure_dir "${DATA_DIR}"
ensure_dir "${SRC_DIR}"
ensure_dir "${LOG_DIR}"

install_homebrew_tools

SOURCE_PATH="$(prepare_source_tree)"

if [[ "${DRY_RUN}" != "1" ]]; then
  find "${SRC_DIR}" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  cp -a "${SOURCE_PATH}/." "${SRC_DIR}/"
else
  printf '[dry-run] find %s -mindepth 1 -maxdepth 1 -exec rm -rf {} + && cp -a %s/. %s/\n' "${SRC_DIR}" "${SOURCE_PATH}" "${SRC_DIR}"
fi

if [[ ! -x "${VENV_DIR}/bin/python3" ]]; then
  log "creating virtual environment"
  run_cmd python3 -m venv "${VENV_DIR}"
fi

log "installing Python package"
run_cmd "${VENV_DIR}/bin/python3" -m pip install --upgrade pip setuptools wheel
run_cmd "${VENV_DIR}/bin/python3" -m pip install --upgrade "${SRC_DIR}"

if [[ "${ENABLE_LAUNCH_AGENT}" == "1" ]]; then
  log "installing LaunchAgent"
  load_launch_agent
else
  log "LaunchAgent install skipped (ESP_HOST_BRIDGE_ENABLE_LAUNCH_AGENT=0)"
fi

log "install complete"
log "config path: ${CONFIG_PATH}"
log "start manually with: ${VENV_DIR}/bin/esp-host-bridge-mac webui"
log "open: http://127.0.0.1:${WEBUI_PORT}"

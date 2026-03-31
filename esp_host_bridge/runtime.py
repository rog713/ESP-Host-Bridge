#!/usr/bin/env python3
from __future__ import annotations

import argparse
import atexit
import copy
import difflib
import html
import json
import logging
import os
import platform
import re
import secrets
import shlex
import signal
import socket
import ssl
import subprocess
import sys
import threading
import time
import asyncio
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Dict, Optional, Tuple
from urllib.parse import quote_plus

try:
    import psutil  # type: ignore
except Exception:
    psutil = None

try:
    import serial  # type: ignore
    from serial import SerialException  # type: ignore
    from serial.tools import list_ports  # type: ignore
except Exception:
    serial = None
    SerialException = Exception
    list_ports = None

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

SERIAL_RETRY_SECONDS = 2
SLEEP_SERIAL_PROBE_SECONDS = 3.0
RX_BUFFER_MAX_BYTES = 4096
RX_BUFFER_KEEP_BYTES = 1024
DISK_TEMP_REFRESH_SECONDS = 15.0
DISK_USAGE_REFRESH_SECONDS = 10.0
SLOW_SENSOR_REFRESH_SECONDS = 5.0
INTEGRATION_HEALTH_LOG_MIN_INTERVAL_SECONDS = 30.0
MAX_LOG_LINES = 800
METRIC_HISTORY_POINTS = 90
WEBUI_DEFAULT_PORT = 8654
MDI_FONT_CSS_URL = "https://cdn.jsdelivr.net/npm/@mdi/font@7.4.47/css/materialdesignicons.min.css"
MDI_CODEPOINT_CACHE_PATH = Path(__file__).resolve().parent / ".esp_host_bridge_mdi_codepoints.json"
ESP_BOOT_LINE_RE = re.compile(r"\bESP=BOOT\b(?:,ID=([0-9A-Fa-f]+))?(?:,REASON=([A-Z0-9_]+))?")
HOME_ASSISTANT_SLUG_LABELS = {
    "esphome": "ESPHome",
    "mqtt": "MQTT",
    "zha": "ZHA",
    "zwave_js": "Z-Wave JS",
    "zwavejs": "Z-Wave JS",
    "unifi": "UniFi",
    "homeassistant": "Home Assistant",
    "mobile_app": "Mobile App",
}

_mdi_codepoint_map_lock = threading.Lock()
_mdi_codepoint_map_cache: Optional[Dict[str, int]] = None
_mdi_codepoint_map_cache_err: Optional[str] = None


def _detect_app_version() -> str:
    env_version = str(os.environ.get("ESP_HOST_BRIDGE_VERSION", "") or "").strip()
    if env_version:
        return env_version
    try:
        from importlib import metadata as importlib_metadata

        version = str(importlib_metadata.version("esp-host-bridge") or "").strip()
        if version:
            return version
    except Exception:
        pass
    seen: set[Path] = set()
    current = Path(__file__).resolve()
    for ancestor in (current.parent, *current.parents):
        for candidate in (
            ancestor / "config.yaml",
            ancestor / "pyproject.toml",
            ancestor / "esp-host-bridge.plg",
            ancestor / "dist" / "esp-host-bridge.plg",
        ):
            if candidate in seen or not candidate.is_file():
                continue
            seen.add(candidate)
            try:
                raw = candidate.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for pattern in (
                r'(?m)^version\s*=\s*"([^"\n]+)"\s*$',
                r'(?m)^version:\s*"?(.*?)"?\s*$',
                r'\bversion="([^"]+)"',
            ):
                match = re.search(pattern, raw)
                if not match:
                    continue
                version = str(match.group(1) or "").strip()
                if version:
                    return version
    return "dev"


APP_VERSION = _detect_app_version()


@dataclass
class RuntimeState:
    cpu_prev_total: Optional[int] = None
    cpu_prev_idle: Optional[int] = None
    active_iface: Optional[str] = None
    prev_rx: Optional[float] = None
    prev_tx: Optional[float] = None
    prev_t: Optional[float] = None
    disk_temp_c: float = 0.0
    disk_temp_available: bool = False
    last_disk_temp_ts: float = 0.0
    disk_usage_pct: float = 0.0
    last_disk_usage_ts: float = 0.0
    fan_rpm: float = 0.0
    fan_available: bool = False
    gpu_temp_c: float = 0.0
    gpu_util_pct: float = 0.0
    gpu_mem_pct: float = 0.0
    gpu_available: bool = False
    last_slow_sensor_ts: float = 0.0
    active_disk: Optional[str] = None
    prev_disk_read_b: Optional[float] = None
    prev_disk_write_b: Optional[float] = None
    rx_buf: str = ""
    tx_frame_index: int = 0
    host_name_sent: bool = False
    ha_token_present: bool = False
    ha_addons_api_ok: Optional[bool] = None
    ha_integrations_api_ok: Optional[bool] = None
    display_sleeping: bool = False
    display_refresh_pending: bool = False
    integration_cache: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    integration_health: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    last_integration_health_payload: str = ""
    last_integration_health_emit_ts: float = 0.0


def safe_float(v: Any, default: Optional[float] = 0.0) -> Optional[float]:
    try:
        return float(v)
    except Exception:
        return default


def safe_int(v: Any, default: Optional[int] = 0) -> Optional[int]:
    try:
        return int(float(v))
    except Exception:
        return default


def _read_first_line(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.readline().strip()


def resolve_host_name() -> str:
    for candidate in (socket.gethostname(), platform.node(), os.environ.get("HOSTNAME", "")):
        name = str(candidate or "").strip()
        if name:
            return name
    return ""


def compact_host_name(value: str, limit: int = 63) -> str:
    cleaned = str(value or "").replace("\r", "").replace("\n", "").replace(",", "_").strip()
    return cleaned[:limit]


def resolve_supervisor_token() -> str:
    token = str(os.environ.get("SUPERVISOR_TOKEN", "") or "").strip()
    if token:
        return token
    try:
        path = Path("/run/s6/container_environment/SUPERVISOR_TOKEN")
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        pass
    return ""


HOST_NAME = resolve_host_name()
HOST_NAME_USB = compact_host_name(HOST_NAME)
SUPERVISOR_TOKEN = resolve_supervisor_token()
SUPERVISOR_HTTP_URL = str(os.environ.get("ESP_HOST_BRIDGE_SUPERVISOR_HTTP", "http://supervisor") or "http://supervisor").rstrip("/")
SUPERVISOR_WS_URL = str(os.environ.get("ESP_HOST_BRIDGE_SUPERVISOR_WS", "ws://supervisor/core/websocket") or "ws://supervisor/core/websocket").rstrip("/")
HOME_ASSISTANT_PLATFORM_MODE = str(os.environ.get("ESP_HOST_BRIDGE_PLATFORM_MODE", "") or "").strip().lower()
HOME_ASSISTANT_SELF_SLUG = str(os.environ.get("ESP_HOST_BRIDGE_SELF_SLUG", "esp_host_bridge") or "esp_host_bridge").strip()


def is_home_assistant_app_mode() -> bool:
    if HOME_ASSISTANT_PLATFORM_MODE == "homeassistant":
        return True
    return bool(SUPERVISOR_TOKEN)


def _humanize_home_assistant_slug(value: Any) -> str:
    slug = str(value or "").strip().lower()
    if not slug:
        return ""
    if slug in HOME_ASSISTANT_SLUG_LABELS:
        return HOME_ASSISTANT_SLUG_LABELS[slug]
    parts = [p for p in re.split(r"[_\-]+", slug) if p]
    if not parts:
        return slug
    return " ".join(part.upper() if len(part) <= 4 else part.capitalize() for part in parts)


def classify_vm_state(state_raw: Any) -> tuple[str, str]:
    text = str(state_raw or "").strip().lower()
    if not text:
        return "stopped", "Stopped"
    if any(token in text for token in ("running", "idle", "in shutdown", "shutdown", "no state")):
        return "running", "Running"
    if any(token in text for token in ("paused", "pmsuspended", "suspended", "blocked")):
        return "paused", "Paused"
    if any(token in text for token in ("shut off", "shutoff", "crashed")):
        return "stopped", "Stopped"
    return "other", text.title()


def _supervisor_request_json(path: str, timeout: float, method: str = "GET", payload: Any = None) -> Any:
    if not SUPERVISOR_TOKEN:
        raise RuntimeError("SUPERVISOR_TOKEN is not available")
    url = SUPERVISOR_HTTP_URL + path
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method=method.upper())
    req.add_header("Authorization", f"Bearer {SUPERVISOR_TOKEN}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    if not raw:
        return {}
    decoded = json.loads(raw.decode("utf-8", errors="ignore"))
    if isinstance(decoded, dict) and "data" in decoded:
        return decoded.get("data")
    return decoded



from .config import cfg_to_agent_args, load_cfg, validate_cfg
from .integrations import (
    CommandContext,
    PollContext,
    command_registry_snapshot,
    dispatch_integration_command,
    get_registered_commands,
    integration_health_snapshot,
    match_registered_command,
    poll_integrations,
)
from .serial import serial_io_bypassed, try_open_serial_once


def detect_host_power_command_defaults() -> Dict[str, str]:
    if is_home_assistant_app_mode():
        return {
            "os": "homeassistant",
            "shutdown_cmd": "Supervisor API /host/shutdown",
            "restart_cmd": "Supervisor API /host/reboot",
        }
    system = platform.system().lower()
    if system == "linux":
        return {
            "os": system,
            "shutdown_cmd": "systemctl poweroff",
            "restart_cmd": "systemctl reboot",
        }
    if system == "darwin":
        return {
            "os": system,
            "shutdown_cmd": "/sbin/shutdown -h now",
            "restart_cmd": "/sbin/shutdown -r now",
        }
    if system == "windows":
        return {
            "os": system,
            "shutdown_cmd": "shutdown /s /t 0",
            "restart_cmd": "shutdown /r /t 0",
        }
    return {"os": system or "unknown", "shutdown_cmd": "", "restart_cmd": ""}

def resolve_host_command_argv(
    cmd: str,
    use_sudo: bool = False,
    shutdown_cmd: Optional[str] = None,
    restart_cmd: Optional[str] = None,
) -> tuple[Optional[list[str]], Optional[str]]:
    cmd_s = (cmd or "").strip()
    cmd_l = cmd_s.lower()
    system = platform.system().lower()

    custom_cmd = ""
    if cmd_l in ("shutdown",):
        custom_cmd = (shutdown_cmd or "").strip()
    elif cmd_l in ("restart", "reboot"):
        custom_cmd = (restart_cmd or "").strip()

    argv: Optional[list[str]] = None
    if custom_cmd:
        try:
            argv = shlex.split(custom_cmd, posix=(os.name != "nt"))
        except Exception as e:
            return None, f"invalid custom host command for CMD={cmd_s} ({e})"
        if not argv:
            return None, f"custom host command is empty for CMD={cmd_s}"
    else:
        if system == "linux":
            if cmd_l in ("shutdown",):
                argv = ["/usr/bin/systemctl", "poweroff"]
            elif cmd_l in ("restart", "reboot"):
                argv = ["/usr/bin/systemctl", "reboot"]
        elif system == "darwin":
            if cmd_l in ("shutdown",):
                argv = ["/sbin/shutdown", "-h", "now"]
            elif cmd_l in ("restart", "reboot"):
                argv = ["/sbin/shutdown", "-r", "now"]
        elif system == "windows":
            if cmd_l in ("shutdown",):
                argv = ["shutdown", "/s", "/t", "0"]
            elif cmd_l in ("restart", "reboot"):
                argv = ["shutdown", "/r", "/t", "0"]

    if argv is None:
        return None, f"unsupported or unknown CMD={cmd_s}"

    if use_sudo and system in {"linux", "darwin"} and argv and argv[0] != "sudo":
        argv = ["sudo"] + argv
    return argv, None


def build_host_power_command_previews(
    *,
    use_sudo: bool = False,
    shutdown_cmd: Optional[str] = None,
    restart_cmd: Optional[str] = None,
) -> list[Dict[str, Any]]:
    runtime_cmd_by_id = {
        "host_shutdown": "shutdown",
        "host_restart": "restart",
    }
    out: list[Dict[str, Any]] = []
    for spec in get_registered_commands():
        if spec.owner_id != "host":
            continue
        runtime_cmd = runtime_cmd_by_id.get(spec.command_id)
        if not runtime_cmd:
            continue
        argv, err = resolve_host_command_argv(
            runtime_cmd,
            use_sudo=use_sudo,
            shutdown_cmd=shutdown_cmd,
            restart_cmd=restart_cmd,
        )
        row: Dict[str, Any] = {
            "command_id": spec.command_id,
            "label": spec.label,
            "trigger": spec.patterns[0] if spec.patterns else runtime_cmd,
            "destructive": bool(spec.destructive),
            "confirmation_text": spec.confirmation_text or None,
        }
        if argv is None:
            row["ok"] = False
            row["command"] = ""
            row["message"] = err or "not available"
        else:
            row["ok"] = True
            row["command"] = " ".join(shlex.quote(x) for x in argv)
            row["message"] = "ok"
        out.append(row)
    return out

def execute_host_command(
    cmd: str,
    use_sudo: bool = False,
    shutdown_cmd: Optional[str] = None,
    restart_cmd: Optional[str] = None,
) -> None:
    cmd_s = (cmd or "").strip()
    argv, err = resolve_host_command_argv(
        cmd_s,
        use_sudo=use_sudo,
        shutdown_cmd=shutdown_cmd,
        restart_cmd=restart_cmd,
    )
    if argv is None:
        logging.warning(err or "ignoring unsupported or unknown CMD=%s", cmd_s)
        return
    logging.info("executing host command: %s", " ".join(shlex.quote(x) for x in argv))
    subprocess.run(argv, check=False)

def resolve_home_assistant_host_power_target(cmd: str) -> tuple[Optional[str], Optional[str]]:
    cmd_s = (cmd or "").strip()
    cmd_l = cmd_s.lower()
    if cmd_l == "shutdown":
        return "/host/shutdown", None
    if cmd_l in ("restart", "reboot"):
        return "/host/reboot", None
    return None, f"unsupported or unknown CMD={cmd_s}"

def execute_home_assistant_host_power_command(cmd: str, timeout: float) -> bool:
    cmd_s = (cmd or "").strip()
    path, err = resolve_home_assistant_host_power_target(cmd_s)
    if not path:
        logging.warning(err or "ignoring unsupported or unknown CMD=%s", cmd_s)
        return False
    try:
        _supervisor_request_json(path, timeout=timeout, method="POST", payload={})
        logging.info("home assistant host power command requested: %s via %s", cmd_s.lower(), path)
    except Exception as e:
        logging.warning("home assistant host power command failed for %s (%s)", cmd_s, e)
    return True

def command_to_power_state(cmd: str) -> Optional[str]:
    cmd_l = (cmd or "").strip().lower()
    if cmd_l == "shutdown":
        return "SHUTTING_DOWN"
    if cmd_l in ("restart", "reboot"):
        return "RESTARTING"
    return None


def handle_display_state_command(cmd: str, state: Optional[RuntimeState]) -> bool:
    cmd_l = (cmd or "").strip().lower()
    if cmd_l == "display_sleep":
        if state is not None:
            if not state.display_sleeping:
                logging.info("display entered sleep; pausing USB telemetry output")
            state.display_sleeping = True
            state.display_refresh_pending = False
        return True
    if cmd_l == "display_wake":
        if state is not None:
            was_sleeping = state.display_sleeping
            state.display_sleeping = False
            state.display_refresh_pending = True
            state.tx_frame_index = 0
            if was_sleeping:
                logging.info("display woke; resuming USB telemetry output")
        return True
    return False

def process_usb_commands(
    ser: Any,
    rx_buf: str,
    state: Optional[RuntimeState] = None,
    allow_host_cmds: bool = False,
    homeassistant_mode: bool = False,
    host_cmd_use_sudo: bool = False,
    docker_socket: str = "/var/run/docker.sock",
    virsh_binary: str = "virsh",
    virsh_uri: Optional[str] = None,
    timeout: float = 2.0,
    shutdown_cmd: Optional[str] = None,
    restart_cmd: Optional[str] = None,
) -> str:
    try:
        n = ser.in_waiting
    except Exception:
        n = 0
    if n <= 0:
        return rx_buf

    raw = ser.read(n)
    if not raw:
        return rx_buf

    rx_buf += raw.decode("utf-8", errors="ignore")
    while True:
        nl = rx_buf.find("\n")
        if nl < 0:
            break
        line = rx_buf[:nl].strip("\r").strip()
        rx_buf = rx_buf[nl + 1 :]
        if not line:
            continue
        logging.info("usb_rx: %s", line)
        if not line.startswith("CMD="):
            continue
        cmd = line.split("=", 1)[1].strip()
        command_spec = match_registered_command(cmd)
        if handle_display_state_command(cmd, state):
            continue
        if allow_host_cmds:
            if dispatch_integration_command(
                cmd,
                CommandContext(
                    args=argparse.Namespace(
                        docker_socket=docker_socket,
                        virsh_binary=virsh_binary,
                        virsh_uri=virsh_uri,
                    ),
                    state=state,
                    timeout=timeout,
                    homeassistant_mode=homeassistant_mode,
                    supervisor_request_json=_supervisor_request_json,
                ),
            ):
                continue
            power_state = command_to_power_state(cmd)
            if power_state:
                try:
                    ack = f"POWER={power_state}\n"
                    ser.write(ack.encode("utf-8", errors="ignore"))
                    ser.flush()
                    logging.info("usb_tx: %s", ack.strip())
                    time.sleep(0.15)
                except Exception as e:
                    logging.warning("failed to send power state to device (%s)", e)
            if homeassistant_mode and power_state:
                execute_home_assistant_host_power_command(cmd, timeout)
                continue
            execute_host_command(
                cmd,
                use_sudo=host_cmd_use_sudo,
                shutdown_cmd=shutdown_cmd,
                restart_cmd=restart_cmd,
            )
        else:
            if command_spec is not None:
                logging.info("registered host command received but disabled (CMD=%s, ID=%s)", cmd, command_spec.command_id)
            else:
                logging.info("host command received but disabled (CMD=%s)", cmd)

    if len(rx_buf) > RX_BUFFER_MAX_BYTES:
        rx_buf = rx_buf[-RX_BUFFER_KEEP_BYTES:]
    return rx_buf

def build_status_line(args: argparse.Namespace, state: RuntimeState) -> str:
    now = time.time()
    homeassistant_mode = is_home_assistant_app_mode()
    state.ha_token_present = bool(SUPERVISOR_TOKEN)
    integration_status = poll_integrations(
        PollContext(
            args=args,
            state=state,
            now=now,
            homeassistant_mode=homeassistant_mode,
        )
    )
    state.integration_health = integration_health_snapshot(integration_status)

    host_status = integration_status.get("host") or {}
    host_metrics = dict(host_status.get("metrics") or {})
    cpu_pct = float(safe_float(host_metrics.get("cpu_pct"), 0.0) or 0.0)
    mem_pct = float(safe_float(host_metrics.get("mem_pct"), 0.0) or 0.0)
    uptime_s = float(safe_float(host_metrics.get("uptime_s"), 0.0) or 0.0)
    cpu_temp = float(safe_float(host_metrics.get("cpu_temp_c"), 0.0) or 0.0)
    cpu_temp_available = bool(host_metrics.get("cpu_temp_available"))
    disk_temp_available = bool(host_metrics.get("disk_temp_available"))
    gpu_enabled = bool(host_metrics.get("gpu_enabled", not bool(getattr(args, "disable_gpu_polling", False))))
    fan_available = bool(host_metrics.get("fan_available"))
    gpu_available = bool(host_metrics.get("gpu_available"))
    state.active_iface = str(host_metrics.get("active_iface") or state.active_iface or "")
    state.active_disk = str(host_metrics.get("active_disk") or state.active_disk or "")
    rx_kbps = float(safe_float(host_metrics.get("rx_kbps"), 0.0) or 0.0)
    tx_kbps = float(safe_float(host_metrics.get("tx_kbps"), 0.0) or 0.0)
    disk_r_kbs = float(safe_float(host_metrics.get("disk_r_kbs"), 0.0) or 0.0)
    disk_w_kbs = float(safe_float(host_metrics.get("disk_w_kbs"), 0.0) or 0.0)
    state.disk_temp_c = float(safe_float(host_metrics.get("disk_temp_c"), 0.0) or 0.0)
    state.disk_usage_pct = float(safe_float(host_metrics.get("disk_usage_pct"), 0.0) or 0.0)
    state.fan_rpm = float(safe_float(host_metrics.get("fan_rpm"), 0.0) or 0.0)
    state.gpu_temp_c = float(safe_float(host_metrics.get("gpu_temp_c"), 0.0) or 0.0)
    state.gpu_util_pct = float(safe_float(host_metrics.get("gpu_util_pct"), 0.0) or 0.0)
    state.gpu_mem_pct = float(safe_float(host_metrics.get("gpu_mem_pct"), 0.0) or 0.0)

    docker_status = integration_status.get("docker") or {}
    docker_enabled = bool(docker_status.get("enabled", not bool(getattr(args, "disable_docker_polling", False))))
    docker = list(docker_status.get("items") or [])
    docker_counts = dict(docker_status.get("counts") or {"running": 0, "stopped": 0, "unhealthy": 0})
    docker_compact = str(docker_status.get("compact") or "")
    state.ha_addons_api_ok = docker_status.get("api_ok")

    vm_status = integration_status.get("vms") or {}
    vm_enabled = bool(vm_status.get("enabled", not bool(getattr(args, "disable_vm_polling", False))))
    vms = list(vm_status.get("items") or [])
    vm_counts = dict(vm_status.get("counts") or {"running": 0, "stopped": 0, "paused": 0, "other": 0})
    vm_compact = str(vm_status.get("compact") or "-")
    state.ha_integrations_api_ok = vm_status.get("api_ok")

    ha_docker_api = -1 if state.ha_addons_api_ok is None else (1 if state.ha_addons_api_ok else 0)
    ha_vms_api = -1 if state.ha_integrations_api_ok is None else (1 if state.ha_integrations_api_ok else 0)

    frame = state.tx_frame_index % 5
    state.tx_frame_index = (state.tx_frame_index + 1) % 5

    # Rotate compact frames to avoid overflowing the ESP USB CDC RX buffer.
    if frame == 0:
        return (
            f"CPU={cpu_pct:.1f},"
            f"TEMP={cpu_temp:.1f},"
            f"MEM={mem_pct:.1f},"
            f"UP={int(uptime_s)},"
            f"RX={rx_kbps:.0f},"
            f"TX={tx_kbps:.0f},"
            f"IFACE={state.active_iface or ''},"
            f"TEMPAV={1 if cpu_temp_available else 0},"
            f"HAMODE={1 if homeassistant_mode else 0},"
            f"HATOKEN={1 if state.ha_token_present else 0},"
            f"HADOCKAPI={ha_docker_api},"
            f"HAVMSAPI={ha_vms_api},"
            f"GPUEN={1 if gpu_enabled else 0},"
            f"DOCKEREN={1 if docker_enabled else 0},"
            f"VMSEN={1 if vm_enabled else 0},"
            f"POWER=RUNNING\n"
        )
    if frame == 1:
        return (
            f"DISK={state.disk_temp_c:.1f},"
            f"DISKPCT={state.disk_usage_pct:.1f},"
            f"DISKR={disk_r_kbs:.0f},"
            f"DISKW={disk_w_kbs:.0f},"
            f"FAN={state.fan_rpm:.0f},"
            f"DISKTAV={1 if disk_temp_available else 0},"
            f"FANAV={1 if fan_available else 0},"
            f"POWER=RUNNING\n"
        )
    if frame == 2:
        return (
            f"GPUT={state.gpu_temp_c:.1f},"
            f"GPUU={state.gpu_util_pct:.0f},"
            f"GPUVM={state.gpu_mem_pct:.0f},"
            f"GPUAV={1 if gpu_available else 0},"
            f"POWER=RUNNING\n"
        )
    if frame == 3:
        return (
            f"DOCKRUN={int(docker_counts.get('running', 0))},"
            f"DOCKSTOP={int(docker_counts.get('stopped', 0))},"
            f"DOCKUNH={int(docker_counts.get('unhealthy', 0))},"
            f"DOCKER={docker_compact},"
            f"POWER=RUNNING\n"
        )
    return (
        f"VMSRUN={int(vm_counts.get('running', 0))},"
        f"VMSSTOP={int(vm_counts.get('stopped', 0))},"
        f"VMSPAUSE={int(vm_counts.get('paused', 0))},"
        f"VMSOTHER={int(vm_counts.get('other', 0))},"
        f"VMS={vm_compact},"
        f"POWER=RUNNING\n"
    )


def maybe_build_integration_health_line(state: RuntimeState, now: float) -> Optional[str]:
    if not state.integration_health:
        return None
    try:
        payload = json.dumps(state.integration_health, sort_keys=True, separators=(",", ":"))
        compare_rows: Dict[str, Dict[str, Any]] = {}
        for key, value in state.integration_health.items():
            if not isinstance(value, dict):
                continue
            row = dict(value)
            row.pop("last_refresh_ts", None)
            row.pop("last_success_ts", None)
            row.pop("last_error_ts", None)
            compare_rows[str(key)] = row
        compare_payload = json.dumps(compare_rows, sort_keys=True, separators=(",", ":"))
    except Exception:
        return None
    if (
        compare_payload == state.last_integration_health_payload
        and (now - float(state.last_integration_health_emit_ts or 0.0)) < INTEGRATION_HEALTH_LOG_MIN_INTERVAL_SECONDS
    ):
        return None
    state.last_integration_health_payload = compare_payload
    state.last_integration_health_emit_ts = now
    return f"INTEGRATION_HEALTH={payload}"

def agent_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="esp-host-bridge agent")
    ap.add_argument(
        "--serial-port",
        default=None,
        help="Serial device path (auto-detect if omitted; set to NONE or DEBUG to run without USB serial I/O)",
    )
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--timeout", type=float, default=2.0)
    ap.add_argument("--iface", default=None, help="Network interface name, e.g. eth0")
    ap.add_argument("--docker-socket", default="/var/run/docker.sock", help="Docker Engine Unix socket path")
    ap.add_argument("--docker-interval", type=float, default=2.0, help="Docker refresh interval in seconds (0 disables polling)")
    ap.add_argument("--disable-docker-polling", action="store_true", help="Disable Docker polling entirely")
    ap.add_argument("--virsh-binary", default="virsh", help="virsh executable path")
    ap.add_argument("--virsh-uri", default=None, help="Optional virsh connection URI, e.g. qemu:///system")
    ap.add_argument("--vm-interval", type=float, default=5.0, help="VM refresh interval in seconds (0 disables polling)")
    ap.add_argument("--disable-vm-polling", action="store_true", help="Disable VM polling entirely")
    ap.add_argument("--disable-gpu-polling", action="store_true", help="Disable GPU polling entirely")
    ap.add_argument("--disk-device", default=None, help="Disk device for throughput (e.g. /dev/nvme0n1 or sda)")
    ap.add_argument("--disk-temp-device", default=None, help="Disk device for temperature (e.g. /dev/nvme0n1)")
    ap.add_argument("--cpu-temp-sensor", default=None, help="Preferred CPU/core temperature sensor identifier")
    ap.add_argument("--fan-sensor", default=None, help="Preferred fan sensor identifier")
    ap.add_argument(
        "--allow-host-cmds",
        action="store_true",
        help="Execute host actions from USB CDC commands (shutdown/restart/docker_start/docker_stop/vm_start/vm_stop/vm_force_stop/vm_restart)",
    )
    ap.add_argument(
        "--host-cmd-use-sudo",
        action="store_true",
        help="Run host commands via sudo (requires sudoers rule)",
    )
    ap.add_argument("--shutdown-cmd", default=None, help="Custom host shutdown command")
    ap.add_argument("--restart-cmd", default=None, help="Custom host restart command")
    return ap

def run_agent(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    last_port = None
    state = RuntimeState()
    ser = None
    next_serial_retry_at = 0.0
    next_sleep_probe_at = 0.0
    debug_mode = serial_io_bypassed(getattr(args, "serial_port", None))
    if debug_mode:
        logging.info("serial link disabled by configuration (serial_port=NONE/DEBUG)")
    try:
        while True:
            now = time.time()
            if ser is None and not debug_mode and now >= next_serial_retry_at:
                ser, last_port = try_open_serial_once(args.serial_port, args.baud, last_port=last_port)
                if ser is None:
                    next_serial_retry_at = now + SERIAL_RETRY_SECONDS
                else:
                    state.host_name_sent = False
                    state.display_sleeping = False
                    state.display_refresh_pending = True
                    state.tx_frame_index = 0
            try:
                if ser is not None:
                    state.rx_buf = process_usb_commands(
                        ser,
                        state.rx_buf,
                        state=state,
                        allow_host_cmds=args.allow_host_cmds,
                        homeassistant_mode=is_home_assistant_app_mode(),
                        host_cmd_use_sudo=args.host_cmd_use_sudo,
                        docker_socket=args.docker_socket,
                        virsh_binary=args.virsh_binary,
                        virsh_uri=args.virsh_uri,
                        timeout=args.timeout,
                        shutdown_cmd=args.shutdown_cmd,
                        restart_cmd=args.restart_cmd,
                    )
                line = build_status_line(args, state)
                logging.info("%s", line.strip())
                health_line = maybe_build_integration_health_line(state, now)
                if health_line:
                    logging.info("%s", health_line)
                if ser is not None:
                    if not state.display_sleeping:
                        next_sleep_probe_at = 0.0
                        if not state.host_name_sent and HOST_NAME_USB:
                            ser.write(f"HOSTNAME={HOST_NAME_USB}\n".encode("utf-8", errors="ignore"))
                            state.host_name_sent = True
                        ser.write(line.encode("utf-8", errors="ignore"))
                        state.display_refresh_pending = False
                    elif now >= next_sleep_probe_at:
                        ser.write(b"\n")
                        ser.flush()
                        next_sleep_probe_at = now + SLEEP_SERIAL_PROBE_SECONDS
                    state.rx_buf = process_usb_commands(
                        ser,
                        state.rx_buf,
                        state=state,
                        allow_host_cmds=args.allow_host_cmds,
                        homeassistant_mode=is_home_assistant_app_mode(),
                        host_cmd_use_sudo=args.host_cmd_use_sudo,
                        docker_socket=args.docker_socket,
                        virsh_binary=args.virsh_binary,
                        virsh_uri=args.virsh_uri,
                        timeout=args.timeout,
                        shutdown_cmd=args.shutdown_cmd,
                        restart_cmd=args.restart_cmd,
                    )
                    if state.display_refresh_pending and not state.display_sleeping:
                        line = build_status_line(args, state)
                        logging.info("%s", line.strip())
                        health_line = maybe_build_integration_health_line(state, now)
                        if health_line:
                            logging.info("%s", health_line)
                        if not state.host_name_sent and HOST_NAME_USB:
                            ser.write(f"HOSTNAME={HOST_NAME_USB}\n".encode("utf-8", errors="ignore"))
                            state.host_name_sent = True
                        ser.write(line.encode("utf-8", errors="ignore"))
                        state.display_refresh_pending = False
            except (SerialException, OSError) as e:
                logging.warning("serial write failed (%s), reconnecting...", e)
                try:
                    ser.close()
                except Exception:
                    pass
                ser = None
                state.rx_buf = ""
                next_serial_retry_at = time.time() + SERIAL_RETRY_SECONDS
                next_sleep_probe_at = 0.0
            except Exception as e:
                logging.warning("%s", e)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        logging.info("stopped by user (KeyboardInterrupt)")
        return 0
    finally:
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass
    return 0

class RunnerManager:
    def __init__(self, self_script: Path, python_bin: str, package_module: Optional[str] = None) -> None:
        self.self_script = self_script
        self.python_bin = python_bin
        self.package_module = str(package_module or "").strip() or None
        self._lock = threading.RLock()
        self._proc: Optional[subprocess.Popen[str]] = None
        self._logs: Deque[tuple[int, str]] = deque(maxlen=MAX_LOG_LINES)
        self._next_log_id = 1
        self._comm_logs: Deque[tuple[int, str]] = deque(maxlen=MAX_LOG_LINES)
        self._next_comm_log_id = 1
        self._started_at: Optional[float] = None
        self._last_exit: Optional[int] = None
        self._cmd: Optional[list[str]] = None
        self._last_metrics_line: str = ""
        self._last_metrics_at: Optional[float] = None
        self._last_metrics: Dict[str, str] = {}
        self._metric_history: Dict[str, Deque[tuple[float, float]]] = {}
        self._serial_connected: Optional[bool] = None
        self._serial_disconnect_count: int = 0
        self._last_serial_disconnect_at: Optional[float] = None
        self._last_serial_reconnect_at: Optional[float] = None
        self._last_comm_event_at: Optional[float] = None
        self._last_comm_event_text: str = ""
        self._esp_boot_count: int = 0
        self._last_esp_boot_at: Optional[float] = None
        self._last_esp_boot_id: str = ""
        self._last_esp_boot_reason: str = ""
        self._last_esp_boot_line: str = ""
        self._display_sleeping: Optional[bool] = None
        self._last_esp_wifi_at: Optional[float] = None
        self._esp_wifi_state: str = ""
        self._esp_wifi_rssi_dbm: Optional[int] = None
        self._esp_wifi_ip: str = ""
        self._esp_wifi_ssid: str = ""
        self._integration_health_cache: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _is_comm_event_line(line: str) -> bool:
        ll = (line or "").lower()
        comm_markers = [
            "serial connected:",
            "serial write failed",
            "serial open failed",
            "serial port not found:",
            "no serial port available",
            "no serial ports detected",
            "available ports:",
            "failed to send power state to device",
            "usb_cdc",
            "esp=boot",
            "display entered sleep",
            "display woke",
        ]
        if any(m in ll for m in comm_markers):
            return True
        # Include indented available-port list lines after "available ports:"
        if ll.startswith("warning:   - /dev/") or ll.startswith("  - /dev/"):
            return True
        return False

    def _update_comm_state_from_line(self, line: str) -> None:
        ll = (line or "").lower()
        now_ts = time.time()
        self._last_comm_event_at = now_ts
        self._last_comm_event_text = (line or "").strip()
        if "serial connected:" in ll:
            self._serial_connected = True
            self._display_sleeping = False
            self._last_serial_reconnect_at = now_ts
            return
        if "display entered sleep" in ll:
            self._display_sleeping = True
            return
        if "display woke" in ll:
            self._display_sleeping = False
            return
        if "esp=boot" in ll:
            if self._serial_connected is not True:
                self._last_serial_reconnect_at = now_ts
            self._serial_connected = True
            self._display_sleeping = False
            return
        if "serial write failed" in ll or "serial open failed" in ll:
            self._serial_connected = False
            self._serial_disconnect_count += 1
            self._last_serial_disconnect_at = now_ts
            return
        if "serial port not found:" in ll or "no serial port available" in ll:
            self._serial_connected = False
            if self._last_serial_disconnect_at is None:
                self._last_serial_disconnect_at = now_ts

    def _try_capture_metrics(self, line: str) -> None:
        raw = (line or "").strip()
        if not raw:
            return
        # Agent logs are usually prefixed (e.g. "INFO: "), so find the first metrics token.
        m = re.search(r'\b[A-Z][A-Z0-9_]*=', raw)
        if not m:
            return
        payload = raw[m.start():]
        if payload.startswith("INTEGRATION_HEALTH="):
            return
        if ',' not in payload and 'POWER=' not in payload:
            return
        metrics: Dict[str, str] = {}
        for part in payload.split(','):
            if '=' not in part:
                continue
            k, v = part.split('=', 1)
            key = k.strip().upper()
            val = v.strip()
            if not key:
                continue
            metrics[key] = val
        if not metrics:
            return
        now_ts = time.time()
        with self._lock:
            merged = dict(self._last_metrics)
            merged.update(metrics)
            self._last_metrics_line = payload
            self._last_metrics_at = now_ts
            self._last_metrics = merged
            for k, v in metrics.items():
                try:
                    fv = float(v)
                except Exception:
                    continue
                hist = self._metric_history.get(k)
                if hist is None:
                    hist = deque(maxlen=METRIC_HISTORY_POINTS)
                    self._metric_history[k] = hist
                hist.append((now_ts, fv))
            self._refresh_integration_health_from_metrics(metrics, now_ts)

    def _refresh_integration_health_from_metrics(self, metrics: Dict[str, str], now_ts: float) -> None:
        data = getattr(self, "_integration_health_cache", None)
        if not isinstance(data, dict) or not data:
            return

        def _touch(key: str) -> None:
            row = data.get(key)
            if not isinstance(row, dict):
                return
            if row.get("enabled") is False:
                return
            if row.get("available") is False:
                return
            row["last_refresh_ts"] = now_ts
            row["last_success_ts"] = now_ts

        metric_keys = set(metrics.keys())
        if metric_keys.intersection({"CPU", "MEM", "TEMP", "RX", "TX", "DISK", "DISKPCT", "DISKR", "DISKW", "FAN", "GPUT", "GPUU", "GPUVM"}):
            _touch("host")
        if metric_keys.intersection({"DOCKRUN", "DOCKSTOP", "DOCKUNH", "DOCKER"}):
            _touch("docker")
        if metric_keys.intersection({"VMSRUN", "VMSSTOP", "VMSPAUSE", "VMSOTHER", "VMS"}):
            _touch("vms")

    def _try_capture_esp_boot(self, line: str) -> None:
        raw = (line or "").strip()
        if not raw:
            return
        match = ESP_BOOT_LINE_RE.search(raw)
        if not match:
            return
        boot_id = (match.group(1) or "").strip().upper()
        boot_reason = (match.group(2) or "").strip().upper()
        now_ts = time.time()
        with self._lock:
            if boot_id:
                if boot_id == self._last_esp_boot_id and self._last_esp_boot_at and (now_ts - self._last_esp_boot_at) < 30.0:
                    return
            elif raw == self._last_esp_boot_line and self._last_esp_boot_at and (now_ts - self._last_esp_boot_at) < 10.0:
                return
            self._esp_boot_count += 1
            self._last_esp_boot_at = now_ts
            self._last_esp_boot_id = boot_id
            self._last_esp_boot_reason = boot_reason
            self._last_esp_boot_line = raw

    def _try_capture_esp_wifi(self, line: str) -> None:
        raw = (line or "").strip()
        marker = "ESP=WIFI"
        pos = raw.find(marker)
        if pos < 0:
            return
        payload = raw[pos:]
        parts: Dict[str, str] = {}
        for part in payload.split(","):
            if "=" not in part:
                continue
            k, v = part.split("=", 1)
            key = k.strip().upper()
            val = v.strip()
            if key:
                parts[key] = val
        if parts.get("ESP", "").strip().upper() != "WIFI":
            return
        state = str(parts.get("STATE", "") or "").strip().upper()
        rssi_val = str(parts.get("RSSI", "") or "").strip()
        ip = str(parts.get("IP", "") or "").strip()
        ssid = str(parts.get("SSID", "") or "").strip()
        rssi: Optional[int] = None
        if rssi_val:
            try:
                rssi = int(float(rssi_val))
            except Exception:
                rssi = None
        now_ts = time.time()
        with self._lock:
            self._last_esp_wifi_at = now_ts
            self._esp_wifi_state = state
            if state == "CONNECTED":
                self._esp_wifi_rssi_dbm = rssi
                self._esp_wifi_ip = ip
                self._esp_wifi_ssid = ssid
            else:
                self._esp_wifi_rssi_dbm = None
                self._esp_wifi_ip = ""
                self._esp_wifi_ssid = ""

    def _try_capture_integration_health(self, line: str) -> None:
        raw = (line or "").strip()
        marker = "INTEGRATION_HEALTH="
        pos = raw.find(marker)
        if pos < 0:
            return
        payload = raw[pos + len(marker):].strip()
        if not payload:
            return
        try:
            decoded = json.loads(payload)
        except Exception:
            return
        if not isinstance(decoded, dict):
            return
        cleaned: Dict[str, Dict[str, Any]] = {}
        for key, value in decoded.items():
            if isinstance(value, dict):
                cleaned[str(key)] = dict(value)
        with self._lock:
            self._integration_health_cache = cleaned

    def _append_log(self, line: str) -> None:
        raw = line.rstrip("\n")
        if not raw:
            line = "\n"
        elif re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\s", raw):
            line = raw + "\n"
        else:
            line = f"{fmt_ts(time.time())} {raw}\n"
        self._try_capture_metrics(line)
        self._try_capture_esp_boot(line)
        self._try_capture_esp_wifi(line)
        self._try_capture_integration_health(line)
        with self._lock:
            self._logs.append((self._next_log_id, line))
            self._next_log_id += 1
            if self._is_comm_event_line(line):
                self._update_comm_state_from_line(line)
                self._comm_logs.append((self._next_comm_log_id, line))
                self._next_comm_log_id += 1

    def log_event(self, line: str) -> None:
        self._append_log(line)

    def logs_tail_text(self, limit: int = 140) -> str:
        with self._lock:
            tail = list(self._logs)[-limit:]
        return "".join([line for _, line in tail])

    def logs_all_text(self) -> str:
        with self._lock:
            rows = list(self._logs)
        return "".join([line for _, line in rows])

    def comm_logs_tail_text(self, limit: int = 140) -> str:
        with self._lock:
            tail = list(self._comm_logs)[-limit:]
        return "".join([line for _, line in tail])

    def comm_logs_all_text(self) -> str:
        with self._lock:
            rows = list(self._comm_logs)
        return "".join([line for _, line in rows])

    def logs_since(self, since: int) -> tuple[list[dict[str, Any]], int]:
        with self._lock:
            rows = [{"id": i, "text": line} for i, line in self._logs if i >= since]
            next_id = self._next_log_id
        return rows, next_id

    def comm_logs_since(self, since: int) -> tuple[list[dict[str, Any]], int]:
        with self._lock:
            rows = [{"id": i, "text": line} for i, line in self._comm_logs if i >= since]
            next_id = self._next_comm_log_id
        return rows, next_id

    def clear_logs(self) -> None:
        with self._lock:
            self._logs.clear()
            self._next_log_id = 1

    def clear_comm_logs(self) -> None:
        with self._lock:
            self._comm_logs.clear()
            self._next_comm_log_id = 1

    def status(self) -> Dict[str, Any]:
        with self._lock:
            running = self._proc is not None and self._proc.poll() is None
            active_iface = self._last_metrics.get("IFACE") or None
            return {
                "host_name": HOST_NAME or None,
                "bridge_version": APP_VERSION,
                "platform_mode": "homeassistant" if is_home_assistant_app_mode() else "host",
                "running": running,
                "pid": self._proc.pid if running and self._proc else None,
                "started_at": self._started_at,
                "last_exit": self._last_exit,
                "cmd": self._cmd,
                "next_log_id": self._next_log_id,
                "next_comm_log_id": self._next_comm_log_id,
                "comm_status": {
                    "serial_connected": self._serial_connected,
                    "serial_disconnect_count": self._serial_disconnect_count,
                    "last_serial_disconnect_at": self._last_serial_disconnect_at,
                    "last_serial_reconnect_at": self._last_serial_reconnect_at,
                    "last_comm_event_at": self._last_comm_event_at,
                    "last_comm_event_age_s": (time.time() - self._last_comm_event_at) if self._last_comm_event_at else None,
                    "last_comm_event_text": self._last_comm_event_text,
                },
                "esp_status": {
                    "boot_count": self._esp_boot_count,
                    "last_boot_at": self._last_esp_boot_at,
                    "last_boot_age_s": (time.time() - self._last_esp_boot_at) if self._last_esp_boot_at else None,
                    "last_boot_id": self._last_esp_boot_id,
                    "last_boot_reason": self._last_esp_boot_reason,
                    "display_sleeping": self._display_sleeping,
                    "wifi_state": self._esp_wifi_state,
                    "wifi_rssi_dbm": self._esp_wifi_rssi_dbm,
                    "wifi_ip": self._esp_wifi_ip,
                    "wifi_ssid": self._esp_wifi_ssid,
                    "wifi_age_s": (time.time() - self._last_esp_wifi_at) if self._last_esp_wifi_at else None,
                },
                "last_metrics_at": self._last_metrics_at,
                "last_metrics_age_s": (time.time() - self._last_metrics_at) if self._last_metrics_at else None,
                "last_metrics": dict(self._last_metrics),
                "last_metrics_line": self._last_metrics_line,
                "active_iface": active_iface,
                "integration_health": copy.deepcopy(self._integration_health_or_default()),
                "command_registry": command_registry_snapshot(),
                "metric_history": {k: [float(vv) for _, vv in rows] for k, rows in self._metric_history.items()},
            }

    def _integration_health_or_default(self) -> Dict[str, Dict[str, Any]]:
        data = getattr(self, "_integration_health_cache", None)
        if isinstance(data, dict):
            now_ts = time.time()
            out: Dict[str, Dict[str, Any]] = {}
            for key, value in data.items():
                if not isinstance(value, dict):
                    continue
                row = dict(value)
                last_refresh_ts = safe_float(row.get("last_refresh_ts"), None)
                last_success_ts = safe_float(row.get("last_success_ts"), None)
                last_error_ts = safe_float(row.get("last_error_ts"), None)
                row["last_refresh_age_s"] = (now_ts - last_refresh_ts) if last_refresh_ts else None
                row["last_success_age_s"] = (now_ts - last_success_ts) if last_success_ts else None
                row["last_error_age_s"] = (now_ts - last_error_ts) if last_error_ts else None
                out[str(key)] = row
            return out
        return {}

    def _on_process_exit(self, proc: subprocess.Popen[str]) -> None:
        rc = proc.wait()
        self._append_log(f"[agent exited rc={rc}]")
        with self._lock:
            if self._proc is proc:
                self._proc = None
            self._last_exit = rc

    def _start_reader(self, proc: subprocess.Popen[str]) -> None:
        def run() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                self._append_log(line)

        threading.Thread(target=run, name="agent-stdout", daemon=True).start()
        threading.Thread(target=self._on_process_exit, args=(proc,), name="agent-exit", daemon=True).start()

    def start(self, cfg: Dict[str, Any]) -> tuple[bool, str]:
        ok, msg = validate_cfg(cfg)
        if not ok:
            return False, msg
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return False, "Process is already running"

        if self.package_module:
            cmd = [self.python_bin, "-m", self.package_module, "agent"] + cfg_to_agent_args(cfg)
        else:
            cmd = [self.python_bin, str(self.self_script), "agent"] + cfg_to_agent_args(cfg)
        self._append_log("[starting] " + " ".join(shlex.quote(x) for x in cmd))
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=(os.name != "nt"),
            )
        except Exception as e:
            self._append_log(f"[start failed] {e}")
            return False, f"Failed to start: {e}"

        with self._lock:
            self._proc = proc
            self._started_at = time.time()
            self._last_exit = None
            self._cmd = cmd
        self._start_reader(proc)
        return True, "Started"

    def stop(self, timeout: float = 5.0) -> tuple[bool, str]:
        with self._lock:
            proc = self._proc
        if proc is None or proc.poll() is not None:
            return False, "No running process"
        self._append_log("[stopping]")
        try:
            if os.name == "nt":
                proc.terminate()
            else:
                os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._append_log("[did not exit in time; killing]")
                if os.name == "nt":
                    proc.kill()
                else:
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=timeout)
        except Exception as e:
            return False, f"Failed to stop: {e}"
        with self._lock:
            if self._proc is proc:
                self._proc = None
        return True, "Stopped"

    def restart(self, cfg: Dict[str, Any]) -> tuple[bool, str]:
        self.stop()
        time.sleep(0.2)
        return self.start(cfg)

    def stop_noexcept(self) -> None:
        try:
            self.stop()
        except Exception:
            pass

def fmt_ts(ts: Optional[float]) -> str:
    if not ts:
        return "--"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))

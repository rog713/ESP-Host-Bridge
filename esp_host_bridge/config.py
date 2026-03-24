from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any, Dict


def default_webui_config_path() -> Path:
    env = os.environ.get("WEBUI_CONFIG", "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().with_name("config.json")

def webui_default_cfg() -> Dict[str, Any]:
    return {
        "serial_port": "",
        "baud": 115200,
        "interval": 1.0,
        "timeout": 2.0,
        "iface": "",
        "docker_socket": "/var/run/docker.sock",
        "docker_polling_enabled": True,
        "docker_interval": 2.0,
        "virsh_binary": "virsh",
        "virsh_uri": "",
        "vm_polling_enabled": True,
        "vm_interval": 5.0,
        "gpu_polling_enabled": True,
        "disk_device": "",
        "disk_temp_device": "",
        "cpu_temp_sensor": "",
        "fan_sensor": "",
        "allow_host_cmds": False,
        "host_cmd_use_sudo": False,
        "shutdown_cmd": "",
        "restart_cmd": "",
        "webui_auth_enabled": False,
        "webui_password_hash": "",
        "webui_session_secret": "",
    }

def _clean_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    return str(v).strip()

def _clean_int(v: Any, default: int) -> int:
    try:
        return int(str(v).strip())
    except Exception:
        return default

def _clean_float(v: Any, default: float) -> float:
    try:
        return float(str(v).strip())
    except Exception:
        return default

def _clean_bool(v: Any, default: bool = False) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in {"1", "true", "yes", "on"}:
        return True
    if s in {"0", "false", "no", "off"}:
        return False
    return default

def normalize_cfg(raw: Dict[str, Any]) -> Dict[str, Any]:
    cfg = webui_default_cfg()
    cfg["serial_port"] = _clean_str(raw.get("serial_port", cfg["serial_port"]), cfg["serial_port"])
    cfg["baud"] = _clean_int(raw.get("baud", cfg["baud"]), cfg["baud"])
    cfg["interval"] = _clean_float(raw.get("interval", cfg["interval"]), cfg["interval"])
    cfg["timeout"] = _clean_float(raw.get("timeout", cfg["timeout"]), cfg["timeout"])
    cfg["iface"] = _clean_str(raw.get("iface", cfg["iface"]), cfg["iface"])
    cfg["docker_socket"] = _clean_str(raw.get("docker_socket", cfg["docker_socket"]), cfg["docker_socket"])
    cfg["docker_polling_enabled"] = _clean_bool(raw.get("docker_polling_enabled", cfg["docker_polling_enabled"]), cfg["docker_polling_enabled"])
    cfg["docker_interval"] = _clean_float(raw.get("docker_interval", cfg["docker_interval"]), cfg["docker_interval"])
    cfg["virsh_binary"] = _clean_str(raw.get("virsh_binary", cfg["virsh_binary"]), cfg["virsh_binary"])
    cfg["virsh_uri"] = _clean_str(raw.get("virsh_uri", cfg["virsh_uri"]), cfg["virsh_uri"])
    cfg["vm_polling_enabled"] = _clean_bool(raw.get("vm_polling_enabled", cfg["vm_polling_enabled"]), cfg["vm_polling_enabled"])
    cfg["vm_interval"] = _clean_float(raw.get("vm_interval", cfg["vm_interval"]), cfg["vm_interval"])
    cfg["gpu_polling_enabled"] = _clean_bool(raw.get("gpu_polling_enabled", cfg["gpu_polling_enabled"]), cfg["gpu_polling_enabled"])
    cfg["disk_device"] = _clean_str(raw.get("disk_device", cfg["disk_device"]), cfg["disk_device"])
    cfg["disk_temp_device"] = _clean_str(raw.get("disk_temp_device", cfg["disk_temp_device"]), cfg["disk_temp_device"])
    cfg["cpu_temp_sensor"] = _clean_str(raw.get("cpu_temp_sensor", cfg["cpu_temp_sensor"]), cfg["cpu_temp_sensor"])
    cfg["fan_sensor"] = _clean_str(raw.get("fan_sensor", cfg["fan_sensor"]), cfg["fan_sensor"])
    cfg["allow_host_cmds"] = _clean_bool(raw.get("allow_host_cmds", cfg["allow_host_cmds"]), cfg["allow_host_cmds"])
    cfg["host_cmd_use_sudo"] = _clean_bool(raw.get("host_cmd_use_sudo", cfg["host_cmd_use_sudo"]), cfg["host_cmd_use_sudo"])
    cfg["shutdown_cmd"] = _clean_str(raw.get("shutdown_cmd", cfg["shutdown_cmd"]), cfg["shutdown_cmd"])
    cfg["restart_cmd"] = _clean_str(raw.get("restart_cmd", cfg["restart_cmd"]), cfg["restart_cmd"])
    cfg["webui_auth_enabled"] = _clean_bool(raw.get("webui_auth_enabled", cfg["webui_auth_enabled"]), cfg["webui_auth_enabled"])
    cfg["webui_password_hash"] = _clean_str(raw.get("webui_password_hash", cfg["webui_password_hash"]), cfg["webui_password_hash"])
    cfg["webui_session_secret"] = _clean_str(raw.get("webui_session_secret", cfg["webui_session_secret"]), cfg["webui_session_secret"])
    return cfg

def ensure_webui_session_secret(cfg: Dict[str, Any]) -> tuple[Dict[str, Any], bool]:
    updated = normalize_cfg(cfg)
    secret_value = _clean_str(updated.get("webui_session_secret"), "")
    if secret_value:
        return updated, False
    updated["webui_session_secret"] = secrets.token_hex(32)
    return updated, True

def validate_cfg(cfg: Dict[str, Any]) -> tuple[bool, str]:
    if _clean_int(cfg.get("baud"), 0) <= 0:
        return False, "baud must be > 0"
    if _clean_float(cfg.get("interval"), 0.0) <= 0.0:
        return False, "interval must be > 0"
    if _clean_float(cfg.get("timeout"), 0.0) <= 0.0:
        return False, "timeout must be > 0"
    if _clean_float(cfg.get("docker_interval"), 0.0) < 0.0:
        return False, "docker_interval must be >= 0"
    if _clean_float(cfg.get("vm_interval"), 0.0) < 0.0:
        return False, "vm_interval must be >= 0"
    if _clean_bool(cfg.get("docker_polling_enabled"), True) and _clean_float(cfg.get("docker_interval"), 0.0) > 0.0 and not _clean_str(cfg.get("docker_socket")):
        return False, "docker_socket is required when docker polling is enabled"
    return True, "ok"

def load_cfg(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            obj = json.load(f)
    except Exception:
        return webui_default_cfg()
    if not isinstance(obj, dict):
        return webui_default_cfg()
    return normalize_cfg(obj)

def atomic_write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(json.dumps(obj, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)

def cfg_to_agent_args(cfg: Dict[str, Any]) -> list[str]:
    argv = [
        "--baud",
        str(_clean_int(cfg.get("baud"), 115200)),
        "--interval",
        str(_clean_float(cfg.get("interval"), 1.0)),
        "--timeout",
        str(_clean_float(cfg.get("timeout"), 2.0)),
        "--docker-socket",
        _clean_str(cfg.get("docker_socket"), "/var/run/docker.sock"),
        "--docker-interval",
        str(_clean_float(cfg.get("docker_interval"), 2.0)),
        "--virsh-binary",
        _clean_str(cfg.get("virsh_binary"), "virsh"),
        "--vm-interval",
        str(_clean_float(cfg.get("vm_interval"), 5.0)),
    ]
    for key, flag in [
        ("serial_port", "--serial-port"),
        ("iface", "--iface"),
        ("virsh_uri", "--virsh-uri"),
        ("disk_device", "--disk-device"),
        ("disk_temp_device", "--disk-temp-device"),
        ("cpu_temp_sensor", "--cpu-temp-sensor"),
        ("fan_sensor", "--fan-sensor"),
    ]:
        val = _clean_str(cfg.get(key), "")
        if val:
            argv += [flag, val]
    if not _clean_bool(cfg.get("docker_polling_enabled"), True):
        argv += ["--disable-docker-polling"]
    if not _clean_bool(cfg.get("vm_polling_enabled"), True):
        argv += ["--disable-vm-polling"]
    if not _clean_bool(cfg.get("gpu_polling_enabled"), True):
        argv += ["--disable-gpu-polling"]
    if _clean_bool(cfg.get("allow_host_cmds"), False):
        argv += ["--allow-host-cmds"]
    if _clean_bool(cfg.get("host_cmd_use_sudo"), False):
        argv += ["--host-cmd-use-sudo"]
    if _clean_str(cfg.get("shutdown_cmd"), ""):
        argv += ["--shutdown-cmd", _clean_str(cfg.get("shutdown_cmd"), "")]
    if _clean_str(cfg.get("restart_cmd"), ""):
        argv += ["--restart-cmd", _clean_str(cfg.get("restart_cmd"), "")]
    return argv

def cfg_from_form(form: Any) -> Dict[str, Any]:
    def _has_checkbox(name: str) -> bool:
        try:
            return name in form
        except Exception:
            return form.get(name) is not None

    return normalize_cfg(
        {
            "serial_port": form.get("serial_port"),
            "baud": form.get("baud"),
            "interval": form.get("interval"),
            "timeout": form.get("timeout"),
            "iface": form.get("iface"),
            "docker_socket": form.get("docker_socket"),
            "docker_polling_enabled": _has_checkbox("docker_polling_enabled"),
            "docker_interval": form.get("docker_interval"),
            "virsh_binary": form.get("virsh_binary"),
            "virsh_uri": form.get("virsh_uri"),
            "vm_polling_enabled": _has_checkbox("vm_polling_enabled"),
            "vm_interval": form.get("vm_interval"),
            "gpu_polling_enabled": _has_checkbox("gpu_polling_enabled"),
            "disk_device": form.get("disk_device"),
            "disk_temp_device": form.get("disk_temp_device"),
            "cpu_temp_sensor": form.get("cpu_temp_sensor"),
            "fan_sensor": form.get("fan_sensor"),
            "allow_host_cmds": _has_checkbox("allow_host_cmds"),
            "host_cmd_use_sudo": _has_checkbox("host_cmd_use_sudo"),
            "shutdown_cmd": form.get("shutdown_cmd"),
            "restart_cmd": form.get("restart_cmd"),
            "webui_auth_enabled": _has_checkbox("webui_auth_enabled"),
        }
    )

__all__ = [
    "_clean_bool",
    "_clean_float",
    "_clean_int",
    "_clean_str",
    "atomic_write_json",
    "cfg_from_form",
    "cfg_to_agent_args",
    "default_webui_config_path",
    "ensure_webui_session_secret",
    "load_cfg",
    "normalize_cfg",
    "validate_cfg",
    "webui_default_cfg",
]

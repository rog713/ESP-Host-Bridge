from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any, Dict, Iterable

from .integrations import (
    CleanerSet,
    get_registered_config_fields,
    get_registered_secret_config_field_names,
    integration_cfg_to_agent_args,
    validate_integration_cfg,
)

REDACTED_SECRET_TEXT = "..."
_BUILTIN_SECRET_FIELDS = frozenset({"webui_password_hash", "webui_session_secret"})


def default_webui_config_path() -> Path:
    env = os.environ.get("WEBUI_CONFIG", "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().with_name("config.json")

def webui_default_cfg() -> Dict[str, Any]:
    cfg = {
        "serial_port": "",
        "baud": 115200,
        "interval": 1.0,
        "timeout": 2.0,
        "allow_host_cmds": False,
        "host_cmd_use_sudo": False,
        "shutdown_cmd": "",
        "restart_cmd": "",
        "webui_auth_enabled": False,
        "webui_password_hash": "",
        "webui_session_secret": "",
    }
    for field in get_registered_config_fields():
        cfg[field.name] = field.default
    return cfg


def _clean_value_by_kind(kind: str, value: Any, default: Any) -> Any:
    if kind == "bool":
        return _clean_bool(value, bool(default))
    if kind == "int":
        return _clean_int(value, int(default))
    if kind == "float":
        return _clean_float(value, float(default))
    return _clean_str(value, str(default))


def _cleaners() -> CleanerSet:
    return CleanerSet(
        clean_str=_clean_str,
        clean_int=_clean_int,
        clean_float=_clean_float,
        clean_bool=_clean_bool,
    )

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
    cfg["allow_host_cmds"] = _clean_bool(raw.get("allow_host_cmds", cfg["allow_host_cmds"]), cfg["allow_host_cmds"])
    cfg["host_cmd_use_sudo"] = _clean_bool(raw.get("host_cmd_use_sudo", cfg["host_cmd_use_sudo"]), cfg["host_cmd_use_sudo"])
    cfg["shutdown_cmd"] = _clean_str(raw.get("shutdown_cmd", cfg["shutdown_cmd"]), cfg["shutdown_cmd"])
    cfg["restart_cmd"] = _clean_str(raw.get("restart_cmd", cfg["restart_cmd"]), cfg["restart_cmd"])
    cfg["webui_auth_enabled"] = _clean_bool(raw.get("webui_auth_enabled", cfg["webui_auth_enabled"]), cfg["webui_auth_enabled"])
    cfg["webui_password_hash"] = _clean_str(raw.get("webui_password_hash", cfg["webui_password_hash"]), cfg["webui_password_hash"])
    cfg["webui_session_secret"] = _clean_str(raw.get("webui_session_secret", cfg["webui_session_secret"]), cfg["webui_session_secret"])
    for field in get_registered_config_fields():
        cfg[field.name] = _clean_value_by_kind(field.kind, raw.get(field.name, cfg[field.name]), cfg[field.name])
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
    errors = validate_integration_cfg(cfg, _cleaners())
    if errors:
        return False, errors[0]
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


def _masked_secret_if_present(value: Any, mask: str = REDACTED_SECRET_TEXT) -> str:
    return mask if _clean_str(value, "") else ""


def secret_placeholder_text(has_secret: bool, mask: str = REDACTED_SECRET_TEXT) -> str:
    return mask if has_secret else ""


def _normalized_secret_keep_tokens(mask: str = REDACTED_SECRET_TEXT) -> set[str]:
    base = {
        "",
        mask,
        "...",
        "xxx",
        "xxxxx",
        "***",
        "*****",
        "•••",
        "••••",
    }
    return {str(token or "").strip().lower() for token in base}


def preserve_secret_fields(
    candidate_cfg: Dict[str, Any],
    existing_cfg: Dict[str, Any],
    *,
    mask: str = REDACTED_SECRET_TEXT,
    include_builtin: bool = False,
) -> Dict[str, Any]:
    updated = dict(candidate_cfg)
    keep_tokens = _normalized_secret_keep_tokens(mask)
    names: list[str] = list(get_registered_secret_config_field_names())
    if include_builtin:
        names.extend(sorted(_BUILTIN_SECRET_FIELDS))
    for name in names:
        existing_value = _clean_str(existing_cfg.get(name), "")
        if not existing_value:
            continue
        submitted_value = _clean_str(updated.get(name), "")
        if submitted_value.strip().lower() in keep_tokens:
            updated[name] = existing_value
    return updated


def redact_cfg(cfg: Dict[str, Any], mask: str = REDACTED_SECRET_TEXT) -> Dict[str, Any]:
    redacted = normalize_cfg(cfg)
    for name in _BUILTIN_SECRET_FIELDS:
        if name in redacted:
            redacted[name] = _masked_secret_if_present(redacted.get(name), mask)
    for name in get_registered_secret_config_field_names():
        if name in redacted:
            redacted[name] = _masked_secret_if_present(redacted.get(name), mask)
    return redacted

def cfg_to_agent_args(cfg: Dict[str, Any]) -> list[str]:
    argv = [
        "--baud",
        str(_clean_int(cfg.get("baud"), 115200)),
        "--interval",
        str(_clean_float(cfg.get("interval"), 1.0)),
        "--timeout",
        str(_clean_float(cfg.get("timeout"), 2.0)),
    ]
    for key, flag in [
        ("serial_port", "--serial-port"),
    ]:
        val = _clean_str(cfg.get(key), "")
        if val:
            argv += [flag, val]
    argv += integration_cfg_to_agent_args(cfg, _cleaners())
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
            "allow_host_cmds": _has_checkbox("allow_host_cmds"),
            "host_cmd_use_sudo": _has_checkbox("host_cmd_use_sudo"),
            "shutdown_cmd": form.get("shutdown_cmd"),
            "restart_cmd": form.get("restart_cmd"),
            "webui_auth_enabled": _has_checkbox("webui_auth_enabled"),
            **{
                field.name: (_has_checkbox(field.name) if field.checkbox else form.get(field.name))
                for field in get_registered_config_fields()
            },
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
    "preserve_secret_fields",
    "redact_cfg",
    "REDACTED_SECRET_TEXT",
    "secret_placeholder_text",
    "validate_cfg",
    "webui_default_cfg",
]

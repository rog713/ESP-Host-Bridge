from __future__ import annotations

import http.client
import logging
import socket
import urllib.parse
from typing import Any, Dict

from ..metrics import (
    docker_summary_counts,
    get_docker_containers_from_engine,
    get_home_assistant_addons,
    normalize_docker_data,
)
from .base import CleanerSet, CommandContext, CommandSpec, ConfigFieldSpec, IntegrationSpec, PollContext

DOCKER_WARN_INTERVAL_SECONDS = 30.0
DOCKER_DEFAULT_COUNTS = {"running": 0, "stopped": 0, "unhealthy": 0}

DOCKER_CONFIG_FIELDS = (
    ConfigFieldSpec(
        "docker_polling_enabled",
        "bool",
        True,
        checkbox=True,
        label="Enable Docker Polling",
        hint="Turn Docker polling on or off without deleting the socket path.",
        section_key="docker",
        homeassistant_label="Enable Add-on Polling",
        homeassistant_hint="Turn add-on polling on or off without changing the Home Assistant Supervisor data source.",
    ),
    ConfigFieldSpec(
        "docker_socket",
        "str",
        "/var/run/docker.sock",
        cli_flag="--docker-socket",
        label="Docker Socket",
        hint="Only used when Docker polling is enabled.",
        section_key="docker",
        homeassistant_label="Add-on Source",
        homeassistant_hint="Home Assistant app mode reads add-ons from the Supervisor API. This value is ignored.",
        homeassistant_value="Home Assistant Supervisor API",
        readonly_when_homeassistant=True,
    ),
    ConfigFieldSpec(
        "docker_interval",
        "float",
        2.0,
        cli_flag="--docker-interval",
        label="Docker Poll Interval (s)",
        hint="Set to <code>0</code> to disable Docker polling entirely. <code>2</code> is a good default on low-power hosts.",
        section_key="docker",
        input_step="0.1",
        homeassistant_label="Add-on Poll Interval (s)",
        homeassistant_hint="How often the Supervisor add-on list is refreshed. Set to <code>0</code> to disable add-on polling.",
    ),
)

DOCKER_COMMANDS = (
    CommandSpec(
        command_id="docker_start",
        owner_id="docker",
        patterns=("docker_start:",),
        match_kind="prefix",
        label="Start Docker Container",
    ),
    CommandSpec(
        command_id="docker_stop",
        owner_id="docker",
        patterns=("docker_stop:",),
        match_kind="prefix",
        label="Stop Docker Container",
        destructive=True,
        confirmation_text="Stop the selected Docker container",
    ),
)


def _sanitize_compact_token(value: Any, fallback: str = "") -> str:
    text = str(value or fallback).strip()
    if not text:
        text = fallback
    return text.replace(",", "_").replace(";", "_").replace("|", "_")


def compact_containers(docker_data: list[dict[str, Any]], max_items: int = 10) -> str:
    out: list[str] = []
    for container in docker_data[:max_items]:
        if not isinstance(container, dict):
            continue
        raw_name = container.get("name") or container.get("Names") or "container"
        if isinstance(raw_name, list):
            name = str(raw_name[0] if raw_name else "container")
        else:
            name = str(raw_name)
        name = name.lstrip("/").replace(",", "_").replace(";", "_")
        if len(name) > 24:
            name = name[:24]
        status_raw = str(container.get("status") or container.get("State") or "").lower()
        state = "up" if any(token in status_raw for token in ["running", "up", "healthy"]) else "down"
        out.append(f"{name}|{state}")
    return ";".join(out)


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, unix_socket_path: str, timeout_s: float):
        super().__init__("localhost", timeout=timeout_s)
        self.unix_socket_path = unix_socket_path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.unix_socket_path)


def _cache(state: Any) -> Dict[str, Any]:
    integration_cache = getattr(state, "integration_cache", None)
    if not isinstance(integration_cache, dict):
        integration_cache = {}
        setattr(state, "integration_cache", integration_cache)
    cached = integration_cache.get("docker")
    if not isinstance(cached, dict):
        cached = {
            "items": [],
            "counts": dict(DOCKER_DEFAULT_COUNTS),
            "last_refresh_ts": 0.0,
            "last_success_ts": 0.0,
            "last_warn_ts": 0.0,
            "last_error": "",
            "last_error_ts": 0.0,
            "api_ok": None,
            "available": None,
        }
        integration_cache["docker"] = cached
    return cached


def validate_cfg(cfg: Dict[str, Any], clean: CleanerSet) -> list[str]:
    errors: list[str] = []
    interval = clean.clean_float(cfg.get("docker_interval"), 0.0)
    enabled = clean.clean_bool(cfg.get("docker_polling_enabled"), True)
    if interval < 0.0:
        errors.append("docker_interval must be >= 0")
    if enabled and interval > 0.0 and not clean.clean_str(cfg.get("docker_socket"), ""):
        errors.append("docker_socket is required when docker polling is enabled")
    return errors


def cfg_to_agent_args(cfg: Dict[str, Any], clean: CleanerSet) -> list[str]:
    argv = [
        "--docker-socket",
        clean.clean_str(cfg.get("docker_socket"), "/var/run/docker.sock"),
        "--docker-interval",
        str(clean.clean_float(cfg.get("docker_interval"), 2.0)),
    ]
    if not clean.clean_bool(cfg.get("docker_polling_enabled"), True):
        argv.append("--disable-docker-polling")
    return argv


def poll(ctx: PollContext) -> Dict[str, Any]:
    cache = _cache(ctx.state)
    enabled = not bool(getattr(ctx.args, "disable_docker_polling", False))
    interval = max(0.0, float(getattr(ctx.args, "docker_interval", 2.0) or 0.0))

    if enabled and interval > 0.0 and (
        not cache.get("last_refresh_ts") or (ctx.now - float(cache.get("last_refresh_ts") or 0.0)) >= interval
    ):
        try:
            if ctx.homeassistant_mode:
                items = get_home_assistant_addons(timeout=ctx.args.timeout)
            else:
                items = get_docker_containers_from_engine(ctx.args.docker_socket, timeout=ctx.args.timeout)
            cache["api_ok"] = True if ctx.homeassistant_mode else None
            cache["available"] = True
            cache["last_success_ts"] = ctx.now
            cache["last_error"] = ""
            cache["last_error_ts"] = 0.0
        except Exception as exc:
            items = []
            cache["api_ok"] = False if ctx.homeassistant_mode else None
            cache["available"] = False
            cache["last_error"] = str(exc).strip()[:200]
            cache["last_error_ts"] = ctx.now
            last_warn_ts = float(cache.get("last_warn_ts") or 0.0)
            if (ctx.now - last_warn_ts) >= DOCKER_WARN_INTERVAL_SECONDS:
                if ctx.homeassistant_mode:
                    logging.warning("Home Assistant add-on API unavailable; continuing without add-on data (%s)", exc)
                else:
                    logging.warning(
                        "Docker API unavailable via %s; continuing without docker data (%s)",
                        ctx.args.docker_socket,
                        exc,
                    )
                cache["last_warn_ts"] = ctx.now
        items = normalize_docker_data(items)
        cache["items"] = items
        cache["counts"] = docker_summary_counts(items)
        cache["last_refresh_ts"] = ctx.now

    if enabled:
        items = list(cache.get("items") or [])
        counts = dict(cache.get("counts") or DOCKER_DEFAULT_COUNTS)
    else:
        items = []
        counts = dict(DOCKER_DEFAULT_COUNTS)
        if ctx.homeassistant_mode:
            cache["api_ok"] = None
        cache["available"] = None

    last_refresh_ts = float(cache.get("last_refresh_ts") or 0.0)
    last_success_ts = float(cache.get("last_success_ts") or 0.0)
    last_error_ts = float(cache.get("last_error_ts") or 0.0)
    last_error = str(cache.get("last_error") or "").strip()
    return {
        "enabled": enabled,
        "items": items,
        "counts": counts,
        "compact": compact_containers(items),
        "api_ok": cache.get("api_ok"),
        "health": {
            "integration_id": "docker",
            "enabled": enabled,
            "available": cache.get("available"),
            "source": "home_assistant_supervisor" if ctx.homeassistant_mode else "docker_socket",
            "last_refresh_ts": last_refresh_ts or None,
            "last_success_ts": last_success_ts or None,
            "last_error": last_error or None,
            "last_error_ts": last_error_ts or None,
            "commands": [spec.command_id for spec in DOCKER_COMMANDS],
            "api_ok": cache.get("api_ok"),
        },
    }


def _execute_docker_command(cmd: str, socket_path: str, timeout: float) -> bool:
    cmd_s = (cmd or "").strip()
    cmd_l = cmd_s.lower()
    if cmd_l.startswith("docker_start:"):
        action = "start"
        target = cmd_s.split(":", 1)[1].strip()
    elif cmd_l.startswith("docker_stop:"):
        action = "stop"
        target = cmd_s.split(":", 1)[1].strip()
    else:
        return False

    if not target:
        logging.warning("ignoring docker command with empty target (CMD=%s)", cmd_s)
        return True

    encoded = urllib.parse.quote(target, safe="")
    path = f"/containers/{encoded}/{action}" + ("?t=10" if action == "stop" else "")
    try:
        conn = UnixHTTPConnection(socket_path, timeout)
        conn.request("POST", path)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        if resp.status in (204, 304):
            logging.info("docker %s requested for %s (HTTP %s)", action, target, resp.status)
        else:
            logging.warning(
                "docker %s failed for %s via %s (HTTP %s: %r)",
                action,
                target,
                socket_path,
                resp.status,
                body[:200],
            )
    except Exception as exc:
        logging.warning("docker %s failed for %s via %s (%s)", action, target, socket_path, exc)
    return True


def _execute_home_assistant_addon_command(cmd: str, ctx: CommandContext) -> bool:
    cmd_s = (cmd or "").strip()
    cmd_l = cmd_s.lower()
    if cmd_l.startswith("docker_start:"):
        action = "start"
        target = cmd_s.split(":", 1)[1].strip()
    elif cmd_l.startswith("docker_stop:"):
        action = "stop"
        target = cmd_s.split(":", 1)[1].strip()
    else:
        return False
    if not target:
        logging.warning("ignoring add-on command with empty target (CMD=%s)", cmd_s)
        return True
    addons = get_home_assistant_addons(ctx.timeout)
    target_l = target.lower()
    match = next(
        (
            row
            for row in addons
            if str(row.get("name") or "") == target
            or str(row.get("slug") or "") == target
            or str(row.get("name") or "").lower().startswith(target_l)
            or str(row.get("slug") or "").lower().startswith(target_l)
        ),
        None,
    )
    if not match:
        logging.warning("home assistant add-on command target not found (%s)", target)
        return True
    slug = str(match.get("slug") or "").strip()
    if not slug:
        logging.warning("home assistant add-on slug missing for %s", target)
        return True
    try:
        if ctx.supervisor_request_json is None:
            raise RuntimeError("Supervisor API helper unavailable")
        ctx.supervisor_request_json(
            f"/addons/{urllib.parse.quote(slug, safe='')}/{action}",
            timeout=ctx.timeout,
            method="POST",
            payload={},
        )
        logging.info("home assistant add-on %s requested for %s", action, target)
    except Exception as exc:
        logging.warning("home assistant add-on %s failed for %s (%s)", action, target, exc)
    return True


def handle_command(cmd: str, ctx: CommandContext) -> bool:
    if ctx.homeassistant_mode:
        handled = _execute_home_assistant_addon_command(cmd, ctx)
        if handled:
            return True
    return _execute_docker_command(cmd, str(getattr(ctx.args, "docker_socket", "/var/run/docker.sock")), ctx.timeout)


DOCKER_INTEGRATION = IntegrationSpec(
    integration_id="docker",
    title="Docker",
    homeassistant_title="Add-ons",
    section_key="docker",
    icon_class="mdi-docker",
    config_fields=DOCKER_CONFIG_FIELDS,
    commands=DOCKER_COMMANDS,
    validate_cfg=validate_cfg,
    cfg_to_agent_args=cfg_to_agent_args,
    poll=poll,
    handle_command=handle_command,
)

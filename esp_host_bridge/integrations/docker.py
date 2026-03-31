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
from .base import (
    CleanerSet,
    CommandContext,
    CommandSpec,
    ConfigFieldSpec,
    DashboardCardSpec,
    DashboardDetailSpec,
    DashboardGroupSpec,
    IntegrationSpec,
    PollContext,
    PreviewCardSpec,
    PreviewPageSpec,
)

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
        preview_target="docker",
        preview_action_id="start",
        preview_label="Start",
        preview_button_class="start",
        optimistic_patch={"state": "up"},
    ),
    CommandSpec(
        command_id="docker_stop",
        owner_id="docker",
        patterns=("docker_stop:",),
        match_kind="prefix",
        label="Stop Docker Container",
        destructive=True,
        confirmation_text="Stop the selected Docker container",
        preview_target="docker",
        preview_action_id="stop",
        preview_label="Stop",
        preview_button_class="stop",
        optimistic_patch={"state": "down"},
    ),
)

DOCKER_DASHBOARD_GROUPS = (
    DashboardGroupSpec(
        group_id="docker_summary",
        title="Docker",
        homeassistant_title="Add-ons",
        icon_class="mdi-docker",
        cards=(
            DashboardCardSpec(
                card_id="DockerCounts",
                label="Docker Summary",
                homeassistant_label="Add-on Summary",
                render_kind="docker_counts",
                subtext="Run / Stop / Unhealthy",
                homeassistant_subtext="Started / Stopped / Issue",
                severity_kind="docker_counts",
            ),
        ),
    ),
)

DOCKER_DASHBOARD_DETAILS = (
    DashboardDetailSpec(
        detail_id="docker_list",
        title="Containers",
        homeassistant_title="Add-ons",
        render_kind="status_list",
        waiting_text="Waiting for Docker data...",
        homeassistant_waiting_text="Waiting for add-on data...",
        show_all_text="Show all containers",
        homeassistant_show_all_text="Show all add-ons",
    ),
)

DOCKER_PREVIEW_CARDS = (
    PreviewCardSpec(
        card_id="DOCKER",
        label="Docker",
        homeassistant_label="Add-ons",
        icon_class="mdi-docker",
        homeassistant_icon_class="mdi-puzzle-outline",
        render_kind="docker_preview_counts",
        subtext="Run / Stop / Unh",
        homeassistant_subtext="On / Off / Issue",
    ),
)

DOCKER_PREVIEW_PAGES = (
    PreviewPageSpec(
        page_id="docker",
        dom_id="espPageDocker",
        preview_order=1,
        title="Docker",
        footer="Docker",
        tab_label="Docker",
        tab_icon_class="mdi-docker",
        indicator_count=1,
        indicator_index=1,
        top_pills="docker",
        nav_down="home",
        home_button_position="tl",
        home_button_title="Docker",
        home_button_icon_class="mdi-docker",
        modal_target="docker",
        modal_title="Docker",
        modal_subtitle="Container control",
        modal_icon_class="mdi-docker",
        empty_title="No Docker Data",
        empty_subtitle="No containers in the latest payload",
        token_missing_title="Token Missing",
        token_missing_subtitle="Supervisor token is not available to the app",
        api_error_title="Add-on API Error",
        api_error_subtitle="Check app logs for Supervisor API errors",
        homeassistant_title="Add-ons",
        homeassistant_footer="Add-ons",
        homeassistant_tab_label="Add-ons",
        homeassistant_tab_icon_class="mdi-puzzle-outline",
        homeassistant_home_button_title="Add-ons",
        homeassistant_home_button_icon_class="mdi-puzzle-outline",
        homeassistant_modal_title="Add-ons",
        homeassistant_modal_subtitle="Home Assistant app control",
        homeassistant_modal_icon_class="mdi-puzzle-outline",
        homeassistant_empty_title="No Add-ons",
        homeassistant_empty_subtitle="No add-ons in the latest payload",
        homeassistant_token_missing_title="Token Missing",
        homeassistant_token_missing_subtitle="Supervisor token is not available to the app",
        homeassistant_api_error_title="Add-on API Error",
        homeassistant_api_error_subtitle="Check app logs for Supervisor API errors",
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


def parse_compact_containers(value: Any) -> list[dict[str, str]]:
    raw = str(value or "").strip()
    if not raw:
        return []
    items = (
        raw.split(";")
    )
    rows: list[dict[str, str]] = []
    for item in items:
        token = str(item or "").strip()
        if not token:
            continue
        parts = token.split("|")
        name = str(parts[0] or "").strip()
        state = str(parts[1] if len(parts) > 1 else "--").strip().lower() or "--"
        if not name:
            continue
        rows.append(
            {
                "name": name,
                "state_text": state,
                "state_class": "up" if state == "up" else "down",
            }
        )
    rows.sort(key=lambda row: (0 if row["state_class"] == "up" else 1, row["name"].lower()))
    return rows


def detail_payloads(last_metrics: Dict[str, Any], homeassistant_mode: bool) -> Dict[str, Dict[str, Any]]:
    items = parse_compact_containers(last_metrics.get("DOCKER"))
    token = int(float(last_metrics.get("HATOKEN") or 0)) if homeassistant_mode else 1
    api = int(float(last_metrics.get("HADOCKAPI") or -1)) if homeassistant_mode else 1
    if not items and homeassistant_mode and token == 0:
        hint = "Supervisor token missing in app container"
    elif not items and homeassistant_mode and api == 0:
        hint = "Add-on API unavailable; check logs"
    elif not items:
        hint = "No add-ons in the latest payload" if homeassistant_mode else "No containers in the latest payload"
    else:
        extra = max(0, len(items) - 5)
        if extra:
            hint = (
                f"{len(items)} add-ons detected, showing 5"
                if homeassistant_mode
                else f"{len(items)} containers detected, showing 5"
            )
        elif len(items) == 1:
            hint = "1 add-on detected" if homeassistant_mode else "1 container detected"
        else:
            hint = f"{len(items)} add-ons detected" if homeassistant_mode else f"{len(items)} containers detected"
    return {
        "docker_list": {
            "kind": "status_list",
            "items": items,
            "hint": hint,
        }
    }


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
    sort_order=1,
    action_group_title="Docker Controls",
    homeassistant_action_group_title="Add-on Controls",
    config_fields=DOCKER_CONFIG_FIELDS,
    commands=DOCKER_COMMANDS,
    dashboard_groups=DOCKER_DASHBOARD_GROUPS,
    dashboard_details=DOCKER_DASHBOARD_DETAILS,
    preview_cards=DOCKER_PREVIEW_CARDS,
    preview_pages=DOCKER_PREVIEW_PAGES,
    validate_cfg=validate_cfg,
    cfg_to_agent_args=cfg_to_agent_args,
    poll=poll,
    handle_command=handle_command,
    detail_payloads=detail_payloads,
)

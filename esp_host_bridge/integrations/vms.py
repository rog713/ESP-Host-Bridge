from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ..metrics import (
    _run_command_capture,
    _virsh_uri_candidates,
    get_home_assistant_integrations,
    get_virtual_machines_from_virsh,
    vm_summary_counts,
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

VMS_WARN_INTERVAL_SECONDS = 30.0
VMS_DEFAULT_COUNTS = {"running": 0, "stopped": 0, "paused": 0, "other": 0}

VMS_CONFIG_FIELDS = (
    ConfigFieldSpec(
        "vm_polling_enabled",
        "bool",
        True,
        checkbox=True,
        label="Enable VM Polling",
        hint="Turn VM polling on or off without deleting the <code>virsh</code> settings.",
        section_key="virtual_machines",
        homeassistant_label="Enable Integration Polling",
        homeassistant_hint="Turn integration polling on or off without changing the Home Assistant Core query settings.",
    ),
    ConfigFieldSpec(
        "virsh_binary",
        "str",
        "virsh",
        cli_flag="--virsh-binary",
        label="Virsh Binary",
        hint="Path to <code>virsh</code>. Use an absolute path if the Web UI launches outside your shell environment.",
        section_key="virtual_machines",
        homeassistant_label="Integration Source",
        homeassistant_hint="Home Assistant app mode reads integrations from the Home Assistant Core WebSocket API. This value is ignored.",
        homeassistant_value="Home Assistant Core WebSocket API",
        readonly_when_homeassistant=True,
    ),
    ConfigFieldSpec(
        "virsh_uri",
        "str",
        "",
        cli_flag="--virsh-uri",
        label="Virsh URI",
        hint="Optional libvirt connection URI, for example <code>qemu:///system</code>.",
        section_key="virtual_machines",
        homeassistant_label="Integration Query",
        homeassistant_hint="Home Assistant app mode groups entity-registry entries by integration domain. This value is ignored.",
        homeassistant_value="config/entity_registry/list_for_display",
        readonly_when_homeassistant=True,
    ),
    ConfigFieldSpec(
        "vm_interval",
        "float",
        5.0,
        cli_flag="--vm-interval",
        label="VM Poll Interval (s)",
        hint="How often VM data is refreshed. <code>5</code> is a good default for low-power hosts.",
        section_key="virtual_machines",
        input_step="0.1",
        homeassistant_label="Integration Poll Interval (s)",
        homeassistant_hint="How often the Home Assistant integration registry is refreshed. <code>5</code> is a good default.",
    ),
)

VMS_COMMANDS = (
    CommandSpec(
        command_id="vm_start",
        owner_id="vms",
        patterns=("vm_start:",),
        match_kind="prefix",
        label="Start Virtual Machine",
        preview_target="vms",
        preview_action_id="start",
        preview_label="Start",
        preview_button_class="start",
        preview_homeassistant_enabled=False,
        optimistic_patch={"stateKey": "running", "stateLabel": "Running"},
    ),
    CommandSpec(
        command_id="vm_stop",
        owner_id="vms",
        patterns=("vm_stop:",),
        match_kind="prefix",
        label="Stop Virtual Machine",
        destructive=True,
        confirmation_text="Shut down the selected virtual machine",
        preview_target="vms",
        preview_action_id="stop",
        preview_label="Stop",
        preview_button_class="stop",
        preview_homeassistant_enabled=False,
        optimistic_patch={"stateKey": "stopped", "stateLabel": "Stopped"},
    ),
    CommandSpec(
        command_id="vm_force_stop",
        owner_id="vms",
        patterns=("vm_force_stop:",),
        match_kind="prefix",
        label="Force Stop Virtual Machine",
        destructive=True,
        confirmation_text="Force stop the selected virtual machine",
    ),
    CommandSpec(
        command_id="vm_restart",
        owner_id="vms",
        patterns=("vm_restart:",),
        match_kind="prefix",
        label="Restart Virtual Machine",
        destructive=True,
        confirmation_text="Restart the selected virtual machine",
        preview_target="vms",
        preview_action_id="restart",
        preview_label="Restart",
        preview_button_class="restart",
        preview_homeassistant_enabled=False,
        optimistic_patch={"stateKey": "running", "stateLabel": "Running"},
    ),
)

VMS_DASHBOARD_GROUPS = (
    DashboardGroupSpec(
        group_id="vms_summary",
        title="Virtual Machines",
        homeassistant_title="Integrations",
        icon_class="mdi-monitor-multiple",
        cards=(
            DashboardCardSpec(
                card_id="VmCounts",
                label="VM Summary",
                homeassistant_label="Integration Summary",
                render_kind="vm_counts",
                subtext="Run / Pause / Stop / Other",
                homeassistant_subtext="Loaded integrations",
                severity_kind="always_ok",
            ),
        ),
    ),
)

VMS_DASHBOARD_DETAILS = (
    DashboardDetailSpec(
        detail_id="vm_list",
        title="Virtual Machines",
        homeassistant_title="Integrations",
        render_kind="status_list",
        waiting_text="Waiting for VM data...",
        homeassistant_waiting_text="Waiting for integration data...",
        show_all_text="Show all virtual machines",
        homeassistant_show_all_text="Show all integrations",
    ),
)

VMS_PREVIEW_CARDS = (
    PreviewCardSpec(
        card_id="VMS",
        label="VMs",
        homeassistant_label="Integrations",
        icon_class="mdi-monitor-multiple",
        homeassistant_icon_class="mdi-devices",
        render_kind="vm_preview_counts",
        subtext="Run / Pause / Stop",
        homeassistant_subtext="Loaded",
    ),
)

VMS_PREVIEW_PAGES = (
    PreviewPageSpec(
        page_id="vms",
        dom_id="espPageVms",
        preview_order=12,
        render_kind="workload_list",
        title="VMS",
        footer="VMS",
        render_data={
            "rows_id": "espVmsRows",
            "empty_id": "espVmsEmpty",
        },
        tab_label="VMS",
        tab_icon_class="mdi-monitor-multiple",
        indicator_count=1,
        indicator_index=1,
        top_pills="vms",
        nav_down="home",
        home_button_position="tr",
        home_button_title="VMS",
        home_button_icon_class="mdi-monitor-multiple",
        modal_target="vms",
        modal_title="VMS",
        modal_subtitle="Virtual machine control",
        modal_icon_class="mdi-monitor-multiple",
        empty_title="No VM Data",
        empty_subtitle="No virtual machines in the latest payload",
        token_missing_title="Token Missing",
        token_missing_subtitle="Supervisor token is not available to the app",
        api_error_title="Integration API Error",
        api_error_subtitle="Check app logs for Core WebSocket errors",
        homeassistant_title="INTEGRATIONS",
        homeassistant_footer="Integrations",
        homeassistant_tab_label="Integrations",
        homeassistant_tab_icon_class="mdi-devices",
        homeassistant_home_button_title="Integrations",
        homeassistant_home_button_icon_class="mdi-devices",
        homeassistant_modal_title="Integrations",
        homeassistant_modal_subtitle="Loaded integration overview",
        homeassistant_modal_icon_class="mdi-devices",
        homeassistant_empty_title="No Integrations",
        homeassistant_empty_subtitle="No integrations in the latest payload",
        homeassistant_token_missing_title="Token Missing",
        homeassistant_token_missing_subtitle="Supervisor token is not available to the app",
        homeassistant_api_error_title="Integration API Error",
        homeassistant_api_error_subtitle="Check app logs for Core WebSocket errors",
    ),
)


def _clean_token(value: Any, fallback: str = "") -> str:
    text = str(value or fallback).strip()
    if not text:
        text = fallback
    return text.replace(",", "_").replace(";", "_").replace("|", "_")


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


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


def compact_virtual_machines(vm_data: list[dict[str, Any]], max_items: int = 10) -> str:
    out: list[str] = []
    for vm in vm_data[:max_items]:
        if not isinstance(vm, dict):
            continue
        name = _clean_token(vm.get("name"), "vm")
        if len(name) > 24:
            name = name[:24]
        state_key, state_label = classify_vm_state(vm.get("state"))
        vcpus = max(0, _safe_int(vm.get("vcpus"), 0))
        mem_mib = max(0, _safe_int(vm.get("max_mem_mib"), 0))
        out.append(
            f"{name}|{_clean_token(state_key, 'stopped')}|"
            f"{vcpus}|{mem_mib}|{_clean_token(state_label, 'Stopped')}"
        )
    return ";".join(out) if out else "-"


def parse_compact_virtual_machines(value: Any) -> list[dict[str, str]]:
    raw = str(value or "").strip()
    if not raw or raw == "-":
        return []
    rows: list[dict[str, str]] = []
    rank = {"running": 0, "paused": 1, "stopped": 2, "other": 3}
    for item in raw.split(";"):
        token = str(item or "").strip()
        if not token:
            continue
        parts = token.split("|")
        name = str(parts[0] or "").strip()
        state_key = str(parts[1] if len(parts) > 1 else "other").strip().lower() or "other"
        state_label = str(parts[4] if len(parts) > 4 else parts[1] if len(parts) > 1 else "Unknown").strip() or "Unknown"
        if not name:
            continue
        rows.append(
            {
                "name": name,
                "state_text": state_label,
                "state_class": state_key,
            }
        )
    rows.sort(key=lambda row: (rank.get(row["state_class"], 4), row["name"].lower()))
    return rows


def detail_payloads(last_metrics: Dict[str, Any], homeassistant_mode: bool) -> Dict[str, Dict[str, Any]]:
    items = parse_compact_virtual_machines(last_metrics.get("VMS"))
    token = int(float(last_metrics.get("HATOKEN") or 0)) if homeassistant_mode else 1
    api = int(float(last_metrics.get("HAVMSAPI") or -1)) if homeassistant_mode else 1
    if not items and homeassistant_mode and token == 0:
        hint = "Supervisor token missing in app container"
    elif not items and homeassistant_mode and api == 0:
        hint = "Integration registry unavailable; check logs"
    elif not items:
        hint = "No integrations in the latest payload" if homeassistant_mode else "No virtual machines in the latest payload"
    else:
        extra = max(0, len(items) - 5)
        if extra:
            hint = (
                f"{len(items)} integrations detected, showing 5"
                if homeassistant_mode
                else f"{len(items)} virtual machines detected, showing 5"
            )
        elif len(items) == 1:
            hint = "1 integration detected" if homeassistant_mode else "1 virtual machine detected"
        else:
            hint = f"{len(items)} integrations detected" if homeassistant_mode else f"{len(items)} virtual machines detected"
    return {
        "vm_list": {
            "kind": "status_list",
            "items": items,
            "hint": hint,
        }
    }


def _cache(state: Any) -> Dict[str, Any]:
    integration_cache = getattr(state, "integration_cache", None)
    if not isinstance(integration_cache, dict):
        integration_cache = {}
        setattr(state, "integration_cache", integration_cache)
    cached = integration_cache.get("vms")
    if not isinstance(cached, dict):
        cached = {
            "items": [],
            "counts": dict(VMS_DEFAULT_COUNTS),
            "last_refresh_ts": 0.0,
            "last_success_ts": 0.0,
            "last_warn_ts": 0.0,
            "last_error": "",
            "last_error_ts": 0.0,
            "api_ok": None,
            "available": None,
        }
        integration_cache["vms"] = cached
    return cached


def validate_cfg(cfg: Dict[str, Any], clean: CleanerSet) -> list[str]:
    errors: list[str] = []
    if clean.clean_float(cfg.get("vm_interval"), 0.0) < 0.0:
        errors.append("vm_interval must be >= 0")
    return errors


def cfg_to_agent_args(cfg: Dict[str, Any], clean: CleanerSet) -> list[str]:
    argv = [
        "--virsh-binary",
        clean.clean_str(cfg.get("virsh_binary"), "virsh"),
        "--vm-interval",
        str(clean.clean_float(cfg.get("vm_interval"), 5.0)),
    ]
    virsh_uri = clean.clean_str(cfg.get("virsh_uri"), "")
    if virsh_uri:
        argv += ["--virsh-uri", virsh_uri]
    if not clean.clean_bool(cfg.get("vm_polling_enabled"), True):
        argv.append("--disable-vm-polling")
    return argv


def poll(ctx: PollContext) -> Dict[str, Any]:
    cache = _cache(ctx.state)
    enabled = not bool(getattr(ctx.args, "disable_vm_polling", False))
    interval = max(0.0, float(getattr(ctx.args, "vm_interval", 5.0) or 0.0))

    if enabled and interval > 0.0 and (
        not cache.get("last_refresh_ts") or (ctx.now - float(cache.get("last_refresh_ts") or 0.0)) >= interval
    ):
        try:
            if ctx.homeassistant_mode:
                items = get_home_assistant_integrations(timeout=ctx.args.timeout)
            else:
                items = get_virtual_machines_from_virsh(ctx.args.virsh_binary, ctx.args.virsh_uri, timeout=ctx.args.timeout)
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
            if (ctx.now - last_warn_ts) >= VMS_WARN_INTERVAL_SECONDS:
                if ctx.homeassistant_mode:
                    logging.warning("Home Assistant integration registry unavailable; continuing without integration data (%s)", exc)
                else:
                    logging.warning(
                        "virsh unavailable via %s%s; continuing without VM data (%s)",
                        ctx.args.virsh_binary,
                        f" -c {ctx.args.virsh_uri}" if ctx.args.virsh_uri else "",
                        exc,
                    )
                cache["last_warn_ts"] = ctx.now
        cache["items"] = items
        cache["counts"] = vm_summary_counts(items)
        cache["last_refresh_ts"] = ctx.now

    if enabled:
        items = list(cache.get("items") or [])
        counts = dict(cache.get("counts") or VMS_DEFAULT_COUNTS)
    else:
        items = []
        counts = dict(VMS_DEFAULT_COUNTS)
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
        "compact": compact_virtual_machines(items),
        "api_ok": cache.get("api_ok"),
        "health": {
            "integration_id": "vms",
            "enabled": enabled,
            "available": cache.get("available"),
            "source": "home_assistant_core_websocket" if ctx.homeassistant_mode else "virsh",
            "last_refresh_ts": last_refresh_ts or None,
            "last_success_ts": last_success_ts or None,
            "last_error": last_error or None,
            "last_error_ts": last_error_ts or None,
            "commands": [spec.command_id for spec in VMS_COMMANDS],
            "api_ok": cache.get("api_ok"),
        },
    }


def _virsh_cmd(binary: str, uri: Optional[str], *parts: str) -> list[str]:
    argv = [binary]
    if uri:
        argv += ["-c", uri]
    argv += list(parts)
    return argv


def handle_command(cmd: str, ctx: CommandContext) -> bool:
    cmd_s = (cmd or "").strip()
    cmd_l = cmd_s.lower()
    if cmd_l.startswith("vm_start:"):
        action = "start"
        target = cmd_s.split(":", 1)[1].strip()
        parts = ("start", target)
    elif cmd_l.startswith("vm_force_stop:"):
        action = "destroy"
        target = cmd_s.split(":", 1)[1].strip()
        parts = ("destroy", target)
    elif cmd_l.startswith("vm_stop:"):
        action = "shutdown"
        target = cmd_s.split(":", 1)[1].strip()
        parts = ("shutdown", target)
    elif cmd_l.startswith("vm_restart:"):
        action = "reboot"
        target = cmd_s.split(":", 1)[1].strip()
        parts = ("reboot", target)
    else:
        return False

    if not target:
        logging.warning("ignoring VM command with empty target (CMD=%s)", cmd_s)
        return True

    errors: list[str] = []
    virsh_binary = str(getattr(ctx.args, "virsh_binary", "virsh") or "virsh")
    virsh_uri = getattr(ctx.args, "virsh_uri", None)
    for candidate_uri in _virsh_uri_candidates(virsh_uri):
        argv = _virsh_cmd(virsh_binary, candidate_uri, *parts)
        try:
            proc = _run_command_capture(argv, ctx.timeout)
            if proc.returncode == 0:
                logging.info("vm %s requested for %s", action, target)
                return True
            errors.append((proc.stderr or proc.stdout or "").strip()[:200])
        except Exception as exc:
            errors.append(str(exc))
    logging.warning(
        "vm %s failed for %s (%s)",
        action,
        target,
        "; ".join([err for err in errors if err][:3]) or "unknown error",
    )
    return True


VMS_INTEGRATION = IntegrationSpec(
    integration_id="vms",
    title="Virtual Machines",
    homeassistant_title="Integrations",
    section_key="virtual_machines",
    icon_class="mdi-monitor-multiple",
    sort_order=2,
    action_group_title="VM Controls",
    homeassistant_action_group_title="Integration Controls",
    config_fields=VMS_CONFIG_FIELDS,
    commands=VMS_COMMANDS,
    dashboard_groups=VMS_DASHBOARD_GROUPS,
    dashboard_details=VMS_DASHBOARD_DETAILS,
    preview_cards=VMS_PREVIEW_CARDS,
    preview_pages=VMS_PREVIEW_PAGES,
    validate_cfg=validate_cfg,
    cfg_to_agent_args=cfg_to_agent_args,
    poll=poll,
    handle_command=handle_command,
    detail_payloads=detail_payloads,
)

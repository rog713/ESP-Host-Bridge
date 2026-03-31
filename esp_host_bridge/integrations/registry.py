from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Sequence

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
    SummaryChipSpec,
)
from .docker import DOCKER_INTEGRATION
from .host import HOST_INTEGRATION
from .vms import VMS_INTEGRATION

_REGISTERED_INTEGRATIONS: tuple[IntegrationSpec, ...] = (
    HOST_INTEGRATION,
    DOCKER_INTEGRATION,
    VMS_INTEGRATION,
)

_BUILTIN_COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec(
        command_id="host_shutdown",
        owner_id="host",
        patterns=("shutdown",),
        match_kind="exact",
        label="Shutdown Host",
        destructive=True,
        confirmation_text="Shut down the host",
    ),
    CommandSpec(
        command_id="host_restart",
        owner_id="host",
        patterns=("restart", "reboot"),
        match_kind="exact",
        label="Restart Host",
        destructive=True,
        confirmation_text="Restart the host",
    ),
)

_SUMMARY_CHIPS: tuple[SummaryChipSpec, ...] = (
    SummaryChipSpec(chip_id="Agent", label="Agent", render_kind="agent_running"),
    SummaryChipSpec(
        chip_id="Workloads",
        label="Serial / Workloads",
        homeassistant_label="Serial / HA",
        render_kind="workload_summary",
    ),
    SummaryChipSpec(chip_id="Age", label="Last Telemetry", render_kind="metrics_age"),
    SummaryChipSpec(chip_id="Integrations", label="Integrations", render_kind="integration_ready"),
    SummaryChipSpec(
        chip_id="Power",
        label="Host Power",
        render_kind="metric_text",
        metric_key="POWER",
        fallback_text="RUNNING",
    ),
)


def get_registered_integrations() -> tuple[IntegrationSpec, ...]:
    return _REGISTERED_INTEGRATIONS


def get_integration_spec(integration_id: str) -> Optional[IntegrationSpec]:
    target = str(integration_id or "").strip().lower()
    if not target:
        return None
    for integration in _REGISTERED_INTEGRATIONS:
        if integration.integration_id == target:
            return integration
    return None


def integration_dashboard_snapshot(*, homeassistant_mode: bool = False) -> list[Dict[str, Any]]:
    rows: list[Dict[str, Any]] = []
    for integration in _REGISTERED_INTEGRATIONS:
        label = (
            str(integration.homeassistant_title or "").strip()
            if homeassistant_mode and str(integration.homeassistant_title or "").strip()
            else str(integration.title or integration.integration_id).strip()
        )
        action_group_title = (
            str(integration.homeassistant_action_group_title or "").strip()
            if homeassistant_mode and str(integration.homeassistant_action_group_title or "").strip()
            else str(integration.action_group_title or label).strip()
        )
        rows.append(
            {
                "integration_id": integration.integration_id,
                "label": label,
                "icon_class": str(integration.icon_class or "mdi-puzzle-outline"),
                "sort_order": int(integration.sort_order),
                "action_group_title": action_group_title or label,
                "command_count": len(integration.commands) + (
                    len([spec for spec in _BUILTIN_COMMANDS if spec.owner_id == integration.integration_id])
                ),
            }
        )
    rows.sort(key=lambda row: (int(row.get("sort_order", 100)), str(row.get("label", ""))))
    return rows


def _integration_status_class(row: Optional[Dict[str, Any]]) -> str:
    if not isinstance(row, dict) or row.get("enabled") is False:
        return ""
    if row.get("available") is False or row.get("last_error"):
        return "danger"
    if row.get("available") is True:
        return "ok"
    return "warn"


def _integration_status_text(row: Optional[Dict[str, Any]]) -> str:
    if not isinstance(row, dict):
        return "Unknown"
    if row.get("enabled") is False:
        return "Disabled"
    if row.get("available") is False:
        return "Unavailable"
    if row.get("available") is True:
        return "Ready"
    return "Unknown"


def _fmt_age_sec(value: Any) -> str:
    try:
        x = max(0.0, float(value))
    except Exception:
        return "--"
    if x < 2.0:
        return "just now"
    if x < 60.0:
        return f"{round(x)}s ago"
    if x < 3600.0:
        return f"{round(x / 60.0)}m ago"
    return f"{round(x / 3600.0)}h ago"


def _preview_card_snapshot(
    card: PreviewCardSpec, *, homeassistant_mode: bool, sort_order: int, preview_order: int
) -> Dict[str, Any]:
    label = (
        str(card.homeassistant_label or "").strip()
        if homeassistant_mode and str(card.homeassistant_label or "").strip()
        else str(card.label or card.card_id).strip()
    )
    icon_class = (
        str(card.homeassistant_icon_class or "").strip()
        if homeassistant_mode and str(card.homeassistant_icon_class or "").strip()
        else str(card.icon_class or "mdi-chart-box-outline").strip()
    )
    subtext = (
        str(card.homeassistant_subtext or "").strip()
        if homeassistant_mode and str(card.homeassistant_subtext or "").strip()
        else str(card.subtext or "").strip()
    )
    return {
        "card_id": card.card_id,
        "label": label,
        "icon_class": icon_class or "mdi-chart-box-outline",
        "render_kind": str(card.render_kind or "text"),
        "metric_key": str(card.metric_key or "").strip() or None,
        "secondary_metric_key": str(card.secondary_metric_key or "").strip() or None,
        "tertiary_metric_key": str(card.tertiary_metric_key or "").strip() or None,
        "subtext": subtext,
        "sort_order": sort_order,
        "preview_order": preview_order,
    }


def preview_cards_snapshot(*, homeassistant_mode: bool = False) -> list[Dict[str, Any]]:
    rows: list[Dict[str, Any]] = []
    for integration in _REGISTERED_INTEGRATIONS:
        for preview_order, card in enumerate(integration.preview_cards):
            rows.append(
                _preview_card_snapshot(
                    card,
                    homeassistant_mode=homeassistant_mode,
                    sort_order=int(integration.sort_order),
                    preview_order=preview_order,
                )
            )
    rows.sort(key=lambda row: (int(row.get("sort_order", 100)), int(row.get("preview_order", 0)), str(row.get("card_id", ""))))
    return rows


def _preview_page_snapshot(page: PreviewPageSpec, *, homeassistant_mode: bool) -> Dict[str, Any]:
    title = (
        str(page.homeassistant_title or "").strip()
        if homeassistant_mode and str(page.homeassistant_title or "").strip()
        else str(page.title or page.page_id).strip()
    )
    footer = (
        str(page.homeassistant_footer or "").strip()
        if homeassistant_mode and str(page.homeassistant_footer or "").strip()
        else str(page.footer or title).strip()
    )
    tab_label = (
        str(page.homeassistant_tab_label or "").strip()
        if homeassistant_mode and str(page.homeassistant_tab_label or "").strip()
        else str(page.tab_label or "").strip()
    )
    tab_icon_class = (
        str(page.homeassistant_tab_icon_class or "").strip()
        if homeassistant_mode and str(page.homeassistant_tab_icon_class or "").strip()
        else str(page.tab_icon_class or "").strip()
    )
    home_button_title = (
        str(page.homeassistant_home_button_title or "").strip()
        if homeassistant_mode and str(page.homeassistant_home_button_title or "").strip()
        else str(page.home_button_title or "").strip()
    )
    home_button_icon_class = (
        str(page.homeassistant_home_button_icon_class or "").strip()
        if homeassistant_mode and str(page.homeassistant_home_button_icon_class or "").strip()
        else str(page.home_button_icon_class or "").strip()
    )
    modal_title = (
        str(page.homeassistant_modal_title or "").strip()
        if homeassistant_mode and str(page.homeassistant_modal_title or "").strip()
        else str(page.modal_title or "").strip()
    )
    modal_subtitle = (
        str(page.homeassistant_modal_subtitle or "").strip()
        if homeassistant_mode and str(page.homeassistant_modal_subtitle or "").strip()
        else str(page.modal_subtitle or "").strip()
    )
    modal_icon_class = (
        str(page.homeassistant_modal_icon_class or "").strip()
        if homeassistant_mode and str(page.homeassistant_modal_icon_class or "").strip()
        else str(page.modal_icon_class or "").strip()
    )
    empty_title = (
        str(page.homeassistant_empty_title or "").strip()
        if homeassistant_mode and str(page.homeassistant_empty_title or "").strip()
        else str(page.empty_title or "").strip()
    )
    empty_subtitle = (
        str(page.homeassistant_empty_subtitle or "").strip()
        if homeassistant_mode and str(page.homeassistant_empty_subtitle or "").strip()
        else str(page.empty_subtitle or "").strip()
    )
    token_missing_title = (
        str(page.homeassistant_token_missing_title or "").strip()
        if homeassistant_mode and str(page.homeassistant_token_missing_title or "").strip()
        else str(page.token_missing_title or "").strip()
    )
    token_missing_subtitle = (
        str(page.homeassistant_token_missing_subtitle or "").strip()
        if homeassistant_mode and str(page.homeassistant_token_missing_subtitle or "").strip()
        else str(page.token_missing_subtitle or "").strip()
    )
    api_error_title = (
        str(page.homeassistant_api_error_title or "").strip()
        if homeassistant_mode and str(page.homeassistant_api_error_title or "").strip()
        else str(page.api_error_title or "").strip()
    )
    api_error_subtitle = (
        str(page.homeassistant_api_error_subtitle or "").strip()
        if homeassistant_mode and str(page.homeassistant_api_error_subtitle or "").strip()
        else str(page.api_error_subtitle or "").strip()
    )
    return {
        "page_id": page.page_id,
        "dom_id": page.dom_id,
        "preview_order": int(page.preview_order),
        "title": title,
        "footer": footer,
        "tab_label": tab_label or None,
        "tab_icon_class": tab_icon_class or None,
        "indicator_count": int(page.indicator_count),
        "indicator_index": int(page.indicator_index),
        "top_pills": str(page.top_pills or "").strip() or None,
        "nav": {
            key: value
            for key, value in {
                "up": str(page.nav_up or "").strip() or None,
                "down": str(page.nav_down or "").strip() or None,
                "left": str(page.nav_left or "").strip() or None,
                "right": str(page.nav_right or "").strip() or None,
            }.items()
            if value
        },
        "home_button_position": str(page.home_button_position or "").strip() or None,
        "home_button_title": home_button_title or None,
        "home_button_icon_class": home_button_icon_class or None,
        "modal_target": str(page.modal_target or "").strip() or None,
        "modal_title": modal_title or None,
        "modal_subtitle": modal_subtitle or None,
        "modal_icon_class": modal_icon_class or None,
        "empty_title": empty_title or None,
        "empty_subtitle": empty_subtitle or None,
        "token_missing_title": token_missing_title or None,
        "token_missing_subtitle": token_missing_subtitle or None,
        "api_error_title": api_error_title or None,
        "api_error_subtitle": api_error_subtitle or None,
    }


def preview_ui_snapshot(*, homeassistant_mode: bool = False) -> Dict[str, Any]:
    pages: list[Dict[str, Any]] = []
    for integration in _REGISTERED_INTEGRATIONS:
        for page in integration.preview_pages:
            pages.append(_preview_page_snapshot(page, homeassistant_mode=homeassistant_mode))
    pages.sort(key=lambda row: (int(row.get("preview_order", 999)), str(row.get("page_id", ""))))
    page_map = {str(row.get("page_id") or "").strip(): row for row in pages if str(row.get("page_id") or "").strip()}
    tabs = [
        {
            "page_id": row["page_id"],
            "label": str(row.get("tab_label") or row["page_id"]),
            "icon_class": str(row.get("tab_icon_class") or "mdi-application-outline"),
        }
        for row in pages
        if row.get("tab_label")
    ]
    home_buttons = [
        {
            "position": str(row.get("home_button_position") or ""),
            "target_page": row["page_id"],
            "title": str(row.get("home_button_title") or row["page_id"]),
            "icon_class": str(row.get("home_button_icon_class") or "mdi-circle-outline"),
        }
        for row in pages
        if row.get("home_button_position")
    ]
    home_buttons.sort(key=lambda row: row["position"])
    modals = {
        str(row["modal_target"]): {
            "target": str(row["modal_target"]),
            "title": str(row.get("modal_title") or row["page_id"]),
            "subtitle": str(row.get("modal_subtitle") or ""),
            "icon_class": str(row.get("modal_icon_class") or "mdi-puzzle-outline"),
        }
        for row in pages
        if row.get("modal_target")
    }
    return {
        "mode": "homeassistant" if homeassistant_mode else "host",
        "page_order": [str(row["page_id"]) for row in pages],
        "pages": page_map,
        "tabs": tabs,
        "home_buttons": home_buttons,
        "modals": modals,
    }


def summary_bar_snapshot(*, homeassistant_mode: bool = False) -> list[Dict[str, Any]]:
    rows: list[Dict[str, Any]] = []
    for index, chip in enumerate(_SUMMARY_CHIPS):
        label = (
            str(chip.homeassistant_label or "").strip()
            if homeassistant_mode and str(chip.homeassistant_label or "").strip()
            else str(chip.label or chip.chip_id).strip()
        )
        rows.append(
            {
                "chip_id": chip.chip_id,
                "label": label,
                "render_kind": chip.render_kind,
                "metric_key": str(chip.metric_key or "").strip() or None,
                "fallback_text": str(chip.fallback_text or "--"),
                "sort_order": index,
            }
        )
    return rows


def preview_action_groups_snapshot(*, homeassistant_mode: bool = False) -> list[Dict[str, Any]]:
    meta_rows = integration_dashboard_snapshot(homeassistant_mode=homeassistant_mode)
    meta_map = {
        str(row.get("integration_id") or "").strip().lower(): row
        for row in meta_rows
        if str(row.get("integration_id") or "").strip()
    }
    groups: Dict[str, Dict[str, Any]] = {}
    for spec in get_registered_commands():
        target = str(spec.preview_target or "").strip().lower()
        action_id = str(spec.preview_action_id or "").strip()
        if not target or not action_id:
            continue
        if homeassistant_mode and not spec.preview_homeassistant_enabled:
            continue
        meta = meta_map.get(target, {})
        group = groups.setdefault(
            target,
            {
                "target": target,
                "title": str(meta.get("label") or target.title()),
                "icon_class": str(meta.get("icon_class") or "mdi-puzzle-outline"),
                "actions": [],
                "footnote": "",
            },
        )
        if target == "vms" and not homeassistant_mode:
            group["footnote"] = "Hold Stop on the device for force off"
        group["actions"].append(
            {
                "command_id": spec.command_id,
                "action_id": action_id,
                "label": str(spec.preview_label or spec.label or spec.command_id),
                "button_class": str(spec.preview_button_class or action_id),
                "destructive": bool(spec.destructive),
                "confirmation_text": str(spec.confirmation_text or "").strip() or None,
                "optimistic_patch": dict(spec.optimistic_patch or {}),
            }
        )
    return [
        groups[key]
        for key in sorted(
            groups.keys(),
            key=lambda key: (int((meta_map.get(key) or {}).get("sort_order", 99)), key),
        )
    ]


def _dashboard_card_snapshot(card: DashboardCardSpec, *, homeassistant_mode: bool) -> Dict[str, Any]:
    label = (
        str(card.homeassistant_label or "").strip()
        if homeassistant_mode and str(card.homeassistant_label or "").strip()
        else str(card.label or card.card_id).strip()
    )
    subtext = (
        str(card.homeassistant_subtext or "").strip()
        if homeassistant_mode and str(card.homeassistant_subtext or "").strip()
        else str(card.subtext or "").strip()
    )
    return {
        "card_id": card.card_id,
        "label": label,
        "render_kind": str(card.render_kind or "text"),
        "metric_key": str(card.metric_key or "").strip() or None,
        "secondary_metric_key": str(card.secondary_metric_key or "").strip() or None,
        "tertiary_metric_key": str(card.tertiary_metric_key or "").strip() or None,
        "subtext": subtext or None,
        "severity_kind": str(card.severity_kind or "").strip() or None,
        "spark_keys": list(card.spark_keys),
        "spark_color": str(card.spark_color or "").strip() or None,
    }


def _dashboard_group_snapshot(
    integration: IntegrationSpec, group: DashboardGroupSpec, *, homeassistant_mode: bool
) -> Dict[str, Any]:
    title = (
        str(group.homeassistant_title or "").strip()
        if homeassistant_mode and str(group.homeassistant_title or "").strip()
        else str(group.title or integration.title or integration.integration_id).strip()
    )
    return {
        "integration_id": integration.integration_id,
        "group_id": group.group_id,
        "title": title,
        "icon_class": str(group.icon_class or integration.icon_class or "mdi-view-dashboard-outline"),
        "span_class": str(group.span_class or "span6"),
        "cards": [_dashboard_card_snapshot(card, homeassistant_mode=homeassistant_mode) for card in group.cards],
    }


def monitor_dashboard_snapshot(*, homeassistant_mode: bool = False) -> list[Dict[str, Any]]:
    rows: list[Dict[str, Any]] = []
    for integration in _REGISTERED_INTEGRATIONS:
        for group in integration.dashboard_groups:
            rows.append(_dashboard_group_snapshot(integration, group, homeassistant_mode=homeassistant_mode))
    return rows


def _dashboard_detail_snapshot(detail: DashboardDetailSpec, *, homeassistant_mode: bool) -> Dict[str, Any]:
    title = (
        str(detail.homeassistant_title or "").strip()
        if homeassistant_mode and str(detail.homeassistant_title or "").strip()
        else str(detail.title or detail.detail_id).strip()
    )
    waiting_text = (
        str(detail.homeassistant_waiting_text or "").strip()
        if homeassistant_mode and str(detail.homeassistant_waiting_text or "").strip()
        else str(detail.waiting_text or "").strip()
    )
    show_all_text = (
        str(detail.homeassistant_show_all_text or "").strip()
        if homeassistant_mode and str(detail.homeassistant_show_all_text or "").strip()
        else str(detail.show_all_text or "").strip()
    )
    return {
        "detail_id": detail.detail_id,
        "title": title,
        "render_kind": str(detail.render_kind or "list"),
        "waiting_text": waiting_text,
        "show_all_text": show_all_text,
        "span_class": str(detail.span_class or "span6"),
    }


def monitor_detail_snapshot(*, homeassistant_mode: bool = False) -> list[Dict[str, Any]]:
    rows: list[Dict[str, Any]] = []
    for integration in _REGISTERED_INTEGRATIONS:
        for detail in integration.dashboard_details:
            row = _dashboard_detail_snapshot(detail, homeassistant_mode=homeassistant_mode)
            row["integration_id"] = integration.integration_id
            rows.append(row)
    return rows


def monitor_detail_payload_snapshot(
    last_metrics: Dict[str, Any], *, homeassistant_mode: bool = False
) -> Dict[str, Dict[str, Any]]:
    payloads: Dict[str, Dict[str, Any]] = {}
    metrics = last_metrics if isinstance(last_metrics, dict) else {}
    for integration in _REGISTERED_INTEGRATIONS:
        if integration.detail_payloads is None:
            continue
        payloads.update(integration.detail_payloads(metrics, homeassistant_mode))
    return payloads


def get_registered_commands() -> tuple[CommandSpec, ...]:
    out: list[CommandSpec] = list(_BUILTIN_COMMANDS)
    for integration in _REGISTERED_INTEGRATIONS:
        out.extend(integration.commands)
    return tuple(out)


def get_registered_config_fields() -> tuple[ConfigFieldSpec, ...]:
    out: list[ConfigFieldSpec] = []
    for integration in _REGISTERED_INTEGRATIONS:
        out.extend(integration.config_fields)
    return tuple(out)


def get_registered_secret_config_fields() -> tuple[ConfigFieldSpec, ...]:
    return tuple(field for field in get_registered_config_fields() if field.secret)


def get_registered_secret_config_field_names() -> tuple[str, ...]:
    return tuple(field.name for field in get_registered_secret_config_fields())


def validate_integration_cfg(cfg: Dict[str, Any], cleaners: CleanerSet) -> list[str]:
    errors: list[str] = []
    for integration in _REGISTERED_INTEGRATIONS:
        if integration.validate_cfg is None:
            continue
        errors.extend(integration.validate_cfg(cfg, cleaners))
    return errors


def integration_cfg_to_agent_args(cfg: Dict[str, Any], cleaners: CleanerSet) -> list[str]:
    argv: list[str] = []
    for integration in _REGISTERED_INTEGRATIONS:
        if integration.cfg_to_agent_args is None:
            continue
        argv.extend(integration.cfg_to_agent_args(cfg, cleaners))
    return argv


def poll_integrations(ctx: PollContext) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for integration in _REGISTERED_INTEGRATIONS:
        if integration.poll is None:
            continue
        out[integration.integration_id] = integration.poll(ctx)
    return out


def dispatch_integration_command(cmd: str, ctx: CommandContext) -> bool:
    command = match_registered_command(cmd)
    if command is None:
        return False
    for integration in _REGISTERED_INTEGRATIONS:
        if integration.integration_id != command.owner_id:
            continue
        if integration.handle_command is None:
            continue
        if integration.handle_command(cmd, ctx):
            return True
    return False


def _command_matches(spec: CommandSpec, cmd: str) -> bool:
    text = str(cmd or "").strip()
    if not text:
        return False
    text_l = text.lower()
    for pattern in spec.patterns:
        needle = str(pattern or "").strip().lower()
        if not needle:
            continue
        if spec.match_kind == "prefix":
            if text_l.startswith(needle):
                return True
        else:
            if text_l == needle:
                return True
    return False


def match_registered_command(cmd: str) -> Optional[CommandSpec]:
    for spec in get_registered_commands():
        if _command_matches(spec, cmd):
            return spec
    return None


def command_registry_snapshot() -> list[Dict[str, Any]]:
    out: list[Dict[str, Any]] = []
    for spec in get_registered_commands():
        out.append(
            {
                "command_id": spec.command_id,
                "owner_id": spec.owner_id,
                "patterns": list(spec.patterns),
                "match_kind": spec.match_kind,
                "label": spec.label,
                "destructive": spec.destructive,
                "confirmation_text": spec.confirmation_text or None,
            }
        )
    return out


def integration_overview_snapshot(
    integration_health: Dict[str, Dict[str, Any]],
    command_registry: Sequence[Dict[str, Any]],
    *,
    homeassistant_mode: bool = False,
) -> Dict[str, Any]:
    meta_rows = integration_dashboard_snapshot(homeassistant_mode=homeassistant_mode)
    meta_map = {
        str(row.get("integration_id") or "").strip().lower(): row
        for row in meta_rows
        if str(row.get("integration_id") or "").strip()
    }
    health = integration_health if isinstance(integration_health, dict) else {}
    command_rows = list(command_registry or [])

    health_rows = [
        (key, row)
        for key, row in health.items()
        if isinstance(row, dict)
    ]
    health_rows.sort(
        key=lambda item: (
            int((meta_map.get(item[0]) or {}).get("sort_order", 99)),
            item[0],
        )
    )

    enabled_rows = [row for _, row in health_rows if row.get("enabled") is not False]
    ready_count = sum(1 for row in enabled_rows if row.get("available") is True and not row.get("last_error"))
    ready_text = f"{ready_count}/{len(enabled_rows)} ready" if enabled_rows else "--"

    dashboard_cards: list[Dict[str, Any]] = []
    for meta in meta_rows:
        integration_id = str(meta.get("integration_id") or "").strip().lower()
        row = health.get(integration_id) if integration_id else None
        command_count = int(meta.get("command_count", 0)) if str(meta.get("command_count", "")).strip() else 0
        dashboard_cards.append(
            {
                "integration_id": integration_id,
                "icon_class": str(meta.get("icon_class") or "mdi-puzzle-outline"),
                "label": str(meta.get("label") or integration_id or "Integration"),
                "status_class": _integration_status_class(row),
                "status_text": _integration_status_text(row),
                "source_text": f"Source: {str(row.get('source') or '--')}" if isinstance(row, dict) else "Source: --",
                "commands_text": f"{command_count} command{'' if command_count == 1 else 's'}" if command_count >= 0 else "--",
            }
        )

    health_chips: list[Dict[str, Any]] = []
    health_detail_rows: list[Dict[str, Any]] = []
    for integration_id, row in health_rows:
        meta = meta_map.get(integration_id, {})
        label = str(meta.get("label") or integration_id.replace("_", " ").title() or "Integration")
        status_text = _integration_status_text(row)
        status_class = _integration_status_class(row)
        commands = [str(cmd) for cmd in (row.get("commands") or []) if str(cmd).strip()]
        health_chips.append(
            {
                "integration_id": integration_id,
                "label": label,
                "status_class": status_class,
                "status_text": status_text,
                "text": f"{label}: {status_text}",
            }
        )
        health_detail_rows.append(
            {
                "integration_id": integration_id,
                "title": label,
                "status_class": status_class,
                "status_text": status_text,
                "source_text": f"Source: {str(row.get('source') or '--')}",
                "refresh_text": f"Refreshed {_fmt_age_sec(row.get('last_refresh_age_s'))}",
                "success_text": f"Last success {_fmt_age_sec(row.get('last_success_age_s'))}",
                "error_text": str(row.get("last_error") or "").strip() or None,
                "commands": commands,
            }
        )

    grouped: Dict[str, list[Dict[str, Any]]] = {}
    for entry in command_rows:
        owner = str(entry.get("owner_id") or "").strip().lower() or "other"
        grouped.setdefault(owner, []).append(entry)
    command_groups: list[Dict[str, Any]] = []
    for owner_id, items in sorted(
        grouped.items(),
        key=lambda item: (int((meta_map.get(item[0]) or {}).get("sort_order", 99)), item[0]),
    ):
        meta = meta_map.get(owner_id, {})
        title = str(meta.get("action_group_title") or meta.get("label") or owner_id.replace("_", " ").title() or "Commands")
        icon_class = str(meta.get("icon_class") or "mdi-puzzle-outline")
        rows = []
        for entry in items:
            patterns = entry.get("patterns") or []
            rows.append(
                {
                    "command_id": str(entry.get("command_id") or ""),
                    "label": str(entry.get("label") or entry.get("command_id") or "--"),
                    "patterns_text": ", ".join(str(p) for p in patterns) if isinstance(patterns, list) else "--",
                    "destructive": bool(entry.get("destructive")),
                }
            )
        command_groups.append(
            {
                "owner_id": owner_id,
                "title": title,
                "icon_class": icon_class,
                "rows": rows,
            }
        )

    return {
        "ready_text": ready_text,
        "command_hint": f"{len(command_rows)} registered commands" if command_rows else "Waiting for command registry...",
        "dashboard_cards": dashboard_cards,
        "health_chips": health_chips,
        "health_rows": health_detail_rows,
        "command_groups": command_groups,
    }


def integration_health_snapshot(polled: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for integration in _REGISTERED_INTEGRATIONS:
        payload = polled.get(integration.integration_id) or {}
        health = payload.get("health")
        if isinstance(health, dict):
            out[integration.integration_id] = dict(health)
            continue
        out[integration.integration_id] = {
            "integration_id": integration.integration_id,
            "enabled": bool(payload.get("enabled", False)),
            "available": None,
            "source": None,
            "last_refresh_ts": None,
            "last_success_ts": None,
            "last_error": None,
            "last_error_ts": None,
            "commands": [spec.command_id for spec in integration.commands],
            "api_ok": payload.get("api_ok"),
        }
    return out


def redact_agent_command_args(argv: Sequence[Any], mask: str = "...") -> list[Any]:
    redacted = list(argv)
    secret_flags = {
        str(field.cli_flag or "").strip()
        for field in get_registered_secret_config_fields()
        if str(field.cli_flag or "").strip()
    }
    if not secret_flags:
        return redacted
    i = 0
    while i < len(redacted):
        part = str(redacted[i] or "")
        if part in secret_flags and i + 1 < len(redacted):
            redacted[i + 1] = mask
            i += 2
            continue
        for flag in secret_flags:
            prefix = flag + "="
            if part.startswith(prefix):
                redacted[i] = prefix + mask
                break
        i += 1
    return redacted

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Sequence

from .base import CleanerSet, CommandContext, CommandSpec, ConfigFieldSpec, IntegrationSpec, PollContext
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

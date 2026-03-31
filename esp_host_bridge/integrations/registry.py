from __future__ import annotations

from typing import Any, Dict, Iterable, Sequence

from .base import CleanerSet, CommandContext, ConfigFieldSpec, IntegrationSpec, PollContext
from .docker import DOCKER_INTEGRATION
from .vms import VMS_INTEGRATION

_REGISTERED_INTEGRATIONS: tuple[IntegrationSpec, ...] = (
    DOCKER_INTEGRATION,
    VMS_INTEGRATION,
)


def get_registered_integrations() -> tuple[IntegrationSpec, ...]:
    return _REGISTERED_INTEGRATIONS


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
    for integration in _REGISTERED_INTEGRATIONS:
        if integration.handle_command is None:
            continue
        if integration.handle_command(cmd, ctx):
            return True
    return False


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

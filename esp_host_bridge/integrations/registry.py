from __future__ import annotations

from typing import Any, Dict, Iterable

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

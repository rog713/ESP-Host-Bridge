from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional


@dataclass(frozen=True)
class CleanerSet:
    clean_str: Callable[[Any, str], str]
    clean_int: Callable[[Any, int], int]
    clean_float: Callable[[Any, float], float]
    clean_bool: Callable[[Any, bool], bool]


@dataclass(frozen=True)
class ConfigFieldSpec:
    name: str
    kind: str
    default: Any
    checkbox: bool = False
    secret: bool = False
    cli_flag: Optional[str] = None
    label: str = ""
    hint: str = ""
    section_key: str = ""
    input_step: Optional[str] = None
    homeassistant_label: Optional[str] = None
    homeassistant_hint: Optional[str] = None
    homeassistant_value: Optional[str] = None
    readonly_when_homeassistant: bool = False


@dataclass
class PollContext:
    args: Any
    state: Any
    now: float
    homeassistant_mode: bool


@dataclass
class CommandContext:
    args: Any
    state: Any
    timeout: float
    homeassistant_mode: bool
    supervisor_request_json: Optional[Callable[..., Any]] = None


@dataclass(frozen=True)
class CommandSpec:
    command_id: str
    owner_id: str
    patterns: tuple[str, ...]
    match_kind: str = "exact"
    label: str = ""
    destructive: bool = False
    confirmation_text: str = ""


@dataclass(frozen=True)
class IntegrationSpec:
    integration_id: str
    title: str = ""
    homeassistant_title: Optional[str] = None
    section_key: str = ""
    icon_class: str = ""
    config_fields: tuple[ConfigFieldSpec, ...] = ()
    commands: tuple[CommandSpec, ...] = ()
    validate_cfg: Optional[Callable[[Dict[str, Any], CleanerSet], list[str]]] = None
    cfg_to_agent_args: Optional[Callable[[Dict[str, Any], CleanerSet], list[str]]] = None
    poll: Optional[Callable[[PollContext], Dict[str, Any]]] = None
    handle_command: Optional[Callable[[str, CommandContext], bool]] = None

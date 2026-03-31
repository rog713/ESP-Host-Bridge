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
    input_id: Optional[str] = None
    chip_id: Optional[str] = None


@dataclass(frozen=True)
class SetupActionSpec:
    button_id: str
    label: str


@dataclass(frozen=True)
class SetupChoiceSpec:
    label: str
    section_key: str
    select_id: str
    placeholder: str
    refresh_button_id: str
    refresh_button_label: str
    result_id: str
    buttons: tuple[SetupActionSpec, ...] = ()
    hint: str = ""


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
class DashboardCardSpec:
    card_id: str
    label: str
    render_kind: str
    metric_key: Optional[str] = None
    secondary_metric_key: Optional[str] = None
    tertiary_metric_key: Optional[str] = None
    subtext: str = ""
    homeassistant_label: Optional[str] = None
    homeassistant_subtext: Optional[str] = None
    severity_kind: str = ""
    spark_keys: tuple[str, ...] = ()
    spark_color: str = ""


@dataclass(frozen=True)
class DashboardGroupSpec:
    group_id: str
    title: str
    icon_class: str
    span_class: str = "span6"
    homeassistant_title: Optional[str] = None
    cards: tuple[DashboardCardSpec, ...] = ()


@dataclass(frozen=True)
class DashboardDetailSpec:
    detail_id: str
    title: str
    render_kind: str
    waiting_text: str
    show_all_text: str
    homeassistant_title: Optional[str] = None
    homeassistant_waiting_text: Optional[str] = None
    homeassistant_show_all_text: Optional[str] = None
    span_class: str = "span6"


@dataclass(frozen=True)
class IntegrationSpec:
    integration_id: str
    title: str = ""
    homeassistant_title: Optional[str] = None
    section_key: str = ""
    icon_class: str = ""
    sort_order: int = 100
    action_group_title: Optional[str] = None
    homeassistant_action_group_title: Optional[str] = None
    config_fields: tuple[ConfigFieldSpec, ...] = ()
    setup_choices: tuple[SetupChoiceSpec, ...] = ()
    commands: tuple[CommandSpec, ...] = ()
    dashboard_groups: tuple[DashboardGroupSpec, ...] = ()
    dashboard_details: tuple[DashboardDetailSpec, ...] = ()
    validate_cfg: Optional[Callable[[Dict[str, Any], CleanerSet], list[str]]] = None
    cfg_to_agent_args: Optional[Callable[[Dict[str, Any], CleanerSet], list[str]]] = None
    poll: Optional[Callable[[PollContext], Dict[str, Any]]] = None
    handle_command: Optional[Callable[[str, CommandContext], bool]] = None

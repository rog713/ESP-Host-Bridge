# Status Contract

This document describes the browser-facing `/api/status` contract on the `dev` branch.

For the backend integration model that feeds this contract, see:

- `docs/integration-model.md`

Scope:

- This is the Web UI contract, not the internal polling contract.
- It covers the payload shape that `esp_host_bridge/host_ui.js` consumes.
- It is expected to grow additively. Existing keys and meanings should stay stable once relied on by the UI.
- The current implementation builds a normalized runtime metric snapshot first, then renders:
  - USB CDC frames from that metric snapshot
  - browser status metadata from the published runtime state

## Base Runtime Fields

These come from `RunnerManager.status()` and describe process/runtime state.

- `host_name`
- `bridge_version`
- `platform_mode`
- `running`
- `pid`
- `started_at`
- `last_exit`
- `cmd`
- `next_log_id`
- `next_comm_log_id`
- `comm_status`
- `esp_status`
- `last_metrics_at`
- `last_metrics_age_s`
- `last_metrics`
- `last_metrics_line`
- `active_iface`
- `integration_health`
- `command_registry`
- `metric_history`

## UI Metadata Snapshots

These are derived in `esp_host_bridge/webui_app.py` and are the main refactor contract for future integrations.

- `integration_dashboard`
  - integration setup/dashboard labels and grouping metadata
- `monitor_dashboard`
  - grouped monitor cards for the dashboard
- `monitor_details`
  - workload detail section metadata
- `monitor_detail_payloads`
  - normalized detail payloads keyed by detail id
- `preview_ui`
  - ESP preview page/tabs/home-button/modal metadata
- `preview_cards`
  - ESP home preview summary cards
- `preview_action_groups`
  - modal action metadata for Docker and VM preview flows
- `summary_bar`
  - top dashboard summary chip metadata
- `integration_overview`
  - derived overview cards, health chips/rows, and command groups

## Stability Rules

- The browser should read these top-level keys directly rather than rebuilding the same structures client-side.
- New integrations should add metadata through the registry snapshots before any browser-specific branching is introduced.
- Payload changes should be additive when possible.
- If a breaking shape change is required, update:
  - this document
  - `tests/test_status_contract.py`
  - any affected browser code in `esp_host_bridge/host_ui.js`

## USB CDC Note

The USB CDC metrics line is intentionally not part of this contract.

Current plan:

- keep the existing compact line-based USB CDC payload stable
- treat USB CDC as an output adapter from the integration/runtime state
- do not redesign the serial protocol while the Web UI metadata refactor is still settling

That keeps ESPHome firmware compatibility stable while integrations and Web UI structure evolve on the backend.

### Current host-mode frame layout

The runtime currently rotates five compact frames in host mode via `build_status_line()`.

Frame 0:

- `CPU`
- `TEMP`
- `MEM`
- `UP`
- `RX`
- `TX`
- `IFACE`
- `TEMPAV`
- `HAMODE`
- `HATOKEN`
- `HADOCKAPI`
- `HAVMSAPI`
- `GPUEN`
- `DOCKEREN`
- `VMSEN`
- `POWER`

Frame 1:

- `DISK`
- `DISKPCT`
- `DISKR`
- `DISKW`
- `FAN`
- `DISKTAV`
- `FANAV`
- `POWER`

Frame 2:

- `GPUT`
- `GPUU`
- `GPUVM`
- `GPUAV`
- `POWER`

Frame 3:

- `DOCKRUN`
- `DOCKSTOP`
- `DOCKUNH`
- `DOCKER`
- `POWER`

Frame 4:

- `VMSRUN`
- `VMSSTOP`
- `VMSPAUSE`
- `VMSOTHER`
- `VMS`
- `POWER`

This layout is pinned by `tests/test_usb_payload_contract.py`.

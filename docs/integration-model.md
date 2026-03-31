# Integration Model

This document describes the internal integration model.

Scope:

- This is the backend architecture contract for future integrations.
- It describes how integrations declare config, telemetry, commands, and UI metadata.
- It is separate from the browser-facing `/api/status` payload contract in `docs/status-contract.md`.

## Goals

- Add new integrations without editing multiple unrelated files by hand.
- Keep the browser and USB CDC adapters stable while internal capabilities grow.
- Make config, command, and dashboard behavior declarative where practical.

## Core Pieces

### Integration Registry

The registry in `esp_host_bridge/integrations/registry.py` is the source of truth for integration metadata.

Each integration declares:

- an integration id
- display metadata
- config field specs
- command specs
- monitor/dashboard metadata
- preview metadata where applicable

Current built-ins are:

- `host`
- `docker`
- `vms`

### Config Field Specs

Config fields are declared through `ConfigFieldSpec` in `esp_host_bridge/integrations/base.py`.

Field specs support:

- default values
- type and validation behavior
- CLI flag mapping
- secret handling/redaction
- setup form metadata such as labels, hints, and section grouping

This is why new integration fields no longer need to be added manually in multiple config helpers.

### Command Registry

Commands are declared once and exposed through the registry.

Command metadata includes:

- owning integration
- command id
- label
- confirmation text
- destructive/action styling hints
- preview-target wiring for browser modals

The runtime executes registered commands. The browser renders command groups from registry-owned metadata instead of maintaining separate hardcoded button maps.

### Runtime Snapshot

The runtime now builds a normalized internal snapshot first, then renders adapters from that snapshot.

Current adapters are:

- browser status payload via `build_browser_status_payload()`
- USB CDC frames via `build_status_line()`

This is the key architectural boundary:

- integrations feed normalized runtime state
- adapters publish that state to browser and ESP consumers

### Browser Metadata Snapshots

The browser no longer infers most structure on its own.

Registry-backed snapshot helpers now supply:

- integration setup/dashboard metadata
- monitor dashboard sections
- monitor detail sections
- preview pages/tabs/home buttons/modals
- preview action groups
- summary bar metadata
- integration overview cards/health rows/command groups

Those snapshots are published through `/api/status` and pinned by tests.

## Stability Rules

- Add new integration behavior through registry metadata first.
- Keep browser changes additive where possible.
- Keep USB CDC output stable unless there is a deliberate versioned protocol change.
- When changing a published snapshot shape, update:
  - `docs/status-contract.md`
  - affected tests
  - affected browser code

## What A New Integration Should Provide

At minimum, a new integration should define:

- integration id and labels
- config field specs
- health/polling behavior
- optional commands
- optional monitor/preview metadata

If a feature needs browser structure, prefer adding metadata to the integration spec rather than a new hardcoded branch in `webui_app.py` or `host_ui.js`.

## Tests That Protect This Model

The current regression floor includes:

- `tests/test_integration_registry.py`
- `tests/test_runtime_snapshot.py`
- `tests/test_status_contract.py`
- `tests/test_usb_payload_contract.py`
- `tests/test_mac_overrides.py`
- `tests/test_config_paths.py`

If the model changes, those tests should change with it.

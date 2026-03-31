from __future__ import annotations

import argparse
import atexit
import html
import json
import logging
import os
import re
import secrets
import shlex
import ssl
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote_plus

from .config import (
    _clean_bool,
    _clean_str,
    REDACTED_SECRET_TEXT,
    atomic_write_json,
    cfg_from_form,
    default_webui_config_path,
    ensure_webui_session_secret,
    migrate_legacy_webui_config,
    load_cfg,
    normalize_cfg,
    preserve_secret_fields,
    redact_cfg,
    secret_placeholder_text,
    validate_cfg,
    webui_default_cfg,
)
from .integrations import get_integration_spec, redact_agent_command_args
from .metrics import detect_hardware_choices
from .runtime import (
    APP_VERSION,
    HOST_NAME,
    MDI_CODEPOINT_CACHE_PATH,
    MDI_FONT_CSS_URL,
    WEBUI_DEFAULT_PORT,
    _mdi_codepoint_map_cache,
    _mdi_codepoint_map_cache_err,
    _mdi_codepoint_map_lock,
    build_host_power_command_defaults,
    build_host_power_command_previews,
    fmt_ts,
    is_home_assistant_app_mode,
    RunnerManager,
)
from .serial import list_serial_port_choices, test_serial_open


def _redir(value: str, key: str = "msg"):
    from flask import redirect

    return redirect(f"/?{key}={quote_plus(value)}")

def _render_mode_toggle_html() -> str:
    return (
        '<div class="mode-toggle">'
        '<button id="viewSetupBtn" class="secondary" type="button">Setup</button>'
        '<button id="viewMonitorBtn" class="secondary" type="button">Dashboard</button>'
        "</div>"
    )

def _render_topbar_subtitle() -> str:
    return "USB CDC telemetry and control bridge for ESPHome"


def _integration_title(integration_id: str, homeassistant_mode: bool) -> str:
    spec = get_integration_spec(integration_id)
    if spec is None:
        return integration_id
    if homeassistant_mode and spec.homeassistant_title:
        return spec.homeassistant_title
    return spec.title or integration_id


def _render_config_field_input(field: Any, cfg: Dict[str, Any], homeassistant_mode: bool) -> str:
    field_name = str(field.name)
    label = str((field.homeassistant_label if homeassistant_mode else field.label) or field_name)
    hint = str((field.homeassistant_hint if homeassistant_mode else field.hint) or "")
    value = cfg.get(field_name, field.default)

    if homeassistant_mode and getattr(field, "readonly_when_homeassistant", False):
        readonly_value = str(field.homeassistant_value or value or "")
        control = f'<div class="hint" style="margin-bottom:6px;"><code>{html.escape(readonly_value)}</code></div>'
    elif getattr(field, "checkbox", False):
        checked_attr = " checked" if _clean_bool(value, bool(field.default)) else ""
        control = f'<input name="{html.escape(field_name)}" type="checkbox"{checked_attr}>'
    elif str(field.kind) in {"float", "int"}:
        step = str(field.input_step or ("0.1" if str(field.kind) == "float" else "1"))
        number_value = html.escape(str(value))
        control = f'<input name="{html.escape(field_name)}" type="number" step="{html.escape(step)}" value="{number_value}">'
    else:
        input_attrs = [f'name="{html.escape(field_name)}"', 'type="text"', f'value="{html.escape(str(value or ""))}"']
        input_id = str(getattr(field, "input_id", "") or "").strip()
        if input_id:
            input_attrs.append(f'id="{html.escape(input_id)}"')
        input_html = f'<input {" ".join(input_attrs)}>'
        chip_id = str(getattr(field, "chip_id", "") or "").strip()
        if chip_id:
            control = (
                '<div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">'
                f'{input_html}<span id="{html.escape(chip_id)}" class="sensor-chip auto">Auto</span>'
                "</div>"
            )
        else:
            control = input_html

    hint_html = f'<div class="hint">{hint}</div>' if hint else ""
    return f'<div class="row"><label>{html.escape(label)}</label><div>{control}{hint_html}</div></div>'


def _render_setup_choice_row(choice: Any) -> str:
    label = html.escape(str(choice.label or "Detected Choices"))
    select_id = html.escape(str(choice.select_id or ""))
    placeholder = html.escape(str(choice.placeholder or "(click Refresh)"))
    refresh_button_id = html.escape(str(choice.refresh_button_id or ""))
    refresh_button_label = html.escape(str(choice.refresh_button_label or "Refresh"))
    result_id = html.escape(str(choice.result_id or ""))
    buttons_html = "".join(
        f'<button id="{html.escape(str(btn.button_id))}" class="secondary" type="button">{html.escape(str(btn.label))}</button>'
        for btn in getattr(choice, "buttons", ()) or ()
    )
    hint = str(getattr(choice, "hint", "") or "")
    hint_html = f'<div class="hint">{hint}</div>' if hint else ""
    return (
        f'<div class="row"><label>{label}</label><div>'
        '<div class="actions" style="margin-top:0;">'
        f'<select id="{select_id}" style="min-width:280px; flex:1;"><option value="">{placeholder}</option></select>'
        f'<button id="{refresh_button_id}" class="secondary" type="button">{refresh_button_label}</button>'
        f'{buttons_html}</div>{hint_html}<div id="{result_id}" class="hint" style="margin-top:6px;"></div></div></div>'
    )


def _render_integration_setup_section(cfg: Dict[str, Any], integration_id: str, homeassistant_mode: bool) -> str:
    spec = get_integration_spec(integration_id)
    if spec is None:
        return ""
    title = _integration_title(integration_id, homeassistant_mode)
    icon_class = str(spec.icon_class or "mdi-cog-outline")
    section_key = str(spec.section_key or integration_id)
    rows = [
        _render_config_field_input(field, cfg, homeassistant_mode)
        for field in spec.config_fields
        if str(getattr(field, "section_key", "") or "") == section_key
    ]
    rows.extend(
        _render_setup_choice_row(choice)
        for choice in getattr(spec, "setup_choices", ()) or ()
        if str(getattr(choice, "section_key", "") or "") == section_key
    )
    rows_html = "\n      ".join(rows)
    return (
        f'<details class="section" data-section-key="{html.escape(section_key)}">'
        f'<summary><span class="section-icon" aria-hidden="true"><span class="mdi {html.escape(icon_class)}"></span></span>{html.escape(title)}</summary>'
        f'<div class="section-body">\n      {rows_html}\n      </div></details>'
    )

def page_html(title: str, body: str) -> str:
    mode_toggle_html = _render_mode_toggle_html()
    topbar_subtitle = _render_topbar_subtitle()
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@mdi/font@7.4.47/css/materialdesignicons.min.css">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Arimo:wght@400;700&family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@48,400,0,0&display=swap">
  <link rel="stylesheet" href="https://fonts.googleapis.com/icon?family=Material+Icons">
  <link rel="stylesheet" href="/static/host/host_ui.css">
</head>
<body>
  <div class="shell">
    <div class="topbar">
      <div>
        <div class="brandline">
          <span class="title-badge" aria-hidden="true"><span class="mdi mdi-chart-line"></span></span>
          <div>
            <h1>{html.escape(title)}</h1>
            <div class="subtitle">{html.escape(topbar_subtitle)}</div>
          </div>
        </div>
      </div>
      <div class="topbar-actions">
        <div class="status-pill">Version: {html.escape(APP_VERSION)}</div>
        {mode_toggle_html}
      </div>
    </div>
    <div class="wrap">{body}</div>
  </div>
</body>
</html>
"""

def _load_mdi_codepoint_map(force: bool = False) -> dict[str, int]:
    global _mdi_codepoint_map_cache, _mdi_codepoint_map_cache_err
    with _mdi_codepoint_map_lock:
        if _mdi_codepoint_map_cache is not None and not force:
            return _mdi_codepoint_map_cache
        if not force:
            try:
                if MDI_CODEPOINT_CACHE_PATH.exists():
                    raw = json.loads(MDI_CODEPOINT_CACHE_PATH.read_text(encoding="utf-8", errors="ignore"))
                    if isinstance(raw, dict):
                        cached: dict[str, int] = {}
                        for k, v in raw.items():
                            try:
                                name = str(k).strip().lower()
                                if not name.startswith("mdi-"):
                                    continue
                                cached[name] = int(v)
                            except Exception:
                                continue
                        if cached:
                            _mdi_codepoint_map_cache = cached
                            _mdi_codepoint_map_cache_err = None
                            return cached
            except Exception:
                pass
        req = urllib.request.Request(
            MDI_FONT_CSS_URL,
            headers={"User-Agent": "esp-host-bridge/1.0"},
        )
        try:
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310 - fixed HTTPS URL
                    css = resp.read().decode("utf-8", errors="ignore")
            except Exception as first_err:
                # Local networks with intercepting proxies can break cert validation.
                retry_unverified = isinstance(first_err, ssl.SSLError) or "CERTIFICATE_VERIFY_FAILED" in str(first_err)
                if not retry_unverified:
                    raise
                ctx = ssl._create_unverified_context()  # type: ignore[attr-defined]
                with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:  # nosec B310 - fixed HTTPS URL
                    css = resp.read().decode("utf-8", errors="ignore")
        except Exception as e:
            _mdi_codepoint_map_cache_err = str(e)
            if _mdi_codepoint_map_cache is not None:
                return _mdi_codepoint_map_cache
            raise
        out: dict[str, int] = {}
        for name, cp_hex in re.findall(
            r'\.(mdi-[a-z0-9-]+)::?before\s*\{[^}]*content:\s*"\\([0-9A-Fa-f]+)"',
            css,
            flags=re.IGNORECASE,
        ):
            try:
                out[name.lower()] = int(cp_hex, 16)
            except Exception:
                continue
        if not out:
            raise RuntimeError("Failed to parse MDI CSS codepoint map")
        _mdi_codepoint_map_cache = out
        _mdi_codepoint_map_cache_err = None
        try:
            MDI_CODEPOINT_CACHE_PATH.write_text(
                json.dumps(out, separators=(",", ":"), sort_keys=True),
                encoding="utf-8",
            )
        except Exception:
            pass
        return out

def mdi_lookup_glyph(name: str) -> tuple[Optional[str], Optional[int], Optional[str]]:
    raw = str(name or "").strip().lower()
    if not raw:
        return None, None, "Missing icon name"
    if raw.startswith("mdi "):
        raw = raw.replace(" ", "-", 1)
    if not raw.startswith("mdi-"):
        raw = "mdi-" + raw
    try:
        cmap = _load_mdi_codepoint_map()
    except Exception as e:
        return raw, None, f"Failed to fetch MDI map: {e}"
    cp = cmap.get(raw)
    if cp is None:
        return raw, None, "MDI icon not found"
    return raw, cp, None

def _register_host_static_routes_fallback(app: Any, *, route_prefix: str = "/static/host") -> None:
    endpoint = "host_static_asset"
    if endpoint in getattr(app, "view_functions", {}):
        return

    base_dir = Path(__file__).resolve().parent
    asset_map = {
        "host_ui.js": (base_dir / "host_ui.js", "application/javascript"),
        "host_ui.css": (base_dir / "host_ui.css", "text/css"),
    }

    @app.get(f"{route_prefix}/<path:asset_name>", endpoint=endpoint)
    def host_static_asset_route(asset_name: str) -> Any:
        from flask import Response

        entry = asset_map.get(str(asset_name or "").strip().lower())
        if entry is None:
            return Response("Not Found", status=404, mimetype="text/plain")

        asset_path, mimetype = entry
        try:
            payload = asset_path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            logging.warning("host static asset unavailable at %s (%s)", asset_path, e)
            payload = ""
        resp = Response(payload, status=200, mimetype=mimetype)
        resp.headers["Cache-Control"] = "public, max-age=300"
        return resp

def create_app(
    *,
    autostart_override: Optional[bool] = None,
) -> Any:
    try:
        from flask import Flask, Response, jsonify, redirect, request, send_file, session
        from werkzeug.security import check_password_hash, generate_password_hash
    except Exception as e:
        raise RuntimeError("Flask is required for webui mode. Install with: pip install flask") from e

    app = Flask(__name__, static_folder=None)
    cfg_path, cfg_migrated, cfg_migrated_from = migrate_legacy_webui_config(default_webui_config_path())
    def _env_flag(name: str, default: bool) -> bool:
        raw = os.environ.get(name)
        if raw is None:
            return default
        return str(raw).strip().lower() not in {"0", "false", "no", "off"}

    autostart = _env_flag("AUTOSTART", True) if autostart_override is None else bool(autostart_override)
    python_bin = os.environ.get("WEBUI_PYTHON", sys.executable or "python3")
    portable_script = str(os.environ.get("PORTABLE_HOST_METRICS_SCRIPT", "") or "").strip()
    self_script = Path(portable_script or str(Path(__file__).resolve()))
    package_module = None if portable_script else ((__package__ or "").split(".", 1)[0] or None)
    pub = RunnerManager(self_script=self_script, python_bin=python_bin, package_module=package_module)
    if cfg_migrated and cfg_migrated_from is not None and hasattr(pub, "log_event"):
        pub.log_event(f"[config migrated] {cfg_migrated_from} -> {cfg_path}")
    initial_cfg = load_cfg(cfg_path)
    initial_cfg, secret_updated = ensure_webui_session_secret(initial_cfg)
    if secret_updated:
        atomic_write_json(cfg_path, initial_cfg)
    app.secret_key = str(initial_cfg.get("webui_session_secret") or secrets.token_hex(32))

    try:
        from esp_host_bridge.ui_assets import register_host_static_routes
    except Exception:
        try:
            from ui_assets import register_host_static_routes
        except Exception as e:
            logging.warning(
                "ui_assets import failed; using inline static asset fallback (%s)",
                e,
            )
            register_host_static_routes = _register_host_static_routes_fallback

    register_host_static_routes(app)

    def _webui_auth_required() -> bool:
        cfg = load_cfg(cfg_path)
        return _clean_bool(cfg.get("webui_auth_enabled"), False) and bool(_clean_str(cfg.get("webui_password_hash"), ""))

    def _safe_next_target(value: str) -> str:
        text = str(value or "").strip()
        if not text.startswith("/"):
            return "/"
        if text.startswith("//"):
            return "/"
        return text

    def _login_redirect() -> Any:
        next_target = _safe_next_target(request.full_path if request.query_string else request.path)
        return redirect(f"/login?next={quote_plus(next_target)}")

    @app.before_request
    def require_webui_login() -> Any:
        path = request.path or "/"
        if not _webui_auth_required():
            return None
        if path in {"/login", "/logout", "/api/status"}:
            return None
        if path.startswith("/static/host/"):
            return None
        if session.get("webui_authenticated") is True:
            return None
        if path.startswith("/api/"):
            return jsonify({"ok": False, "message": "Authentication required"}), 401
        return _login_redirect()

    @app.route("/login", methods=["GET", "POST"])
    def login() -> Any:
        cfg = load_cfg(cfg_path)
        auth_enabled = _clean_bool(cfg.get("webui_auth_enabled"), False)
        password_hash = _clean_str(cfg.get("webui_password_hash"), "")
        if not auth_enabled or not password_hash:
            return redirect("/")

        next_target = _safe_next_target(request.values.get("next", "/"))
        error = ""
        if request.method == "POST":
            submitted_password = str(request.form.get("password") or "")
            if submitted_password and check_password_hash(password_hash, submitted_password):
                session["webui_authenticated"] = True
                return redirect(next_target)
            error = "Incorrect password."

        err_html = f'<div class="err">{html.escape(error)}</div>' if error else ""
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>ESP Host Bridge Login</title>
  <link rel="stylesheet" href="/static/host/host_ui.css">
</head>
<body>
  <div class="shell" style="max-width:520px;">
    <div class="card">
      <h1 style="margin-top:0;">ESP Host Bridge</h1>
      <p class="hint">Direct Web UI access is protected. Enter the password to continue.</p>
      {err_html}
      <form method="post" action="/login">
        <input type="hidden" name="next" value="{html.escape(next_target)}">
        <div class="row"><label>Password</label><div><input name="password" type="password" autocomplete="current-password"></div></div>
        <div class="actions"><button type="submit">Sign In</button></div>
      </form>
    </div>
  </div>
</body>
</html>"""

    @app.post("/logout")
    def logout() -> Any:
        session.pop("webui_authenticated", None)
        return redirect("/login")

    @app.get("/")
    def index() -> str:
        cfg = load_cfg(cfg_path)
        st = pub.status()
        logs = pub.logs_tail_text()
        comm_logs = pub.comm_logs_tail_text()
        msg = request.args.get("msg", "").strip()
        err = request.args.get("err", "").strip()

        msg_html = f'<div class="ok">{html.escape(msg)}</div>' if msg else ""
        err_html = f'<div class="err">{html.escape(err)}</div>' if err else ""
        logout_action = "/logout"
        homeassistant_mode = is_home_assistant_app_mode()
        if homeassistant_mode:
            power_commands_body = """
      <div class=\"row\"><label>Power Control Path</label><div><input type=\"text\" value=\"Home Assistant Supervisor host API\" readonly><div class=\"hint\">Uses <code>POST /host/shutdown</code> for <code>CMD=shutdown</code> and <code>POST /host/reboot</code> for <code>CMD=restart</code> / <code>CMD=reboot</code>.</div></div></div>
      <div class=\"row\"><label>Allow Host Commands</label><div><input name=\"allow_host_cmds\" type=\"checkbox\" {'checked' if cfg.get('allow_host_cmds') else ''}><div class=\"hint\">Lets the ESP request host actions like shutdown and restart through Home Assistant Supervisor.</div></div></div>
            """
        else:
            power_readonly_attr = ''
            host_power_detect_hint = "Auto-fills common power commands for this operating system. Review before saving."
            shutdown_command_hint = "Optional override for <code>CMD=shutdown</code>. Example: <code>systemctl poweroff</code>"
            restart_command_hint = "Optional override for <code>CMD=restart</code> / <code>CMD=reboot</code>."
            preview_host_power_hint = "Shows what will run for <code>CMD=shutdown</code> and <code>CMD=restart</code> (no execution)."
            host_cmd_use_sudo_hint = "Only enable if you configured sudo permissions for this process."
            power_commands_body = f"""
      <div class=\"row\"><label>Host Power Command Defaults</label><div><button id=\"detectHostPowerBtn\" class=\"secondary\" type=\"button\">Detect Host Commands</button><div class=\"hint\">{host_power_detect_hint}</div><div id=\"hostPowerDetectResult\" class=\"hint\" style=\"margin-top:6px;\"></div></div></div>
      <div class=\"row\"><label>Shutdown Command</label><div><input id=\"shutdownCmdInput\" name=\"shutdown_cmd\" type=\"text\" value=\"{html.escape(str(cfg.get('shutdown_cmd', '')))}\"{power_readonly_attr}><div class=\"hint\">{shutdown_command_hint}</div></div></div>
      <div class=\"row\"><label>Restart Command</label><div><input id=\"restartCmdInput\" name=\"restart_cmd\" type=\"text\" value=\"{html.escape(str(cfg.get('restart_cmd', '')))}\"{power_readonly_attr}><div class=\"hint\">{restart_command_hint}</div></div></div>
      <div class=\"row\"><label>Preview Host Commands</label><div><button id=\"previewHostPowerBtn\" class=\"secondary\" type=\"button\">Preview Commands</button><div class=\"hint\">{preview_host_power_hint}</div><pre id=\"hostPowerPreviewBox\" style=\"margin-top:8px; max-height:160px; min-height:80px;\">Click Preview Commands to see resolved host commands.</pre></div></div>
      <div class=\"row\"><label>Allow Host Commands</label><div><input name=\"allow_host_cmds\" type=\"checkbox\" {'checked' if cfg.get('allow_host_cmds') else ''}><div class=\"hint\">Lets the ESP request host actions like shutdown/restart. Leave off unless you need it.</div></div></div>
      <div class=\"row\"><label>Use sudo for Host Commands</label><div><input name=\"host_cmd_use_sudo\" type=\"checkbox\" {'checked' if cfg.get('host_cmd_use_sudo') else ''}><div class=\"hint\">{host_cmd_use_sudo_hint}</div></div></div>
            """
        workload_summary_label = "Add-on Summary" if homeassistant_mode else "Docker Summary"
        workload_summary_sub = "Run / Stop / Issue" if homeassistant_mode else "Run / Stop / Unhealthy"
        vm_summary_label = "Integration Summary" if homeassistant_mode else "VM Summary"
        vm_summary_sub = "Loaded integrations" if homeassistant_mode else "Run / Pause / Stop / Other"
        workload_list_label = "Add-ons" if homeassistant_mode else "Containers"
        workload_waiting_text = "Waiting for add-on data..." if homeassistant_mode else "Waiting for Docker data..."
        workload_show_all = "Show all add-ons" if homeassistant_mode else "Show all containers"
        vm_list_label = "Integrations" if homeassistant_mode else "Virtual Machines"
        vm_waiting_text = "Waiting for integration data..." if homeassistant_mode else "Waiting for VM data..."
        vm_show_all = "Show all integrations" if homeassistant_mode else "Show all virtual machines"
        saved_webui_password_placeholder = secret_placeholder_text(
            bool(_clean_str(cfg.get("webui_password_hash"), "")),
            REDACTED_SECRET_TEXT,
        )
        webui_password_hint = (
            f'Leave blank to keep the current password. Stored value is masked as <code>{html.escape(saved_webui_password_placeholder)}</code>. Disable protection to remove it.'
            if saved_webui_password_placeholder
            else "Leave blank to keep the current password. Disable protection to remove it."
        )
        body = f"""
<div id=\"setupView\" class=\"grid\">
  <div class=\"card\">
    {msg_html}
    {err_html}
    <form method=\"post\" action=\"/save\">
      <div class=\"quick-setup\">
        <h3><span class="quick-setup-icon" aria-hidden="true"><span class="mdi mdi-auto-fix"></span></span>Quick Setup</h3>
        <p>For most users: pick a serial port, test it, then save and restart the agent.</p>
        <ol>
          <li>Click <b>Refresh Ports</b> and choose your device (prefer <code>/dev/serial/by-id/...</code> on Linux/Unraid).</li>
          <li>Click <b>Use Port</b>, then click <b>Test Port</b>.</li>
          <li>Click <b>Save + Restart</b> at the bottom of the left panel.</li>
        </ol>
      </div>
      <details class=\"section\" data-section-key=\"connection\" open><summary><span class=\"section-icon\" aria-hidden=\"true\"><span class=\"mdi mdi-usb-port\"></span></span>Bridge Connection</summary><div class=\"section-body\">
      <div class=\"row\"><label>Serial Port</label><div><div style=\"display:flex; align-items:center; gap:8px; flex-wrap:wrap;\"><input id=\"serialPortInput\" name=\"serial_port\" type=\"text\" value=\"{html.escape(str(cfg.get('serial_port', '')))}\"><span id=\"serialPortChip\" class=\"sensor-chip auto\">Auto</span></div><div class=\"hint\">Use a stable path like <code>/dev/serial/by-id/&lt;device&gt;</code> on Linux/Unraid. Leave it blank for auto-detect, or enter <code>NONE</code>/<code>DEBUG</code> to run without opening a USB serial device.</div></div></div>
      <div class=\"row\"><label>Detected Ports</label><div><div class=\"actions\" style=\"margin-top:0;\"><select id=\"serialPortsSelect\" style=\"min-width:280px; flex:1;\"><option value=\"\">(click Refresh Ports)</option></select><button id=\"refreshPortsBtn\" class=\"secondary\" type=\"button\">Refresh Ports</button><button id=\"useSelectedPortBtn\" class=\"secondary\" type=\"button\">Use Port</button></div><div class=\"hint\">Choose a detected port, then click <b>Use Port</b> to copy it into Serial Port.</div><div id=\"portsResult\" class=\"hint\" style=\"margin-top:6px;\"></div></div></div>
      <div class=\"row\"><label>Baud Rate</label><div><input id=\"baudInput\" name=\"baud\" type=\"number\" value=\"{html.escape(str(cfg.get('baud', 115200)))}\"><div class=\"hint\">Most setups use <code>115200</code>.</div></div></div>
      <div class=\"row\"><label>Port Test</label><div><button id=\"testSerialBtn\" class=\"secondary\" type=\"button\">Test Port</button><div class=\"hint\">Checks whether the selected Serial Port opens cleanly. For <code>NONE</code>/<code>DEBUG</code>, it confirms serial bypass mode instead.</div><div id=\"testSerialResult\" class=\"hint\" style=\"margin-top:6px;\"></div></div></div>
      </div></details>
      <details class=\"section\" data-section-key=\"telemetry\" open><summary><span class=\"section-icon\" aria-hidden=\"true\"><span class=\"mdi mdi-chart-line\"></span></span>Telemetry</summary><div class=\"section-body\">
      <div class=\"row\"><label>Update Interval (s)</label><div><input name=\"interval\" type=\"number\" step=\"0.1\" value=\"{html.escape(str(cfg.get('interval', 1.0)))}\"><div class=\"hint\">How often metrics are sent to the ESP device.</div></div></div>
      <div class=\"row\"><label>Connection Timeout (s)</label><div><input name=\"timeout\" type=\"number\" step=\"0.1\" value=\"{html.escape(str(cfg.get('timeout', 2.0)))}\"><div class=\"hint\">Timeout used for serial reads and host metric checks.</div></div></div>
      </div></details>
      {_render_integration_setup_section(cfg, "host", homeassistant_mode)}
      {_render_integration_setup_section(cfg, "docker", homeassistant_mode)}
      {_render_integration_setup_section(cfg, "vms", homeassistant_mode)}
      <details class=\"section\" data-section-key=\"power_commands\"><summary><span class=\"section-icon\" aria-hidden=\"true\"><span class=\"mdi mdi-power\"></span></span>Power Commands</summary><div class=\"section-body\">
      {power_commands_body}
      </div></details>
      <details class=\"section\" data-section-key=\"direct_webui_security\"><summary><span class=\"section-icon\" aria-hidden=\"true\"><span class=\"mdi mdi-lock-outline\"></span></span>Direct Web UI Security</summary><div class=\"section-body\">
      <div class=\"row\"><label>Protect Direct Web UI</label><div><input name=\"webui_auth_enabled\" type=\"checkbox\" {'checked' if cfg.get('webui_auth_enabled') else ''}><div class=\"hint\">Requires a password for direct Web UI access.</div></div></div>
      <div class=\"row\"><label>New Password</label><div><input name=\"webui_password\" type=\"password\" autocomplete=\"new-password\" placeholder=\"{html.escape(saved_webui_password_placeholder)}\"><div class=\"hint\">{webui_password_hint}</div></div></div>
      </div></details>
      <div class=\"actions form-actions-sticky\">
        <button type=\"submit\">Save + Restart</button>
        <button class=\"secondary\" type=\"submit\" formaction=\"/save?restart=0\">Save Only</button>
      </div>
      <details class=\"section\" data-section-key=\"advanced_ui\"><summary><span class=\"section-icon\" aria-hidden=\"true\"><span class=\"mdi mdi-cog-outline\"></span></span>Advanced</summary><div class=\"section-body\">
      <div class=\"hint\">Config file: <code>{html.escape(str(cfg_path))}</code></div>
      <div class=\"hint\">Script path: <code>{html.escape(str(self_script))}</code></div>
      <div class=\"hint\">Autostart: <code>{'enabled' if autostart else 'disabled'}</code></div>
      </div></details>
    </form>
  </div>
  <div class="card">
    <div class="hero">
      <div class="hero-shell">
        <div class="hero-copy">
          <div class="hero-title">Bridge Status</div>
          <div class="hero-transport">Transport: USB CDC</div>
          <div class="hero-status" id="statusLine">
            <div class="hero-status-grid">
              <div class="hero-status-card">
                <div class="hero-status-k">Agent</div>
                <div class="hero-status-v" id="statusAgent">{'Running' if st['running'] else 'Stopped'}</div>
              </div>
              <div class="hero-status-card">
                <div class="hero-status-k">PID</div>
                <div class="hero-status-v" id="statusPid">{st['pid'] or '--'}</div>
              </div>
              <div class="hero-status-card">
                <div class="hero-status-k">Started</div>
                <div class="hero-status-v hero-status-v-sm" id="statusStarted">{fmt_ts(st['started_at'])}</div>
              </div>
              <div class="hero-status-card">
                <div class="hero-status-k">Last Exit Code</div>
                <div class="hero-status-v" id="statusLastExit">{st['last_exit'] if st['last_exit'] is not None else '--'}</div>
              </div>
            </div>
          </div>
          <div class="hero-meta">
            <div class="status-pill" id="telemetryHealth">Telemetry: Waiting</div>
            <div class="status-pill" id="serialHealth">Serial: Unknown</div>
            <div class="status-pill" id="hostNameStatus">Host: --</div>
            <div class="status-pill" id="activeIfaceStatus">Active Interface: --</div>
            <div class="status-pill" id="serialReconnects">Reconnects: 0</div>
            <div class="status-pill" id="serialEventAge">Comm: --</div>
            <div class="status-pill" id="espBootCount">ESP Boots: 0</div>
            <div class="status-pill" id="displaySleepStatus">Display: --</div>
            <div class="status-pill" id="espWifiStatus">ESP Wi-Fi: --</div>
            <div class="status-pill" id="espWifiDetail">ESP Wi-Fi Detail: --</div>
            <div class="status-pill" id="espBootAge">Last ESP Boot: --</div>
            <div class="status-pill" id="espBootReason">Last ESP Reset: --</div>
          </div>
          <div class="actions" style="margin: 0;">
            <form method="post" action="/start" style="display:inline;"><button class="secondary" type="submit">Start</button></form>
            <form method="post" action="/restart" style="display:inline;"><button type="submit">Restart</button></form>
            <form method="post" action="/stop" style="display:inline;"><button class="danger" type="submit">Stop</button></form>
            <form method="get" action="/" style="display:inline;"><button class="secondary" type="submit">Refresh</button></form>
            {'<form method="post" action="' + html.escape(logout_action) + '" style="display:inline;"><button class="secondary" type="submit">Sign Out</button></form>' if _webui_auth_required() else ''}
          </div>
        </div>
        <div class="hero-art" aria-hidden="true"><span class="mdi mdi-chart-timeline-variant"></span></div>
      </div>
    </div>
    <div class="metrics-grid" id="metricsPreview">
      <div class="metric-card"><div class="metric-label"><span class="metric-icon" aria-hidden="true"><span class="mdi mdi-cpu-64-bit"></span></span>CPU</div><div class="metric-value" id="mCPU">Waiting...</div><div class="metric-sub">Usage</div></div>
      <div class="metric-card"><div class="metric-label"><span class="metric-icon" aria-hidden="true"><span class="mdi mdi-memory"></span></span>Memory</div><div class="metric-value" id="mMEM">Waiting...</div><div class="metric-sub">Used</div></div>
      <div class="metric-card"><div class="metric-label"><span class="metric-icon" aria-hidden="true"><span class="mdi mdi-thermometer"></span></span>CPU Temp</div><div class="metric-value" id="mTEMP">Waiting...</div><div class="metric-sub">Sensor</div></div>
      <div class="metric-card"><div class="metric-label"><span class="metric-icon" aria-hidden="true"><span class="mdi mdi-lan"></span></span>Network</div><div class="metric-value" id="mNET">Waiting...</div><div class="metric-sub">RX / TX</div></div>
      <div class="metric-card"><div class="metric-label"><span class="metric-icon" aria-hidden="true"><span class="mdi mdi-harddisk"></span></span>Disk</div><div class="metric-value" id="mDISK">Waiting...</div><div class="metric-sub">Temp / Usage</div></div>
      <div class="metric-card"><div class="metric-label"><span class="metric-icon" aria-hidden="true"><span class="mdi mdi-docker"></span></span>Docker</div><div class="metric-value" id="mDOCKER">Waiting...</div><div class="metric-sub">Run / Stop / Unh</div></div>
      <div class="metric-card"><div class="metric-label"><span class="metric-icon" aria-hidden="true"><span class="mdi mdi-monitor-multiple"></span></span>VMs</div><div class="metric-value" id="mVMS">Waiting...</div><div class="metric-sub">Run / Pause / Stop</div></div>
    </div>
    <details class="section" data-section-key="comm_logs_control"><summary><span class="section-icon" aria-hidden="true"><span class="mdi mdi-transit-connection-variant"></span></span>Bridge Logs</summary><div class="section-body">
    <div class="actions" style="margin: 0 0 12px;">
      <button id="clearCommLogsBtn" class="secondary" type="button">Clear Bridge Logs</button>
      <button id="downloadCommLogsBtn" class="secondary" type="button">Download Bridge Logs</button>
    </div>
    <pre id="commLogs">{html.escape(comm_logs) if comm_logs else 'No communication events yet. Serial disconnects/reconnects will appear here.'}</pre>
    </div></details>
    <details class="section" data-section-key="logs_control"><summary><span class="section-icon" aria-hidden="true"><span class="mdi mdi-file-document-outline"></span></span>Logs</summary><div class="section-body">
    <div class="actions" style="margin: 0 0 12px;">
      <button id="clearLogsBtn" class="secondary" type="button">Clear Logs</button>
      <button id="downloadLogsBtn" class="secondary" type="button">Download Logs</button>
      <label class="hint" style="display:flex; align-items:center; gap:8px; margin:0;">
        <input id="hideMetricLogsChk" type="checkbox" style="width:16px; height:16px; margin:0;">
        Hide metric frames
      </label>
    </div>
    <pre id="logs">{html.escape(logs) if logs else 'No logs yet. Start the agent or click Refresh to load recent output.'}</pre>
    </div></details>
  </div>
</div>
<div id="monitorView" class="card">
  <div class="monitor-shell">
    <div class="dashboard-head">
      <div class="dashboard-title">Dashboard</div>
      <div class="dashboard-subtitle">Live host telemetry, bridge health, and ESP preview</div>
    </div>
    <div class="summary-bar" id="monitorSummaryBar">
      <div class="summary-chip"><div class="k">Agent</div><div class="v" id="sumAgent">--</div></div>
      <div class="summary-chip"><div class="k">Serial / Workloads</div><div class="v" id="sumDocker">--</div></div>
      <div class="summary-chip"><div class="k">Last Telemetry</div><div class="v" id="sumAge">--</div></div>
      <div class="summary-chip"><div class="k">Integrations</div><div class="v" id="sumIntegrations">--</div></div>
      <div class="summary-chip"><div class="k">Host Power</div><div class="v" id="sumPower">--</div></div>
    </div>
    <div class="monitor-grid">
      <section class="mgroup span6">
        <h3><span class="gicon" aria-hidden="true"><span class="mdi mdi-cellphone-cog"></span></span>ESP Screen Preview</h3>
        <div class="esp-preview-wrap">
          <div class="esp-preview-toolbar">
            <div class="esp-preview-tabs" id="espPreviewTabs">
              <button class="secondary" type="button" data-esp-page="home"><span class="mdi mdi-home-outline" aria-hidden="true"></span>Home</button>
              <button class="secondary" type="button" data-esp-page="docker"><span class="mdi mdi-docker" aria-hidden="true"></span>Docker</button>
              <button class="secondary" type="button" data-esp-page="settings_1"><span class="mdi mdi-brightness-6" aria-hidden="true"></span>Settings 1</button>
              <button class="secondary" type="button" data-esp-page="settings_2"><span class="mdi mdi-power" aria-hidden="true"></span>Settings 2</button>
              <button class="secondary" type="button" data-esp-page="info_1"><span class="mdi mdi-access-point-network" aria-hidden="true"></span>Network</button>
              <button class="secondary" type="button" data-esp-page="info_2"><span class="mdi mdi-monitor-dashboard" aria-hidden="true"></span>System</button>
              <button class="secondary" type="button" data-esp-page="info_3"><span class="mdi mdi-thermometer" aria-hidden="true"></span>CPU Temp</button>
              <button class="secondary" type="button" data-esp-page="info_4"><span class="mdi mdi-harddisk" aria-hidden="true"></span>Disk Temp</button>
              <button class="secondary" type="button" data-esp-page="info_5"><span class="mdi mdi-chart-donut" aria-hidden="true"></span>Disk Usage</button>
              <button class="secondary" type="button" data-esp-page="info_6"><span class="mdi mdi-graph-line" aria-hidden="true"></span>GPU</button>
              <button class="secondary" type="button" data-esp-page="info_7"><span class="mdi mdi-timer-outline" aria-hidden="true"></span>Uptime</button>
              <button class="secondary" type="button" data-esp-page="info_8"><span class="mdi mdi-card-text-outline" aria-hidden="true"></span>Host Name</button>
              <button class="secondary" type="button" data-esp-page="vms"><span class="mdi mdi-monitor-multiple" aria-hidden="true"></span>VMS</button>
            </div>
          </div>
          <div class="esp-shell">
            <div class="esp-viewport" id="espPreviewViewport">
              <div class="esp-display-stage" id="espPreviewStage">
                <div class="esp-screen home-mode" id="espPreviewScreen" tabindex="0">
                  <div class="esp-top" id="espPreviewTop">
                    <div class="esp-top-title" id="espTopTitle">HOME</div>
                    <div class="esp-top-pills" id="espTopPills"></div>
                    <div class="esp-page-indicator" id="espPageIndicator" aria-hidden="true"></div>
                  </div>
                  <div class="esp-page active" id="espPageHome">
                    <div class="esp-home-full">
                      <div class="esp-home-canvas">
                      <div class="esp-home-cross-v top"></div>
                      <div class="esp-home-cross-v bottom"></div>
                      <div class="esp-home-cross-h left"></div>
                      <div class="esp-home-cross-h right"></div>
                      <div class="esp-home-ring"></div>
                      <div class="esp-home-btn tl" data-esp-nav="docker" title="Docker"><span class="mdi mdi-docker"></span></div>
                      <div class="esp-home-btn tr" data-esp-nav="vms" title="VMS"><span class="mdi mdi-monitor-multiple"></span></div>
                      <div class="esp-home-btn bl" data-esp-nav="info_1" title="Info"><span class="mdi mdi-information-outline"></span></div>
                      <div class="esp-home-btn br" data-esp-nav="settings_1" title="Settings"><span class="mdi mdi-cog-outline"></span></div>
                      <div class="esp-home-center" title="Screen Saver"><span class="mdi mdi-database-outline"></span></div>
                    </div>
                  </div>
                </div>
                <div class="esp-page" id="espPageInfo1">
                <div class="esp-dualmetric-page">
                  <div class="esp-page-hint"></div>
                  <div class="esp-dualmetric-card">
                    <div class="esp-dualmetric-stats">
                      <div class="esp-dualmetric-dot left"></div>
                      <div class="esp-dualmetric-lbl left">RX</div>
                      <div class="esp-dualmetric-val left" id="espNetRxVal">--</div>
                      <div class="esp-dualmetric-unit left">MB/s</div>
                      <div class="esp-dualmetric-dot right"></div>
                      <div class="esp-dualmetric-lbl right">TX</div>
                      <div class="esp-dualmetric-val right" id="espNetTxVal">--</div>
                      <div class="esp-dualmetric-unit right">MB/s</div>
                    </div>
                    <div class="esp-sys-chartbox">
                      <div id="espNetGraph"></div>
                      <div class="esp-sys-loading" id="espNetLoading">Loading...</div>
                    </div>
                  </div>
                </div>
              </div>
                <div class="esp-page" id="espPageInfo2">
                <div class="esp-sys-page">
                  <div class="esp-page-hint"></div>
                  <div class="esp-sys-card">
                    <div class="esp-sys-stats">
                      <div class="esp-sys-dot cpu"></div>
                      <div class="esp-sys-t" style="left:42px; top:12px;">CPU</div>
                      <div class="esp-sys-v" id="espSysCpuVal" style="left:42px; top:22px;">--</div>
                      <div class="esp-sys-u cpu">%</div>
                      <div class="esp-sys-dot mem"></div>
                      <div class="esp-sys-t" style="left:226px; top:12px;">MEMORY</div>
                      <div class="esp-sys-v mem" id="espSysMemVal" style="left:226px; top:22px;">--</div>
                      <div class="esp-sys-u mem">%</div>
                    </div>
                    <div class="esp-sys-chartbox">
                      <div id="espSysGraph"></div>
                      <div class="esp-sys-loading" id="espSysLoading">Loading...</div>
                    </div>
                  </div>
                </div>
              </div>
                <div class="esp-page" id="espPageDocker">
                <div class="esp-workload-page">
                  <div class="esp-page-hint"></div>
                  <div class="esp-workload-list" id="espDockerRows"></div>
                  <div class="esp-workload-empty" id="espDockerEmpty" hidden>
                    <div class="esp-workload-empty-icon"><span class="mdi mdi-docker"></span></div>
                    <div class="esp-workload-empty-title"></div>
                    <div class="esp-workload-empty-subtitle"></div>
                  </div>
                </div>
              </div>
                <div class="esp-page" id="espPageVms">
                <div class="esp-workload-page">
                  <div class="esp-page-hint"></div>
                  <div class="esp-workload-list" id="espVmsRows"></div>
                  <div class="esp-workload-empty" id="espVmsEmpty" hidden>
                    <div class="esp-workload-empty-icon"><span class="mdi mdi-monitor-multiple"></span></div>
                    <div class="esp-workload-empty-title"></div>
                    <div class="esp-workload-empty-subtitle"></div>
                  </div>
                </div>
              </div>
                <div class="esp-page" id="espPageInfo3">
                <div class="esp-metric-page">
                  <div class="esp-page-hint"></div>
                  <div class="esp-metric-card">
                    <div class="esp-metric-stats">
                      <div class="esp-metric-dot"></div>
                      <div class="esp-metric-title">CPU TEMP</div>
                      <div class="esp-metric-value" id="espCpuTempVal">--</div>
                      <div class="esp-metric-unit">°C</div>
                    </div>
                    <div class="esp-sys-chartbox">
                      <div id="espCpuTempGraph"></div>
                      <div class="esp-sys-loading" id="espCpuTempLoading">Loading...</div>
                    </div>
                  </div>
                </div>
              </div>
                <div class="esp-page" id="espPageInfo4">
                <div class="esp-metric-page">
                  <div class="esp-page-hint"></div>
                  <div class="esp-metric-card">
                    <div class="esp-metric-stats">
                      <div class="esp-metric-dot violet"></div>
                      <div class="esp-metric-title">DISK TEMP</div>
                      <div class="esp-metric-value violet" id="espDiskTempVal">--</div>
                      <div class="esp-metric-unit">°C</div>
                    </div>
                    <div class="esp-sys-chartbox">
                      <div id="espDiskTempGraph"></div>
                      <div class="esp-sys-loading" id="espDiskTempLoading">Loading...</div>
                    </div>
                  </div>
                </div>
              </div>
                <div class="esp-page" id="espPageInfo5">
                <div class="esp-metric-page">
                  <div class="esp-page-hint"></div>
                  <div class="esp-metric-card">
                    <div class="esp-metric-stats">
                      <div class="esp-metric-dot"></div>
                      <div class="esp-metric-title">DISK USAGE</div>
                      <div class="esp-metric-value" id="espDiskUsageVal">--</div>
                      <div class="esp-metric-unit">%</div>
                    </div>
                    <div class="esp-sys-chartbox">
                      <div id="espDiskUsageGraph"></div>
                      <div class="esp-sys-loading" id="espDiskUsageLoading">Loading...</div>
                    </div>
                  </div>
                </div>
              </div>
                <div class="esp-page" id="espPageInfo6">
                <div class="esp-dualmetric-page">
                  <div class="esp-page-hint"></div>
                  <div class="esp-dualmetric-card">
                    <div class="esp-dualmetric-stats">
                      <div class="esp-dualmetric-dot left"></div>
                      <div class="esp-dualmetric-lbl left">GPU</div>
                      <div class="esp-dualmetric-val left" id="espGpuUtilVal">--</div>
                      <div class="esp-dualmetric-unit left">%</div>
                      <div class="esp-dualmetric-dot right"></div>
                      <div class="esp-dualmetric-lbl right">TEMP</div>
                      <div class="esp-dualmetric-val right" id="espGpuTempVal">--</div>
                      <div class="esp-dualmetric-unit right">°C</div>
                    </div>
                    <div class="esp-sys-chartbox">
                      <div id="espGpuGraph"></div>
                      <div class="esp-sys-loading" id="espGpuLoading">Loading...</div>
                    </div>
                  </div>
                </div>
              </div>
                <div class="esp-page" id="espPageInfo7">
                <div class="esp-uptime-page">
                  <div class="esp-page-hint"></div>
                  <div class="esp-uptime-card">
                    <div class="esp-uptime-status" id="espUptimeStatus"></div>
                    <div class="esp-uptime-value" id="espUptimeVal">--</div>
                  </div>
                </div>
              </div>
                <div class="esp-page" id="espPageInfo8">
                <div class="esp-hostname-page">
                  <div class="esp-page-hint"></div>
                  <div class="esp-hostname-card">
                    <div class="esp-hostname-value" id="espHostNameVal">Waiting for host...</div>
                  </div>
                </div>
              </div>
                <div class="esp-page" id="espPageSettings1">
                <div class="esp-settings1-page">
                  <div class="esp-page-hint"></div>
                  <div class="esp-settings1-label">Screen Brightness</div>
                  <div class="esp-settings1-slider">
                    <div class="esp-settings1-track">
                      <div class="esp-settings1-fill" id="espBrightnessFill"></div>
                      <div class="esp-settings1-knob" id="espBrightnessKnob"></div>
                    </div>
                  </div>
                  <div class="esp-settings1-value" id="espBrightnessVal">255</div>
                </div>
              </div>
                <div class="esp-page" id="espPageSettings2">
                <div class="esp-power-exact">
                  <div class="esp-page-hint"></div>
                  <div class="esp-power-status" id="espPowerStatusExact" hidden></div>
                  <div class="esp-power-btn shutdown">Shutdown</div>
                  <div class="esp-power-btn restart">Restart</div>
                </div>
              </div>
                <div class="esp-preview-modal" id="espDockerModal" hidden>
                <div class="esp-preview-modal-card">
                  <div class="esp-preview-modal-header">
                    <div class="esp-preview-modal-heading">
                      <span class="mdi mdi-docker"></span>
                      <div>
                        <div class="esp-preview-modal-title">Docker</div>
                        <div class="esp-preview-modal-subtitle">Container control</div>
                      </div>
                    </div>
                    <button class="esp-preview-modal-close" type="button" data-esp-modal-close="docker" aria-label="Close Docker preview">
                      <span class="mdi mdi-close"></span>
                    </button>
                  </div>
                  <div class="esp-preview-modal-body">
                    <div class="esp-preview-modal-name" id="espDockerModalName">--</div>
                    <div class="esp-state-pill other esp-preview-modal-status" id="espDockerModalStatus"></div>
                    <div class="esp-preview-modal-detail" id="espDockerModalDetail"></div>
                  </div>
                  <div class="esp-preview-modal-footer">
                    <button class="esp-modal-action start" type="button" data-esp-docker-action="start">Start</button>
                    <button class="esp-modal-action stop" type="button" data-esp-docker-action="stop">Stop</button>
                  </div>
                </div>
              </div>
                <div class="esp-preview-modal" id="espVmsModal" hidden>
                <div class="esp-preview-modal-card">
                  <div class="esp-preview-modal-header">
                    <div class="esp-preview-modal-heading">
                      <span class="mdi mdi-monitor-multiple"></span>
                      <div>
                        <div class="esp-preview-modal-title">VMS</div>
                        <div class="esp-preview-modal-subtitle">Virtual machine control</div>
                      </div>
                    </div>
                    <button class="esp-preview-modal-close" type="button" data-esp-modal-close="vms" aria-label="Close VM preview">
                      <span class="mdi mdi-close"></span>
                    </button>
                  </div>
                  <div class="esp-preview-modal-body">
                    <div class="esp-preview-modal-name" id="espVmsModalName">--</div>
                    <div class="esp-state-pill other esp-preview-modal-status" id="espVmsModalStatus"></div>
                    <div class="esp-preview-modal-detail" id="espVmsModalDetail"></div>
                  </div>
                  <div class="esp-preview-modal-footer">
                    <button class="esp-modal-action start" type="button" data-esp-vms-action="start">Start</button>
                    <button class="esp-modal-action stop" type="button" data-esp-vms-action="stop">Stop</button>
                    <button class="esp-modal-action restart" type="button" data-esp-vms-action="restart">Restart</button>
                  </div>
                  <div class="esp-preview-modal-footnote">Hold Stop on the device for force off</div>
                </div>
                </div>
              </div>
              </div>
            </div>
          </div>
          <div class="esp-preview-meta"><span id="espFooterPage">Preview • HOME</span><span id="espFooterPort">Port: --</span></div>
          <div class="monitor-note">Interactive browser simulator driven by live bridge telemetry. Swipe in the preview, click HOME quadrants, or long-press Docker and VM rows for actions.</div>
        </div>
      </section>
      <section class="mgroup span6"><h3><span class="gicon" aria-hidden="true"><span class="mdi mdi-chart-box-outline"></span></span>System</h3><div class="mgroup-grid">
        <div class="mcard" id="mcCPU"><div class="metric-label">CPU Usage</div><div class="metric-value" id="mvCPU">--</div><div class="metric-sub" id="msCPU"></div><svg id="sparkCPU"></svg></div>
        <div class="mcard" id="mcMEM"><div class="metric-label">Memory Usage</div><div class="metric-value" id="mvMEM">--</div><div class="metric-sub" id="msMEM"></div><svg id="sparkMEM"></svg></div>
        <div class="mcard" id="mcTEMP"><div class="metric-label">CPU Temperature</div><div class="metric-value" id="mvTEMP">--</div><div class="metric-sub" id="msTEMP"></div><svg id="sparkTEMP"></svg></div>
        <div class="mcard" id="mcUP"><div class="metric-label">Uptime</div><div class="metric-value" id="mvUP">--</div><div class="metric-sub" id="msUP"></div><svg id="sparkUP"></svg></div>
      </div></section>
      <section class="mgroup span6"><h3><span class="gicon" aria-hidden="true"><span class="mdi mdi-lan"></span></span>Network & Storage</h3><div class="mgroup-grid">
        <div class="mcard" id="mcNET"><div class="metric-label">Network RX / TX</div><div class="metric-value" id="mvNET">--</div><div class="metric-sub" id="msNET">kbps</div><svg id="sparkNET"></svg></div>
        <div class="mcard" id="mcDISKIO"><div class="metric-label">Disk Read / Write</div><div class="metric-value" id="mvDISKIO">--</div><div class="metric-sub" id="msDISKIO">kB/s</div><svg id="sparkDISKIO"></svg></div>
        <div class="mcard" id="mcDISKTEMP"><div class="metric-label">Disk Temperature</div><div class="metric-value" id="mvDISK">--</div><div class="metric-sub" id="msDISK"></div><svg id="sparkDISK"></svg></div>
        <div class="mcard" id="mcDISKPCT"><div class="metric-label">Disk Usage</div><div class="metric-value" id="mvDISKPCT">--</div><div class="metric-sub" id="msDISKPCT"></div><svg id="sparkDISKPCT"></svg></div>
      </div></section>
      <section class="mgroup span6"><h3><span class="gicon" aria-hidden="true"><span class="mdi mdi-fan"></span></span>Cooling & GPU</h3><div class="mgroup-grid">
        <div class="mcard" id="mcFAN"><div class="metric-label">Fan RPM</div><div class="metric-value" id="mvFAN">--</div><div class="metric-sub" id="msFAN"></div><svg id="sparkFAN"></svg></div>
        <div class="mcard" id="mcGPUU"><div class="metric-label">GPU Utilization</div><div class="metric-value" id="mvGPUU">--</div><div class="metric-sub" id="msGPUU"></div><svg id="sparkGPUU"></svg></div>
        <div class="mcard" id="mcGPUT"><div class="metric-label">GPU Temperature</div><div class="metric-value" id="mvGPUT">--</div><div class="metric-sub" id="msGPUT"></div><svg id="sparkGPUT"></svg></div>
        <div class="mcard" id="mcGPUVM"><div class="metric-label">GPU VRAM</div><div class="metric-value" id="mvGPUVM">--</div><div class="metric-sub" id="msGPUVM"></div><svg id="sparkGPUVM"></svg></div>
      </div></section>
      <section class="mgroup span6"><h3><span class="gicon" aria-hidden="true"><span class="mdi mdi-apps"></span></span>Workloads</h3><div class="mgroup-grid">
        <div class="mcard"><div class="metric-label">{workload_summary_label}</div><div class="metric-value" id="mvDockerCounts">--</div><div class="metric-sub" id="msDockerCounts">{workload_summary_sub}</div></div>
        <div class="mcard"><div class="metric-label">{vm_summary_label}</div><div class="metric-value" id="mvVmCounts">--</div><div class="metric-sub" id="msVmCounts">{vm_summary_sub}</div></div>
        <div class="mcard"><div class="metric-label">{workload_list_label}</div><div class="metric-sub" id="dockerMoreHint">{workload_waiting_text}</div><ul class="docker-list" id="dockerPreviewList"></ul><details><summary class="monitor-note">{workload_show_all}</summary><ul class="docker-list" id="dockerAllList"></ul></details></div>
        <div class="mcard"><div class="metric-label">{vm_list_label}</div><div class="metric-sub" id="vmMoreHint">{vm_waiting_text}</div><ul class="docker-list" id="vmPreviewList"></ul><details><summary class="monitor-note">{vm_show_all}</summary><ul class="docker-list" id="vmAllList"></ul></details></div>
      </div></section>
      <section class="mgroup span12"><h3><span class="gicon" aria-hidden="true"><span class="mdi mdi-puzzle-outline"></span></span>Integration Health</h3><div class="mgroup-grid">
        <div class="mcard">
          <div class="metric-label">Integrations</div>
          <div class="integration-health-list" id="integrationHealthList">
            <div class="monitor-note">Waiting for integration health...</div>
          </div>
        </div>
        <div class="mcard">
          <div class="metric-label">Command Registry</div>
          <div class="metric-sub" id="commandRegistryHint">Waiting for command registry...</div>
          <div class="command-registry-list" id="commandRegistryList"></div>
        </div>
      </div></section>
    </div>
  </div>
</div>
<script>
window.__HOST_METRICS_BOOT__ = {{
  nextLogId: {st['next_log_id']},
  nextCommLogId: {st.get('next_comm_log_id', 1)},
}};
</script>
<script src="/static/host/host_ui.js"></script>
"""
        return page_html("ESP Host Bridge", body)

    @app.post("/save")
    def save() -> Any:
        cfg = cfg_from_form(request.form)
        existing_cfg = load_cfg(cfg_path)
        cfg = preserve_secret_fields(cfg, existing_cfg)
        cfg["webui_session_secret"] = _clean_str(existing_cfg.get("webui_session_secret"), "")
        cfg["webui_password_hash"] = _clean_str(existing_cfg.get("webui_password_hash"), "")
        auth_enabled = _clean_bool(cfg.get("webui_auth_enabled"), False)
        submitted_password = _clean_str(request.form.get("webui_password"), "")
        if auth_enabled:
            if submitted_password:
                cfg["webui_password_hash"] = generate_password_hash(submitted_password)
            elif not cfg["webui_password_hash"]:
                return _redir("password is required when direct Web UI protection is enabled", key="err")
        else:
            cfg["webui_password_hash"] = ""
        cfg, secret_updated = ensure_webui_session_secret(cfg)
        ok, message = validate_cfg(cfg)
        if not ok:
            return _redir(message, key="err")
        atomic_write_json(cfg_path, cfg)
        if secret_updated:
            app.secret_key = str(cfg.get("webui_session_secret") or app.secret_key)
        restart = int(request.args.get("restart", "1"))
        if restart:
            ok_run, message_run = pub.restart(cfg)
            if not ok_run:
                return _redir(message_run, key="err")
            return redirect("/?msg=Saved+and+restarted")
        return redirect("/?msg=Saved")

    @app.post("/start")
    def start_proc() -> Any:
        cfg = load_cfg(cfg_path)
        ok, message = pub.start(cfg)
        return _redir(message, key="msg" if ok else "err")

    @app.post("/restart")
    def restart_proc() -> Any:
        cfg = load_cfg(cfg_path)
        ok, message = pub.restart(cfg)
        return _redir(message, key="msg" if ok else "err")

    @app.post("/stop")
    def stop_proc() -> Any:
        ok, message = pub.stop()
        return _redir(message, key="msg" if ok else "err")

    @app.get("/api/status")
    def api_status() -> Any:
        status = dict(pub.status())
        cmd = status.get("cmd")
        if isinstance(cmd, list):
            status["cmd"] = redact_agent_command_args(cmd, REDACTED_SECRET_TEXT)
        return jsonify(status)

    @app.get("/api/config")
    def api_config() -> Any:
        return jsonify(redact_cfg(load_cfg(cfg_path), REDACTED_SECRET_TEXT))

    @app.get("/api/ports")
    def api_ports() -> Any:
        return jsonify({"ports": list_serial_port_choices()})

    @app.get("/api/hardware-choices")
    def api_hardware_choices() -> Any:
        return jsonify(detect_hardware_choices())

    @app.post("/api/test-serial")
    def api_test_serial() -> Any:
        payload = request.get_json(silent=True) or {}
        if isinstance(payload, dict):
            port = payload.get("port")
            baud = payload.get("baud", 115200)
        else:
            port = None
            baud = 115200
        ok, message = test_serial_open(None if port is None else str(port), baud)
        return jsonify({"ok": ok, "message": message}), (200 if ok else 400)

    if not is_home_assistant_app_mode():
        @app.get("/api/host-power-defaults")
        def api_host_power_defaults() -> Any:
            return jsonify(build_host_power_command_defaults())

        @app.post("/api/host-power-preview")
        def api_host_power_preview() -> Any:
            payload = request.get_json(silent=True) or {}
            if not isinstance(payload, dict):
                payload = {}
            use_sudo = _clean_bool(payload.get("host_cmd_use_sudo"), False)
            shutdown_cmd = _clean_str(payload.get("shutdown_cmd"), "")
            restart_cmd = _clean_str(payload.get("restart_cmd"), "")
            return jsonify(
                {
                    "items": build_host_power_command_previews(
                        use_sudo=use_sudo,
                        shutdown_cmd=shutdown_cmd,
                        restart_cmd=restart_cmd,
                    )
                }
            )

    @app.get("/api/logs")
    def api_logs() -> Any:
        since = request.args.get("since", default="1")
        try:
            since_id = max(1, int(since))
        except ValueError:
            since_id = 1
        rows, next_id = pub.logs_since(since_id)
        return jsonify({"lines": rows, "next": next_id})

    @app.post("/api/logs/clear")
    def api_logs_clear() -> Any:
        pub.clear_logs()
        return jsonify({"ok": True, "message": "Logs cleared"})

    @app.get("/api/logs/text")
    def api_logs_text() -> Any:
        body = pub.logs_all_text() or "No logs yet. Start the agent or click Refresh to load recent output.\n"
        ts = time.strftime("%Y%m%d-%H%M%S")
        return Response(
            body,
            mimetype="text/plain",
            headers={"Content-Disposition": f'attachment; filename="esp-host-bridge-{ts}.log"'},
        )

    @app.get("/api/comm-logs")
    def api_comm_logs() -> Any:
        since = request.args.get("since", default="1")
        try:
            since_id = max(1, int(since))
        except ValueError:
            since_id = 1
        rows, next_id = pub.comm_logs_since(since_id)
        return jsonify({"lines": rows, "next": next_id})

    @app.post("/api/comm-logs/clear")
    def api_comm_logs_clear() -> Any:
        pub.clear_comm_logs()
        return jsonify({"ok": True, "message": "Communication logs cleared"})

    @app.get("/api/comm-logs/text")
    def api_comm_logs_text() -> Any:
        body = pub.comm_logs_all_text() or "No communication events yet. Serial disconnects/reconnects will appear here.\n"
        ts = time.strftime("%Y%m%d-%H%M%S")
        return Response(
            body,
            mimetype="text/plain",
            headers={"Content-Disposition": f'attachment; filename="esp-host-bridge-comm-{ts}.log"'},
        )


    @app.post("/api/start")
    def api_start() -> Any:
        payload = request.get_json(silent=True) or {}
        existing_cfg = load_cfg(cfg_path)
        cfg = normalize_cfg(payload) if isinstance(payload, dict) and payload else existing_cfg
        cfg = preserve_secret_fields(cfg, existing_cfg, include_builtin=True)
        cfg["webui_session_secret"] = _clean_str(existing_cfg.get("webui_session_secret"), "")
        cfg["webui_password_hash"] = _clean_str(existing_cfg.get("webui_password_hash"), "")
        ok_valid, msg_valid = validate_cfg(cfg)
        if not ok_valid:
            return jsonify({"ok": False, "message": msg_valid}), 400
        ok, message = pub.start(cfg)
        if ok and isinstance(payload, dict) and payload:
            atomic_write_json(cfg_path, cfg)
        return jsonify({"ok": ok, "message": message}), (200 if ok else 400)

    @app.post("/api/stop")
    def api_stop() -> Any:
        ok, message = pub.stop()
        return jsonify({"ok": ok, "message": message}), (200 if ok else 400)

    @app.post("/api/restart")
    def api_restart() -> Any:
        payload = request.get_json(silent=True) or {}
        existing_cfg = load_cfg(cfg_path)
        cfg = normalize_cfg(payload) if isinstance(payload, dict) and payload else existing_cfg
        cfg = preserve_secret_fields(cfg, existing_cfg, include_builtin=True)
        cfg["webui_session_secret"] = _clean_str(existing_cfg.get("webui_session_secret"), "")
        cfg["webui_password_hash"] = _clean_str(existing_cfg.get("webui_password_hash"), "")
        ok_valid, msg_valid = validate_cfg(cfg)
        if not ok_valid:
            return jsonify({"ok": False, "message": msg_valid}), 400
        if isinstance(payload, dict) and payload:
            atomic_write_json(cfg_path, cfg)
        ok, message = pub.restart(cfg)
        return jsonify({"ok": ok, "message": message}), (200 if ok else 400)

    def maybe_autostart() -> None:
        if not autostart:
            return
        cfg = load_cfg(cfg_path)
        ok, msg = validate_cfg(cfg)
        if not ok:
            pub.log_event(f"[autostart skipped] {msg}")
            return
        ok_start, message = pub.start(cfg)
        if ok_start:
            pub.log_event("[autostart enabled]")
        else:
            pub.log_event(f"[autostart skipped] {message}")

    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    if not cfg_path.exists():
        cfg_seed, _ = ensure_webui_session_secret(webui_default_cfg())
        atomic_write_json(cfg_path, cfg_seed)
    maybe_autostart()
    atexit.register(pub.stop_noexcept)
    return app

def run_webui(args: argparse.Namespace) -> int:
    app = create_app()
    port = int(args.port or os.environ.get("WEBUI_PORT", str(WEBUI_DEFAULT_PORT)))
    host = args.host or os.environ.get("WEBUI_HOST", "0.0.0.0")
    app.run(host=host, port=port, debug=False)
    return 0

def webui_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="esp-host-bridge webui")
    ap.add_argument("--host", default=None, help="Bind host (default from WEBUI_HOST or 0.0.0.0)")
    ap.add_argument("--port", type=int, default=None, help="Bind port (default from WEBUI_PORT or 8654)")
    return ap

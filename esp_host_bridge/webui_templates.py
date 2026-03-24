from __future__ import annotations

from typing import List


def render_mode_toggle_html(*, designer_enabled: bool, designer_only: bool) -> str:
    buttons: List[str] = []
    if not designer_only:
        buttons.append('<button id="viewSetupBtn" class="secondary" type="button">Setup Mode</button>')
        buttons.append('<button id="viewMonitorBtn" class="secondary" type="button">Monitor Mode</button>')
    if designer_enabled:
        buttons.append('<button id="viewDesignerBtn" class="secondary" type="button">Designer Mode</button>')
    if not buttons:
        return ""
    return '<div class="mode-toggle">' + "".join(buttons) + "</div>"


def render_topbar_subtitle(*, designer_only: bool) -> str:
    if designer_only:
        return "Design and apply ESPHome LVGL UI YAML"
    return "Configure, start, and monitor the host metrics agent"

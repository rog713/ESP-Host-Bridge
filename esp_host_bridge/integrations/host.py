from __future__ import annotations

import logging
from typing import Any, Dict

from ..metrics import (
    get_cpu_percent,
    get_cpu_temp_c,
    get_disk_bytes_local,
    get_disk_temp_c,
    get_disk_usage_pct,
    get_fan_rpm,
    get_gpu_metrics,
    get_mem_percent,
    get_net_bytes_local,
    get_uptime_seconds,
)
from .base import (
    CleanerSet,
    ConfigFieldSpec,
    DashboardCardSpec,
    DashboardGroupSpec,
    IntegrationSpec,
    PollContext,
    PreviewCardSpec,
    PreviewPageSpec,
    SetupActionSpec,
    SetupChoiceSpec,
)

HOST_WARN_INTERVAL_SECONDS = 30.0
DISK_TEMP_REFRESH_SECONDS = 15.0
DISK_USAGE_REFRESH_SECONDS = 10.0
SLOW_SENSOR_REFRESH_SECONDS = 5.0
HOST_POWER_COMMAND_IDS = ["host_shutdown", "host_restart"]

HOST_CONFIG_FIELDS = (
    ConfigFieldSpec(
        "iface",
        "str",
        "",
        cli_flag="--iface",
        label="Network Interface",
        hint="Optional. Leave blank to auto-detect, or set a name like <code>eth0</code>/<code>br0</code>.",
        section_key="telemetry_sources",
        input_id="ifaceInput",
    ),
    ConfigFieldSpec(
        "disk_device",
        "str",
        "",
        cli_flag="--disk-device",
        label="Disk Device",
        hint="Optional. Set a device path like <code>/dev/sda</code> if auto-detection is not correct.",
        section_key="telemetry_sources",
        input_id="diskDeviceInput",
    ),
    ConfigFieldSpec(
        "disk_temp_device",
        "str",
        "",
        cli_flag="--disk-temp-device",
        label="Disk Temp Device",
        hint="Optional override for temperature checks (for example <code>/dev/nvme0</code> or <code>/dev/sda</code>).",
        section_key="telemetry_sources",
        input_id="diskTempDeviceInput",
    ),
    ConfigFieldSpec(
        "cpu_temp_sensor",
        "str",
        "",
        cli_flag="--cpu-temp-sensor",
        label="CPU Temp Sensor",
        hint="Optional. Leave blank for auto CPU temp detection, or choose a detected sensor below.",
        section_key="telemetry_sources",
        input_id="cpuTempSensorInput",
        chip_id="cpuTempSensorChip",
    ),
    ConfigFieldSpec(
        "gpu_polling_enabled",
        "bool",
        True,
        checkbox=True,
        label="Enable GPU Metrics",
        hint="Turn GPU temperature, utilization, and VRAM polling on or off without affecting other telemetry.",
        section_key="telemetry_sources",
    ),
    ConfigFieldSpec(
        "fan_sensor",
        "str",
        "",
        cli_flag="--fan-sensor",
        label="Fan Sensor",
        hint="Optional. Leave blank for auto fan detection, or choose a detected sensor below.",
        section_key="telemetry_sources",
        input_id="fanSensorInput",
        chip_id="fanSensorChip",
    ),
)

HOST_SETUP_CHOICES = (
    SetupChoiceSpec(
        label="Detected Interfaces",
        section_key="telemetry_sources",
        select_id="ifaceSelect",
        placeholder="(click Refresh Interfaces)",
        refresh_button_id="refreshIfaceBtn",
        refresh_button_label="Refresh Interfaces",
        result_id="ifaceResult",
        buttons=(SetupActionSpec("useIfaceBtn", "Use Interface"),),
    ),
    SetupChoiceSpec(
        label="Detected Disk Devices",
        section_key="telemetry_sources",
        select_id="diskDeviceSelect",
        placeholder="(click Refresh Disks)",
        refresh_button_id="refreshDiskBtn",
        refresh_button_label="Refresh Disks",
        result_id="diskResult",
        buttons=(
            SetupActionSpec("useDiskBtn", "Use for Disk"),
            SetupActionSpec("useDiskTempBtn", "Use for Temp"),
            SetupActionSpec("useDiskBothBtn", "Use for Both"),
        ),
    ),
    SetupChoiceSpec(
        label="Detected CPU Temp Sensors",
        section_key="telemetry_sources",
        select_id="cpuTempSensorSelect",
        placeholder="(click Refresh CPU Temp Sensors)",
        refresh_button_id="refreshCpuTempSensorBtn",
        refresh_button_label="Refresh CPU Temp Sensors",
        result_id="cpuTempSensorResult",
        buttons=(SetupActionSpec("useCpuTempSensorBtn", "Use Sensor"),),
    ),
    SetupChoiceSpec(
        label="Detected Fan Sensors",
        section_key="telemetry_sources",
        select_id="fanSensorSelect",
        placeholder="(click Refresh Fan Sensors)",
        refresh_button_id="refreshFanSensorBtn",
        refresh_button_label="Refresh Fan Sensors",
        result_id="fanSensorResult",
        buttons=(SetupActionSpec("useFanSensorBtn", "Use Sensor"),),
    ),
)

HOST_DASHBOARD_GROUPS = (
    DashboardGroupSpec(
        group_id="host_system",
        title="System",
        icon_class="mdi-chart-box-outline",
        cards=(
            DashboardCardSpec(
                card_id="CPU",
                label="CPU Usage",
                render_kind="percent_one_decimal",
                metric_key="CPU",
                subtext="Current load",
                severity_kind="cpu_pct",
                spark_keys=("CPU",),
                spark_color="#60a5fa",
            ),
            DashboardCardSpec(
                card_id="MEM",
                label="Memory Usage",
                render_kind="percent_one_decimal",
                metric_key="MEM",
                subtext="Used memory",
                severity_kind="mem_pct",
                spark_keys=("MEM",),
                spark_color="#34d399",
            ),
            DashboardCardSpec(
                card_id="TEMP",
                label="CPU Temperature",
                render_kind="temp_one_decimal",
                metric_key="TEMP",
                subtext="CPU sensor",
                severity_kind="cpu_temp",
                spark_keys=("TEMP",),
                spark_color="#fb923c",
            ),
            DashboardCardSpec(
                card_id="UP",
                label="Uptime",
                render_kind="uptime",
                metric_key="UP",
                severity_kind="always_ok",
                spark_keys=("UP",),
                spark_color="#a78bfa",
            ),
        ),
    ),
    DashboardGroupSpec(
        group_id="host_network_storage",
        title="Network & Storage",
        icon_class="mdi-lan",
        cards=(
            DashboardCardSpec(
                card_id="NET",
                label="Network RX / TX",
                render_kind="pair_round",
                metric_key="RX",
                secondary_metric_key="TX",
                subtext="RX / TX kbps",
                severity_kind="traffic_pair",
                spark_keys=("RX", "TX"),
                spark_color="#22d3ee",
            ),
            DashboardCardSpec(
                card_id="DISKIO",
                label="Disk Read / Write",
                render_kind="pair_round",
                metric_key="DISKR",
                secondary_metric_key="DISKW",
                subtext="Read / Write kB/s",
                severity_kind="disk_io_pair",
                spark_keys=("DISKR", "DISKW"),
                spark_color="#f472b6",
            ),
            DashboardCardSpec(
                card_id="DISK",
                label="Disk Temperature",
                render_kind="disk_temp_usage",
                metric_key="DISK",
                secondary_metric_key="DISKPCT",
                subtext="Temperature / Usage",
                severity_kind="disk_temp",
                spark_keys=("DISK",),
                spark_color="#f59e0b",
            ),
            DashboardCardSpec(
                card_id="DISKPCT",
                label="Disk Usage",
                render_kind="percent_one_decimal",
                metric_key="DISKPCT",
                subtext="Disk usage",
                severity_kind="disk_usage",
                spark_keys=("DISKPCT",),
                spark_color="#10b981",
            ),
        ),
    ),
    DashboardGroupSpec(
        group_id="host_cooling_gpu",
        title="Cooling & GPU",
        icon_class="mdi-fan",
        cards=(
            DashboardCardSpec(
                card_id="FAN",
                label="Fan RPM",
                render_kind="integer",
                metric_key="FAN",
                subtext="RPM",
                severity_kind="always_ok",
                spark_keys=("FAN",),
                spark_color="#fbbf24",
            ),
            DashboardCardSpec(
                card_id="GPUU",
                label="GPU Utilization",
                render_kind="integer_percent",
                metric_key="GPUU",
                subtext="GPU utilization",
                severity_kind="gpu_util",
                spark_keys=("GPUU",),
                spark_color="#38bdf8",
            ),
            DashboardCardSpec(
                card_id="GPUT",
                label="GPU Temperature",
                render_kind="temp_one_decimal",
                metric_key="GPUT",
                subtext="GPU temp",
                severity_kind="gpu_temp",
                spark_keys=("GPUT",),
                spark_color="#fb7185",
            ),
            DashboardCardSpec(
                card_id="GPUVM",
                label="GPU VRAM",
                render_kind="integer_percent",
                metric_key="GPUVM",
                subtext="VRAM usage",
                severity_kind="gpu_mem",
                spark_keys=("GPUVM",),
                spark_color="#c084fc",
            ),
        ),
    ),
)

HOST_PREVIEW_CARDS = (
    PreviewCardSpec(
        card_id="CPU",
        label="CPU",
        icon_class="mdi-cpu-64-bit",
        render_kind="percent_metric",
        subtext="Usage",
        metric_key="CPU",
    ),
    PreviewCardSpec(
        card_id="MEM",
        label="Memory",
        icon_class="mdi-memory",
        render_kind="percent_metric",
        subtext="Used",
        metric_key="MEM",
    ),
    PreviewCardSpec(
        card_id="TEMP",
        label="CPU Temp",
        icon_class="mdi-thermometer",
        render_kind="temp_metric",
        subtext="Sensor",
        metric_key="TEMP",
    ),
    PreviewCardSpec(
        card_id="NET",
        label="Network",
        icon_class="mdi-lan",
        render_kind="pair_metric",
        subtext="RX / TX",
        metric_key="RX",
        secondary_metric_key="TX",
    ),
    PreviewCardSpec(
        card_id="DISK",
        label="Disk",
        icon_class="mdi-harddisk",
        render_kind="disk_temp_usage",
        subtext="Temp / Usage",
        metric_key="DISK",
        secondary_metric_key="DISKPCT",
    ),
)

HOST_PREVIEW_PAGES = (
    PreviewPageSpec(
        page_id="home",
        dom_id="espPageHome",
        preview_order=0,
        render_kind="home",
        title="HOME",
        footer="HOME",
        tab_label="Home",
        tab_icon_class="mdi-home-outline",
    ),
    PreviewPageSpec(
        page_id="settings_1",
        dom_id="espPageSettings1",
        preview_order=2,
        render_kind="brightness",
        title="Settings",
        footer="Settings 1",
        render_data={
            "label": "Screen Brightness",
            "fill_id": "espBrightnessFill",
            "knob_id": "espBrightnessKnob",
            "value_id": "espBrightnessVal",
        },
        tab_label="Settings 1",
        tab_icon_class="mdi-brightness-6",
        indicator_count=2,
        indicator_index=1,
        nav_up="home",
        nav_left="settings_2",
        nav_right="settings_2",
        home_button_position="br",
        home_button_title="Settings",
        home_button_icon_class="mdi-cog-outline",
    ),
    PreviewPageSpec(
        page_id="settings_2",
        dom_id="espPageSettings2",
        preview_order=3,
        render_kind="power",
        title="Settings",
        footer="Settings 2",
        render_data={
            "status_id": "espPowerStatusExact",
        },
        tab_label="Settings 2",
        tab_icon_class="mdi-power",
        indicator_count=2,
        indicator_index=2,
        nav_up="home",
        nav_left="settings_1",
        nav_right="settings_1",
    ),
    PreviewPageSpec(
        page_id="info_1",
        dom_id="espPageInfo1",
        preview_order=4,
        render_kind="dual_metric_graph",
        title="NETWORK",
        footer="Info 1 • Network",
        render_data={
            "left_label": "RX",
            "left_value_id": "espNetRxVal",
            "left_unit": "MB/s",
            "left_dot_class": "left",
            "right_label": "TX",
            "right_value_id": "espNetTxVal",
            "right_unit": "MB/s",
            "right_dot_class": "right",
            "graph_id": "espNetGraph",
            "loading_id": "espNetLoading",
        },
        tab_label="Network",
        tab_icon_class="mdi-access-point-network",
        indicator_count=8,
        indicator_index=1,
        nav_up="home",
        nav_left="info_2",
        nav_right="info_8",
        home_button_position="bl",
        home_button_title="Info",
        home_button_icon_class="mdi-information-outline",
    ),
    PreviewPageSpec(
        page_id="info_2",
        dom_id="espPageInfo2",
        preview_order=5,
        render_kind="system_graph",
        title="SYSTEM",
        footer="Info 2 • System",
        render_data={
            "left_label": "CPU",
            "left_value_id": "espSysCpuVal",
            "left_unit": "%",
            "right_label": "MEMORY",
            "right_value_id": "espSysMemVal",
            "right_unit": "%",
            "graph_id": "espSysGraph",
            "loading_id": "espSysLoading",
        },
        tab_label="System",
        tab_icon_class="mdi-monitor-dashboard",
        indicator_count=8,
        indicator_index=2,
        nav_up="home",
        nav_left="info_3",
        nav_right="info_1",
    ),
    PreviewPageSpec(
        page_id="info_3",
        dom_id="espPageInfo3",
        preview_order=6,
        render_kind="metric_graph",
        title="CPU TEMP",
        footer="Info 3 • CPU Temp",
        render_data={
            "dot_class": "",
            "metric_title": "CPU TEMP",
            "value_id": "espCpuTempVal",
            "unit": "°C",
            "graph_id": "espCpuTempGraph",
            "loading_id": "espCpuTempLoading",
        },
        tab_label="CPU Temp",
        tab_icon_class="mdi-thermometer",
        indicator_count=8,
        indicator_index=3,
        nav_up="home",
        nav_left="info_4",
        nav_right="info_2",
    ),
    PreviewPageSpec(
        page_id="info_4",
        dom_id="espPageInfo4",
        preview_order=7,
        render_kind="metric_graph",
        title="DISK TEMP",
        footer="Info 4 • Disk Temp",
        render_data={
            "dot_class": " violet",
            "value_class": " violet",
            "metric_title": "DISK TEMP",
            "value_id": "espDiskTempVal",
            "unit": "°C",
            "graph_id": "espDiskTempGraph",
            "loading_id": "espDiskTempLoading",
        },
        tab_label="Disk Temp",
        tab_icon_class="mdi-harddisk",
        indicator_count=8,
        indicator_index=4,
        nav_up="home",
        nav_left="info_5",
        nav_right="info_3",
    ),
    PreviewPageSpec(
        page_id="info_5",
        dom_id="espPageInfo5",
        preview_order=8,
        render_kind="metric_graph",
        title="DISK USAGE",
        footer="Info 5 • Disk Usage",
        render_data={
            "dot_class": "",
            "metric_title": "DISK USAGE",
            "value_id": "espDiskUsageVal",
            "unit": "%",
            "graph_id": "espDiskUsageGraph",
            "loading_id": "espDiskUsageLoading",
        },
        tab_label="Disk Usage",
        tab_icon_class="mdi-chart-donut",
        indicator_count=8,
        indicator_index=5,
        nav_up="home",
        nav_left="info_6",
        nav_right="info_4",
    ),
    PreviewPageSpec(
        page_id="info_6",
        dom_id="espPageInfo6",
        preview_order=9,
        render_kind="dual_metric_graph",
        title="GPU",
        footer="Info 6 • GPU",
        render_data={
            "left_label": "GPU",
            "left_value_id": "espGpuUtilVal",
            "left_unit": "%",
            "left_dot_class": "left",
            "right_label": "TEMP",
            "right_value_id": "espGpuTempVal",
            "right_unit": "°C",
            "right_dot_class": "right",
            "graph_id": "espGpuGraph",
            "loading_id": "espGpuLoading",
        },
        tab_label="GPU",
        tab_icon_class="mdi-graph-line",
        indicator_count=8,
        indicator_index=6,
        nav_up="home",
        nav_left="info_7",
        nav_right="info_5",
    ),
    PreviewPageSpec(
        page_id="info_7",
        dom_id="espPageInfo7",
        preview_order=10,
        render_kind="uptime",
        title="UPTIME",
        footer="Info 7 • Uptime",
        render_data={
            "status_id": "espUptimeStatus",
            "value_id": "espUptimeVal",
        },
        tab_label="Uptime",
        tab_icon_class="mdi-timer-outline",
        indicator_count=8,
        indicator_index=7,
        nav_up="home",
        nav_left="info_8",
        nav_right="info_6",
    ),
    PreviewPageSpec(
        page_id="info_8",
        dom_id="espPageInfo8",
        preview_order=11,
        render_kind="hostname",
        title="HOST NAME",
        footer="Info 8 • Host Name",
        render_data={
            "value_id": "espHostNameVal",
            "waiting_text": "Waiting for host...",
        },
        tab_label="Host Name",
        tab_icon_class="mdi-card-text-outline",
        indicator_count=8,
        indicator_index=8,
        nav_up="home",
        nav_left="info_1",
        nav_right="info_7",
    ),
)


def _cache(state: Any) -> Dict[str, Any]:
    integration_cache = getattr(state, "integration_cache", None)
    if not isinstance(integration_cache, dict):
        integration_cache = {}
        setattr(state, "integration_cache", integration_cache)
    cached = integration_cache.get("host")
    if not isinstance(cached, dict):
        cached = {
            "metrics": {
                "cpu_pct": 0.0,
                "mem_pct": 0.0,
                "uptime_s": 0.0,
                "cpu_temp_c": 0.0,
                "cpu_temp_available": False,
                "disk_temp_c": 0.0,
                "disk_temp_available": False,
                "disk_usage_pct": 0.0,
                "fan_rpm": 0.0,
                "fan_available": False,
                "gpu_temp_c": 0.0,
                "gpu_util_pct": 0.0,
                "gpu_mem_pct": 0.0,
                "gpu_available": False,
                "gpu_enabled": True,
                "rx_kbps": 0.0,
                "tx_kbps": 0.0,
                "disk_r_kbs": 0.0,
                "disk_w_kbs": 0.0,
                "active_iface": "",
                "active_disk": "",
            },
            "last_refresh_ts": 0.0,
            "last_success_ts": 0.0,
            "last_warn_ts": 0.0,
            "last_error": "",
            "last_error_ts": 0.0,
            "available": None,
        }
        integration_cache["host"] = cached
    return cached


def cfg_to_agent_args(cfg: Dict[str, Any], clean: CleanerSet) -> list[str]:
    argv: list[str] = []
    for key, flag in (
        ("iface", "--iface"),
        ("disk_device", "--disk-device"),
        ("disk_temp_device", "--disk-temp-device"),
        ("cpu_temp_sensor", "--cpu-temp-sensor"),
        ("fan_sensor", "--fan-sensor"),
    ):
        value = clean.clean_str(cfg.get(key), "")
        if value:
            argv += [flag, value]
    if not clean.clean_bool(cfg.get("gpu_polling_enabled"), True):
        argv.append("--disable-gpu-polling")
    return argv


def poll(ctx: PollContext) -> Dict[str, Any]:
    cache = _cache(ctx.state)
    state = ctx.state
    try:
        cpu_pct, state.cpu_prev_total, state.cpu_prev_idle = get_cpu_percent(state.cpu_prev_total, state.cpu_prev_idle)
        mem_pct = get_mem_percent()
        uptime_s = get_uptime_seconds()
        cpu_temp_sample = get_cpu_temp_c(getattr(ctx.args, "cpu_temp_sensor", None))
        cpu_temp_available = cpu_temp_sample is not None
        cpu_temp_c = float(cpu_temp_sample or 0.0)

        if (ctx.now - float(getattr(state, "last_disk_temp_ts", 0.0) or 0.0)) >= DISK_TEMP_REFRESH_SECONDS:
            disk_temp_sample = get_disk_temp_c(ctx.args.timeout, ctx.args.disk_temp_device or ctx.args.disk_device)
            state.disk_temp_c = float(disk_temp_sample or 0.0)
            state.disk_temp_available = disk_temp_sample is not None
            state.last_disk_temp_ts = ctx.now

        if (ctx.now - float(getattr(state, "last_disk_usage_ts", 0.0) or 0.0)) >= DISK_USAGE_REFRESH_SECONDS:
            state.disk_usage_pct = get_disk_usage_pct(ctx.args.disk_device, state.active_disk)
            state.last_disk_usage_ts = ctx.now

        gpu_enabled = not bool(getattr(ctx.args, "disable_gpu_polling", False))
        if (ctx.now - float(getattr(state, "last_slow_sensor_ts", 0.0) or 0.0)) >= SLOW_SENSOR_REFRESH_SECONDS:
            fan_rpm_sample = get_fan_rpm(getattr(ctx.args, "fan_sensor", None))
            state.fan_rpm = float(fan_rpm_sample or 0.0)
            state.fan_available = fan_rpm_sample is not None
            if gpu_enabled:
                gpu = get_gpu_metrics(ctx.args.timeout)
                state.gpu_temp_c = float(gpu.get("temp_c", 0.0) or 0.0)
                state.gpu_util_pct = float(gpu.get("util_pct", 0.0) or 0.0)
                state.gpu_mem_pct = float(gpu.get("mem_pct", 0.0) or 0.0)
                state.gpu_available = bool(gpu.get("available", False))
            else:
                state.gpu_temp_c = 0.0
                state.gpu_util_pct = 0.0
                state.gpu_mem_pct = 0.0
                state.gpu_available = False
            state.last_slow_sensor_ts = ctx.now

        rx_bytes, tx_bytes, state.active_iface = get_net_bytes_local(ctx.args.iface, state.active_iface)
        rx_kbps = 0.0
        tx_kbps = 0.0
        dt = 0.0
        if state.prev_t is not None and ctx.now > state.prev_t:
            dt = ctx.now - state.prev_t
            if state.prev_rx is not None and rx_bytes >= state.prev_rx:
                rx_kbps = ((rx_bytes - state.prev_rx) * 8.0) / 1000.0 / dt
            if state.prev_tx is not None and tx_bytes >= state.prev_tx:
                tx_kbps = ((tx_bytes - state.prev_tx) * 8.0) / 1000.0 / dt

        disk_read_b, disk_write_b, state.active_disk = get_disk_bytes_local(ctx.args.disk_device, state.active_disk)
        disk_r_kbs = 0.0
        disk_w_kbs = 0.0
        if dt > 0.0:
            if state.prev_disk_read_b is not None and disk_read_b >= state.prev_disk_read_b:
                disk_r_kbs = (disk_read_b - state.prev_disk_read_b) / 1024.0 / dt
            if state.prev_disk_write_b is not None and disk_write_b >= state.prev_disk_write_b:
                disk_w_kbs = (disk_write_b - state.prev_disk_write_b) / 1024.0 / dt

        state.prev_disk_read_b, state.prev_disk_write_b = disk_read_b, disk_write_b
        state.prev_rx, state.prev_tx, state.prev_t = rx_bytes, tx_bytes, ctx.now

        metrics = {
            "cpu_pct": float(cpu_pct),
            "mem_pct": float(mem_pct),
            "uptime_s": float(uptime_s),
            "cpu_temp_c": cpu_temp_c,
            "cpu_temp_available": bool(cpu_temp_available),
            "disk_temp_c": float(getattr(state, "disk_temp_c", 0.0) or 0.0),
            "disk_temp_available": bool(getattr(state, "disk_temp_available", False)),
            "disk_usage_pct": float(getattr(state, "disk_usage_pct", 0.0) or 0.0),
            "fan_rpm": float(getattr(state, "fan_rpm", 0.0) or 0.0),
            "fan_available": bool(getattr(state, "fan_available", False)),
            "gpu_temp_c": float(getattr(state, "gpu_temp_c", 0.0) or 0.0),
            "gpu_util_pct": float(getattr(state, "gpu_util_pct", 0.0) or 0.0),
            "gpu_mem_pct": float(getattr(state, "gpu_mem_pct", 0.0) or 0.0),
            "gpu_available": bool(getattr(state, "gpu_available", False)),
            "gpu_enabled": bool(gpu_enabled),
            "rx_kbps": float(rx_kbps),
            "tx_kbps": float(tx_kbps),
            "disk_r_kbs": float(disk_r_kbs),
            "disk_w_kbs": float(disk_w_kbs),
            "active_iface": str(state.active_iface or ""),
            "active_disk": str(state.active_disk or ""),
        }
        cache["metrics"] = metrics
        cache["available"] = True
        cache["last_success_ts"] = ctx.now
        cache["last_error"] = ""
        cache["last_error_ts"] = 0.0
    except Exception as exc:
        metrics = dict(cache.get("metrics") or {})
        cache["available"] = False
        cache["last_error"] = str(exc).strip()[:200]
        cache["last_error_ts"] = ctx.now
        last_warn_ts = float(cache.get("last_warn_ts") or 0.0)
        if (ctx.now - last_warn_ts) >= HOST_WARN_INTERVAL_SECONDS:
            logging.warning("host metrics unavailable; reusing previous host telemetry (%s)", exc)
            cache["last_warn_ts"] = ctx.now

    cache["last_refresh_ts"] = ctx.now
    last_refresh_ts = float(cache.get("last_refresh_ts") or 0.0)
    last_success_ts = float(cache.get("last_success_ts") or 0.0)
    last_error_ts = float(cache.get("last_error_ts") or 0.0)
    last_error = str(cache.get("last_error") or "").strip()
    return {
        "enabled": True,
        "metrics": dict(cache.get("metrics") or metrics),
        "health": {
            "integration_id": "host",
            "enabled": True,
            "available": cache.get("available"),
            "source": "local_probes",
            "last_refresh_ts": last_refresh_ts or None,
            "last_success_ts": last_success_ts or None,
            "last_error": last_error or None,
            "last_error_ts": last_error_ts or None,
            "commands": list(HOST_POWER_COMMAND_IDS),
            "api_ok": None,
        },
    }


HOST_INTEGRATION = IntegrationSpec(
    integration_id="host",
    title="Telemetry Sources",
    section_key="telemetry_sources",
    icon_class="mdi-chip",
    sort_order=0,
    action_group_title="Host Power",
    config_fields=HOST_CONFIG_FIELDS,
    setup_choices=HOST_SETUP_CHOICES,
    dashboard_groups=HOST_DASHBOARD_GROUPS,
    cfg_to_agent_args=cfg_to_agent_args,
    preview_cards=HOST_PREVIEW_CARDS,
    preview_pages=HOST_PREVIEW_PAGES,
    poll=poll,
)

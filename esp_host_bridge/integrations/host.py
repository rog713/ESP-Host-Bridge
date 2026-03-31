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
from .base import CleanerSet, ConfigFieldSpec, IntegrationSpec, PollContext

HOST_WARN_INTERVAL_SECONDS = 30.0
DISK_TEMP_REFRESH_SECONDS = 15.0
DISK_USAGE_REFRESH_SECONDS = 10.0
SLOW_SENSOR_REFRESH_SECONDS = 5.0
HOST_POWER_COMMAND_IDS = ["host_shutdown", "host_restart"]

HOST_CONFIG_FIELDS = (
    ConfigFieldSpec("iface", "str", "", cli_flag="--iface"),
    ConfigFieldSpec("gpu_polling_enabled", "bool", True, checkbox=True),
    ConfigFieldSpec("disk_device", "str", "", cli_flag="--disk-device"),
    ConfigFieldSpec("disk_temp_device", "str", "", cli_flag="--disk-temp-device"),
    ConfigFieldSpec("cpu_temp_sensor", "str", "", cli_flag="--cpu-temp-sensor"),
    ConfigFieldSpec("fan_sensor", "str", "", cli_flag="--fan-sensor"),
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
    config_fields=HOST_CONFIG_FIELDS,
    cfg_to_agent_args=cfg_to_agent_args,
    poll=poll,
)

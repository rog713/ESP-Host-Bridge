#!/usr/bin/env python3
from __future__ import annotations

import atexit
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

if __package__ in {None, ""}:
    package_root = str(Path(__file__).resolve().parent.parent)
    script_dir = str(Path(__file__).resolve().parent)
    sys.path = [p for p in sys.path if os.path.abspath(p or ".") != script_dir]
    sys.path.insert(0, package_root)
    from esp_host_bridge import cli as app_cli  # type: ignore
    from esp_host_bridge import config as cfg_mod  # type: ignore
    from esp_host_bridge import metrics as metrics_mod  # type: ignore
    from esp_host_bridge import runtime as hm  # type: ignore
    from esp_host_bridge import serial as serial_mod  # type: ignore
else:
    from . import cli as app_cli
    from . import config as cfg_mod
    from . import metrics as metrics_mod
    from . import runtime as hm
    from . import serial as serial_mod

_ORIG_GET_CPU_TEMP_C = metrics_mod.get_cpu_temp_c
_ORIG_GET_FAN_RPM = metrics_mod.get_fan_rpm
_ORIG_GET_GPU_METRICS = metrics_mod.get_gpu_metrics
_ORIG_GET_VIRTUAL_MACHINES_FROM_VIRSH = metrics_mod.get_virtual_machines_from_virsh
_ORIG_EXECUTE_VIRSH_COMMAND = hm.execute_virsh_command
_ORIG_WEBUI_DEFAULT_CFG = cfg_mod.webui_default_cfg
_ORIG_LIST_CPU_TEMP_SENSOR_CHOICES = metrics_mod.list_cpu_temp_sensor_choices
_ORIG_LIST_FAN_SENSOR_CHOICES = metrics_mod.list_fan_sensor_choices
_ORIG_LIST_SERIAL_PORT_CHOICES = serial_mod.list_serial_port_choices
_ORIG_LIST_DISK_DEVICE_CHOICES = metrics_mod.list_disk_device_choices

_MACMON_CACHE_LOCK = threading.Lock()
_MACMON_CACHE_DATA: Dict[str, float] = {}
_MACMON_CACHE_TS = 0.0
_MACMON_THREAD_LOCK = threading.Lock()
_MACMON_THREAD_STARTED = False
_MACMON_STOP_EVENT = threading.Event()
_MACMON_PROC: Optional[subprocess.Popen[str]] = None


def _macmon_cmd_candidates() -> list[list[str]]:
    return [
        ["macmon", "pipe", "--samples", "0", "--interval", "1000"],
        ["/opt/homebrew/bin/macmon", "pipe", "--samples", "0", "--interval", "1000"],
    ]


def _extract_macmon_metrics(row: Dict[str, Any]) -> Dict[str, float]:
    data: Dict[str, float] = {}
    temp = row.get("temp")
    if isinstance(temp, dict):
        ct = hm.safe_float(temp.get("cpu_temp_avg"), None)
        gt = hm.safe_float(temp.get("gpu_temp_avg"), None)
        if ct is not None and 0.0 < float(ct) <= 150.0:
            data["cpu_temp_c"] = float(ct)
        if gt is not None and 0.0 < float(gt) <= 150.0:
            data["gpu_temp_c"] = float(gt)

    gpu_usage = row.get("gpu_usage")
    # macmon reports [freq_mhz, utilization_ratio]
    if isinstance(gpu_usage, (list, tuple)) and len(gpu_usage) >= 2:
        ratio = hm.safe_float(gpu_usage[1], None)
        if ratio is not None:
            data["gpu_util_pct"] = max(0.0, min(100.0, float(ratio) * 100.0))

    # Some versions may expose fan info under a dedicated key.
    fan_val = None
    for key in ("fan_rpm", "fan_speed", "fan"):
        fan_val = hm.safe_float(row.get(key), None)
        if fan_val is not None:
            break
    if fan_val is not None and float(fan_val) >= 0.0:
        data["fan_rpm"] = float(fan_val)
    return data


def _set_macmon_cache(data: Dict[str, float]) -> None:
    global _MACMON_CACHE_TS, _MACMON_CACHE_DATA
    with _MACMON_CACHE_LOCK:
        _MACMON_CACHE_DATA = dict(data)
        _MACMON_CACHE_TS = time.time()


def _macmon_reader_loop() -> None:
    global _MACMON_PROC
    while not _MACMON_STOP_EVENT.is_set():
        proc: Optional[subprocess.Popen[str]] = None
        try:
            for cmd in _macmon_cmd_candidates():
                try:
                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        text=True,
                        bufsize=1,
                        start_new_session=(os.name != "nt"),
                    )
                    break
                except Exception:
                    proc = None
            if proc is None:
                time.sleep(2.0)
                continue

            _MACMON_PROC = proc
            assert proc.stdout is not None
            for raw in proc.stdout:
                if _MACMON_STOP_EVENT.is_set():
                    break
                line = (raw or "").strip()
                if not line.startswith("{"):
                    continue
                try:
                    row = hm.json.loads(line)
                except Exception:
                    continue
                if not isinstance(row, dict):
                    continue
                _set_macmon_cache(_extract_macmon_metrics(row))

            try:
                proc.wait(timeout=0.2)
            except Exception:
                pass
        except Exception:
            pass
        finally:
            _MACMON_PROC = None
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass
        if not _MACMON_STOP_EVENT.is_set():
            time.sleep(1.0)


def _ensure_macmon_reader_started() -> None:
    global _MACMON_THREAD_STARTED
    with _MACMON_THREAD_LOCK:
        if _MACMON_THREAD_STARTED:
            return
        _MACMON_THREAD_STARTED = True
        threading.Thread(target=_macmon_reader_loop, name="macmon-reader", daemon=True).start()


def _stop_macmon_reader() -> None:
    _MACMON_STOP_EVENT.set()
    proc = _MACMON_PROC
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except Exception:
            pass


def _parse_macmon() -> Dict[str, float]:
    _ensure_macmon_reader_started()
    with _MACMON_CACHE_LOCK:
        return dict(_MACMON_CACHE_DATA)


def mac_get_cpu_temp_c(sensor_hint: Optional[str] = None) -> float:
    hint = (sensor_hint or "").strip().lower()
    try:
        mm = _parse_macmon()
        mm_cpu = hm.safe_float(mm.get("cpu_temp_c"), None)
        if hint.startswith("macmon:"):
            return float(mm_cpu or 0.0)
        if mm_cpu is not None and mm_cpu > 0:
            return float(mm_cpu)
    except Exception:
        pass
    return _ORIG_GET_CPU_TEMP_C(sensor_hint)


def mac_get_fan_rpm(sensor_hint: Optional[str] = None) -> float:
    hint = (sensor_hint or "").strip().lower()
    try:
        mm = _parse_macmon()
        mm_fan = hm.safe_float(mm.get("fan_rpm"), None)
        if hint.startswith("macmon:"):
            return float(mm_fan or 0.0)
        if mm_fan is not None and mm_fan >= 0:
            return float(mm_fan)
    except Exception:
        pass
    return _ORIG_GET_FAN_RPM(sensor_hint)


def mac_get_gpu_metrics(timeout: float) -> Dict[str, float]:
    out = _ORIG_GET_GPU_METRICS(timeout)
    try:
        mm = _parse_macmon()
        t = hm.safe_float(mm.get("gpu_temp_c"), None)
        u = hm.safe_float(mm.get("gpu_util_pct"), None)
        if t is not None and t > 0:
            out["temp_c"] = float(t)
        if u is not None and u >= 0:
            out["util_pct"] = max(0.0, min(100.0, float(u)))
        # macmon output does not expose VRAM usage in a stable/portable field.
    except Exception:
        pass
    return out


def _virsh_binary_available(virsh_binary: str) -> bool:
    vb = (virsh_binary or "virsh").strip()
    if not vb:
        vb = "virsh"
    if os.path.isabs(vb):
        return os.path.exists(vb) and os.access(vb, os.X_OK)
    return shutil.which(vb) is not None


def _default_mac_virsh_binary() -> str:
    for candidate in ("/opt/homebrew/bin/virsh", "/usr/local/bin/virsh"):
        if os.path.exists(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return "virsh"


def mac_webui_default_cfg() -> dict[str, Any]:
    cfg = dict(_ORIG_WEBUI_DEFAULT_CFG())
    if hm.platform.system() == "Darwin":
        cfg["virsh_binary"] = _default_mac_virsh_binary()
    return cfg


def mac_get_virtual_machines_from_virsh(
    virsh_binary: str,
    virsh_uri: Optional[str],
    timeout: float,
) -> list[dict[str, Any]]:
    if hm.platform.system() == "Darwin" and not _virsh_binary_available(virsh_binary):
        return []
    return _ORIG_GET_VIRTUAL_MACHINES_FROM_VIRSH(virsh_binary, virsh_uri, timeout)


def mac_execute_virsh_command(
    cmd: str,
    virsh_binary: str,
    virsh_uri: Optional[str],
    timeout: float,
) -> bool:
    if hm.platform.system() == "Darwin" and not _virsh_binary_available(virsh_binary):
        cmd_l = (cmd or "").strip().lower()
        if cmd_l.startswith(("vm_start:", "vm_stop:", "vm_force_stop:", "vm_restart:")):
            hm.logging.info("ignoring VM command on macOS because virsh is unavailable (CMD=%s)", cmd)
            return True
        return False
    return _ORIG_EXECUTE_VIRSH_COMMAND(cmd, virsh_binary, virsh_uri, timeout)


def mac_list_cpu_temp_sensor_choices() -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    try:
        if hm.safe_float(_parse_macmon().get("cpu_temp_c"), None):
            seen.add("macmon:cpu_temp")
            out.append("macmon:cpu_temp")
    except Exception:
        pass
    for v in _ORIG_LIST_CPU_TEMP_SENSOR_CHOICES():
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def mac_list_fan_sensor_choices() -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    try:
        if hm.safe_float(_parse_macmon().get("fan_rpm"), None) is not None:
            seen.add("macmon:fan_rpm")
            out.append("macmon:fan_rpm")
    except Exception:
        pass
    for v in _ORIG_LIST_FAN_SENSOR_CHOICES():
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def mac_list_serial_port_choices() -> list[str]:
    base = _ORIG_LIST_SERIAL_PORT_CHOICES()
    if hm.platform.system() != "Darwin":
        return base
    # Prefer /dev/cu.* on macOS for host-initiated connections.
    cu = [p for p in base if p.startswith("/dev/cu.")]
    tty = [p for p in base if p.startswith("/dev/tty.")]
    rest = [p for p in base if p not in cu and p not in tty]
    return cu + tty + rest


def mac_list_disk_device_choices() -> list[str]:
    out = _ORIG_LIST_DISK_DEVICE_CHOICES()
    seen = set(out)
    try:
        p = subprocess.run(["diskutil", "list"], capture_output=True, text=True, timeout=3, check=False)
        txt = (p.stdout or "")
        for line in txt.splitlines():
            m = re.search(r"(/dev/disk\d+)\b", line)
            if not m:
                continue
            dev = m.group(1)
            if dev not in seen:
                seen.add(dev)
                out.append(dev)
    except Exception:
        pass
    return out


def _apply_mac_overrides() -> None:
    metrics_mod.get_cpu_temp_c = mac_get_cpu_temp_c  # type: ignore[assignment]
    hm.get_cpu_temp_c = mac_get_cpu_temp_c  # type: ignore[assignment]
    metrics_mod.get_fan_rpm = mac_get_fan_rpm  # type: ignore[assignment]
    hm.get_fan_rpm = mac_get_fan_rpm  # type: ignore[assignment]
    metrics_mod.get_gpu_metrics = mac_get_gpu_metrics  # type: ignore[assignment]
    hm.get_gpu_metrics = mac_get_gpu_metrics  # type: ignore[assignment]
    metrics_mod.get_virtual_machines_from_virsh = mac_get_virtual_machines_from_virsh  # type: ignore[assignment]
    hm.get_virtual_machines_from_virsh = mac_get_virtual_machines_from_virsh  # type: ignore[assignment]
    hm.execute_virsh_command = mac_execute_virsh_command  # type: ignore[assignment]
    cfg_mod.webui_default_cfg = mac_webui_default_cfg  # type: ignore[assignment]
    hm.webui_default_cfg = mac_webui_default_cfg  # type: ignore[assignment]
    metrics_mod.list_cpu_temp_sensor_choices = mac_list_cpu_temp_sensor_choices  # type: ignore[assignment]
    hm.list_cpu_temp_sensor_choices = mac_list_cpu_temp_sensor_choices  # type: ignore[assignment]
    metrics_mod.list_fan_sensor_choices = mac_list_fan_sensor_choices  # type: ignore[assignment]
    hm.list_fan_sensor_choices = mac_list_fan_sensor_choices  # type: ignore[assignment]
    serial_mod.list_serial_port_choices = mac_list_serial_port_choices  # type: ignore[assignment]
    hm.list_serial_port_choices = mac_list_serial_port_choices  # type: ignore[assignment]
    metrics_mod.list_disk_device_choices = mac_list_disk_device_choices  # type: ignore[assignment]
    hm.list_disk_device_choices = mac_list_disk_device_choices  # type: ignore[assignment]


def main() -> int:
    # Ensure the Web UI spawns the mac wrapper for agent mode, not the default entrypoint.
    os.environ.setdefault("PORTABLE_HOST_METRICS_SCRIPT", str(Path(__file__).resolve()))
    atexit.register(_stop_macmon_reader)
    _apply_mac_overrides()
    return app_cli.main()


if __name__ == "__main__":
    raise SystemExit(main())

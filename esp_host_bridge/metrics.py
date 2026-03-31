from __future__ import annotations

import asyncio
import http.client
import json
import logging
import os
import re
import socket
import subprocess
from typing import Any, Dict, Optional, Tuple

from .runtime import (
    HOME_ASSISTANT_SELF_SLUG,
    SUPERVISOR_TOKEN,
    SUPERVISOR_WS_URL,
    _humanize_home_assistant_slug,
    _read_first_line,
    _supervisor_request_json,
    classify_vm_state,
    psutil,
    safe_float,
    safe_int,
)


def get_home_assistant_addons(timeout: float) -> list[dict[str, Any]]:
    payload = _supervisor_request_json("/addons", timeout=timeout)
    rows = payload.get("addons") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    addons: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("slug") or "").strip()
        if slug and slug == HOME_ASSISTANT_SELF_SLUG:
            continue
        state = str(item.get("state") or "").strip().lower()
        update_available = bool(item.get("update_available"))
        available = bool(item.get("available", True))
        label = str(item.get("name") or slug or "App").strip()
        state_text = "running" if state == "started" else "stopped"
        if update_available or not available:
            state_text = f"{state_text} issue"
        addons.append(
            {
                "name": label,
                "slug": slug,
                "state": state_text,
                "status": state_text,
                "update_available": update_available,
                "available": available,
            }
        )
    addons.sort(key=lambda row: (0 if "running" in str(row.get("state", "")).lower() else 1, str(row.get("name") or "").lower()))
    return addons

async def _fetch_home_assistant_integrations_async(timeout: float) -> list[dict[str, Any]]:
    try:
        import websockets  # type: ignore
    except Exception as e:
        raise RuntimeError("websockets package is unavailable") from e

    async with websockets.connect(SUPERVISOR_WS_URL, open_timeout=timeout, close_timeout=timeout, max_size=8 * 1024 * 1024) as ws:
        hello = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        if not isinstance(hello, dict) or hello.get("type") != "auth_required":
            raise RuntimeError("unexpected Home Assistant websocket greeting")
        await ws.send(json.dumps({"type": "auth", "access_token": SUPERVISOR_TOKEN}))
        auth = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        if not isinstance(auth, dict) or auth.get("type") != "auth_ok":
            raise RuntimeError("Home Assistant websocket auth failed")
        await ws.send(json.dumps({"id": 1, "type": "config/entity_registry/list_for_display"}))
        result = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        if not isinstance(result, dict) or not result.get("success"):
            raise RuntimeError("entity registry query failed")
        payload = result.get("result")
        if not isinstance(payload, dict):
            return []
        entities = payload.get("entities")
        if not isinstance(entities, list):
            return []
        counts: Dict[str, int] = {}
        for row in entities:
            if not isinstance(row, dict):
                continue
            platform_slug = str(row.get("pl") or "").strip().lower()
            if not platform_slug:
                continue
            counts[platform_slug] = counts.get(platform_slug, 0) + 1
        items: list[dict[str, Any]] = []
        for slug, entity_count in counts.items():
            entity_label = f"{entity_count} entity" if entity_count == 1 else f"{entity_count} entities"
            items.append(
                {
                    "name": _humanize_home_assistant_slug(slug),
                    "state": "running",
                    "vcpus": 0,
                    "max_mem_mib": 0,
                    "state_label": entity_label,
                    "entity_count": entity_count,
                    "platform": slug,
                }
            )
        items.sort(key=lambda row: (-safe_int(row.get("entity_count"), 0), str(row.get("name") or "").lower()))
        return items

def get_home_assistant_integrations(timeout: float) -> list[dict[str, Any]]:
    if not SUPERVISOR_TOKEN:
        raise RuntimeError("SUPERVISOR_TOKEN is not available")
    items = asyncio.run(_fetch_home_assistant_integrations_async(timeout))
    normalized: list[dict[str, Any]] = []
    for item in items:
        state_label = str(item.get("state_label") or "Loaded")
        normalized.append(
            {
                "name": str(item.get("name") or "Integration"),
                "state": "running",
                "vcpus": 0,
                "max_mem_mib": 0,
                "state_label": state_label,
                "entity_count": safe_int(item.get("entity_count"), 0) or 0,
            }
        )
    return normalized

def normalize_docker_data(v: Any) -> list[dict[str, Any]]:
    if isinstance(v, list):
        return v
    if isinstance(v, dict):
        for key in ("containers", "docker", "items"):
            candidate = v.get(key)
            if isinstance(candidate, list):
                return candidate
    return []

def vm_summary_counts(vm_data: list[dict[str, Any]]) -> Dict[str, int]:
    counts = {"running": 0, "stopped": 0, "paused": 0, "other": 0}
    for vm in vm_data:
        if not isinstance(vm, dict):
            continue
        key, _label = classify_vm_state(vm.get("state"))
        if key not in counts:
            key = "other"
        counts[key] += 1
    return counts

def get_cpu_percent(prev_total: Optional[int], prev_idle: Optional[int]) -> Tuple[float, Optional[int], Optional[int]]:
    try:
        line = _read_first_line("/proc/stat")
        parts = line.split()
        if len(parts) >= 6 and parts[0] == "cpu":
            nums = [int(x) for x in parts[1:9]]
            total = sum(nums)
            idle = nums[3] + nums[4]
            if prev_total is None or prev_idle is None:
                return 0.0, total, idle
            dt = total - prev_total
            di = idle - prev_idle
            if dt <= 0:
                return 0.0, total, idle
            pct = (1.0 - (di / dt)) * 100.0
            return max(0.0, min(100.0, pct)), total, idle
    except Exception:
        pass

    if psutil:
        try:
            return float(psutil.cpu_percent(interval=None)), prev_total, prev_idle
        except Exception:
            pass
    return 0.0, prev_total, prev_idle

def get_mem_percent() -> float:
    try:
        mem_total = 0
        mem_avail = 0
        mem_free = 0
        mem_buffers = 0
        mem_cached = 0
        with open("/proc/meminfo", "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 2:
                    continue
                key = parts[0]
                try:
                    val = int(parts[1])
                except Exception:
                    continue
                if key == "MemTotal:":
                    mem_total = val
                elif key == "MemAvailable:":
                    mem_avail = val
                elif key == "MemFree:":
                    mem_free = val
                elif key == "Buffers:":
                    mem_buffers = val
                elif key == "Cached:":
                    mem_cached = val
        if mem_total > 0:
            if mem_avail <= 0:
                mem_avail = mem_free + mem_buffers + mem_cached
            used = mem_total - mem_avail
            pct = (used * 100.0) / mem_total
            return max(0.0, min(100.0, pct))
    except Exception:
        pass

    if psutil:
        try:
            return float(psutil.virtual_memory().percent)
        except Exception:
            pass
    return 0.0

def get_uptime_seconds() -> float:
    try:
        line = _read_first_line("/proc/uptime")
        first = line.split()[0] if line else "0"
        return safe_float(first, 0.0) or 0.0
    except Exception:
        pass
    if psutil:
        try:
            return max(0.0, time.time() - float(psutil.boot_time()))
        except Exception:
            pass
    return 0.0

def _parse_proc_net_dev() -> dict[str, Tuple[float, float]]:
    out: dict[str, Tuple[float, float]] = {}
    try:
        with open("/proc/net/dev", "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()[2:]
    except Exception:
        return out
    for line in lines:
        if ":" not in line:
            continue
        iface, rest = line.split(":", 1)
        iface = iface.strip()
        cols = rest.split()
        if len(cols) < 16:
            continue
        rx = safe_float(cols[0], 0.0) or 0.0
        tx = safe_float(cols[8], 0.0) or 0.0
        out[iface] = (rx, tx)
    return out

def _psutil_net_dev() -> dict[str, Tuple[float, float]]:
    out: dict[str, Tuple[float, float]] = {}
    if not psutil:
        return out
    try:
        stats = psutil.net_io_counters(pernic=True)
        for iface, row in stats.items():
            out[iface] = (float(getattr(row, "bytes_recv", 0.0)), float(getattr(row, "bytes_sent", 0.0)))
    except Exception:
        return {}
    return out


def _iface_is_routable(iface: str) -> bool:
    if not psutil or not hasattr(psutil, "net_if_addrs"):
        return False
    try:
        addrs = psutil.net_if_addrs().get(iface, [])
    except Exception:
        return False
    for addr in addrs:
        family = getattr(addr, "family", None)
        value = str(getattr(addr, "address", "") or "").strip()
        if not value:
            continue
        if family == socket.AF_INET:
            if value.startswith("127.") or value.startswith("169.254."):
                continue
            return True
        if getattr(socket, "AF_INET6", None) == family:
            ll = value.lower()
            if ll == "::1" or ll.startswith("fe80:"):
                continue
            return True
    return False


def _preferred_net_iface(stats: dict[str, Tuple[float, float]]) -> Optional[str]:
    if not stats:
        return None
    iface_stats = {}
    if psutil and hasattr(psutil, "net_if_stats"):
        try:
            iface_stats = psutil.net_if_stats()
        except Exception:
            iface_stats = {}

    exclude_exact = {"lo", "loopback", "lo0", "gif0", "stf0", "bridge0", "awdl0", "llw0", "ap1"}
    exclude_prefixes = ("utun", "gif", "stf", "anpi", "bridge", "awdl", "llw", "ap")
    prefer_prefixes = ("en", "eth", "wl", "wlan")

    def score(name: str, rx: float, tx: float) -> tuple[int, int, str]:
        lname = name.lower()
        total = int(rx + tx)
        score_val = 0
        if lname in exclude_exact or lname.startswith(exclude_prefixes):
            score_val -= 1000
        if lname.startswith(prefer_prefixes):
            score_val += 250
        if _iface_is_routable(name):
            score_val += 200
        row = iface_stats.get(name)
        if row is not None and bool(getattr(row, "isup", False)):
            score_val += 100
        if total > 0:
            score_val += 50
        return score_val, total, lname

    ranked = sorted(
        ((score(name, rx, tx), name) for name, (rx, tx) in stats.items()),
        reverse=True,
    )
    for (score_val, _total, _lname), name in ranked:
        if score_val > -1000:
            return name
    return ranked[0][1] if ranked else None

def get_net_bytes_local(iface_hint: Optional[str] = None, last_iface: Optional[str] = None) -> Tuple[float, float, Optional[str]]:
    stats = _parse_proc_net_dev() or _psutil_net_dev()
    if not stats:
        return 0.0, 0.0, None
    if iface_hint and iface_hint in stats:
        rx, tx = stats[iface_hint]
        return rx, tx, iface_hint
    if last_iface and last_iface in stats:
        rx, tx = stats[last_iface]
        return rx, tx, last_iface
    iface = _preferred_net_iface(stats)
    if iface and iface in stats:
        rx, tx = stats[iface]
        return rx, tx, iface
    iface = next(iter(stats.keys()))
    rx, tx = stats[iface]
    return rx, tx, iface

def _read_temp_millic(path: str) -> Optional[float]:
    try:
        v = float(_read_first_line(path))
    except Exception:
        return None
    if v > 1000.0:
        return v / 1000.0
    if -50.0 <= v <= 150.0:
        return v
    return None

def get_cpu_temp_c(sensor_hint: Optional[str] = None) -> Optional[float]:
    hint = (sensor_hint or "").strip().lower()
    if psutil:
        try:
            temps = psutil.sensors_temperatures(fahrenheit=False)
            if hint:
                for key, entries in temps.items():
                    lk = key.lower()
                    for e in entries:
                        label = (getattr(e, "label", "") or "").lower()
                        current = safe_float(getattr(e, "current", None), None)
                        if current is None or not (-20.0 <= current <= 150.0):
                            continue
                        if hint in {f"psutil:{lk}:{label}", f"{lk}:{label}", label}:
                            return float(current)
            for key, entries in temps.items():
                lk = key.lower()
                for e in entries:
                    label = (getattr(e, "label", "") or "").lower()
                    current = safe_float(getattr(e, "current", None), None)
                    if current is None:
                        continue
                    if any(x in lk for x in ("cpu", "core", "k10", "pkg")) or any(
                        x in label for x in ("cpu", "package", "tdie", "core")
                    ):
                        return float(current)
            for entries in temps.values():
                for e in entries:
                    current = safe_float(getattr(e, "current", None), None)
                    if current is not None:
                        return float(current)
        except Exception:
            pass

    try:
        zones = sorted([p for p in os.listdir("/sys/class/thermal") if p.startswith("thermal_zone")])
    except Exception:
        zones = []

    if hint and hint.startswith('/sys/class/thermal/'):
        temp = _read_temp_millic(hint.rstrip('/') + '/temp')
        if temp is not None:
            return temp

    for tz in zones:
        tpath = f"/sys/class/thermal/{tz}/type"
        vpath = f"/sys/class/thermal/{tz}/temp"
        try:
            ttype = _read_first_line(tpath).lower()
        except Exception:
            ttype = ""
        temp = _read_temp_millic(vpath)
        if temp is None:
            continue
        if any(x in ttype for x in ("cpu", "pkg", "package", "x86_pkg", "soc")):
            return temp

    for tz in zones:
        temp = _read_temp_millic(f"/sys/class/thermal/{tz}/temp")
        if temp is not None:
            return temp

    return None

def get_fan_rpm(sensor_hint: Optional[str] = None) -> Optional[float]:
    hint = (sensor_hint or "").strip().lower()
    if psutil and hasattr(psutil, "sensors_fans"):
        try:
            fans = psutil.sensors_fans()  # type: ignore[attr-defined]
            if hint:
                for group, entries in (fans or {}).items():
                    gl = str(group).lower()
                    for idx, e in enumerate(entries):
                        label = (getattr(e, "label", "") or "").lower()
                        cur = safe_float(getattr(e, "current", None), None)
                        if cur is None or cur < 0:
                            continue
                        if hint in {f"psutil:{gl}:{label}", f"psutil:{gl}:fan{idx+1}", f"{gl}:{label}", label}:
                            return float(cur)
            vals: list[float] = []
            for entries in (fans or {}).values():
                for e in entries:
                    cur = safe_float(getattr(e, "current", None), None)
                    if cur is not None and cur >= 0:
                        vals.append(float(cur))
            if vals:
                return max(vals)
        except Exception:
            pass
    try:
        for hw in sorted(os.listdir('/sys/class/hwmon')):
            base = f'/sys/class/hwmon/{hw}'
            if hint.startswith(base.lower() + '/fan') and hint.endswith('_input'):
                v = safe_float(_read_first_line(hint), None)
                if v is not None and v >= 0:
                    return float(v)
            for name in sorted(os.listdir(base)):
                if not re.match(r'fan\d+_input$', name):
                    continue
                v = safe_float(_read_first_line(f'{base}/{name}'), None)
                if v is not None and v >= 0:
                    return float(v)
    except Exception:
        pass
    return None

def get_disk_usage_pct(disk_hint: Optional[str] = None, active_disk: Optional[str] = None) -> float:
    if psutil:
        try:
            parts = psutil.disk_partitions(all=False)
            hint_name = _normalize_disk_name(disk_hint or active_disk)
            selected_mount = None
            if hint_name:
                for part in parts:
                    dev = str(getattr(part, 'device', '') or '')
                    if dev.startswith('/dev/') and _normalize_disk_name(dev) == hint_name:
                        selected_mount = str(getattr(part, 'mountpoint', '') or '')
                        break
                if selected_mount is None:
                    for part in parts:
                        dev = str(getattr(part, 'device', '') or '')
                        if dev.startswith('/dev/') and dev.startswith(f'/dev/{hint_name}'):
                            selected_mount = str(getattr(part, 'mountpoint', '') or '')
                            break
            if not selected_mount:
                for preferred in ('/mnt/user', '/mnt/cache', '/'):
                    for part in parts:
                        if str(getattr(part, 'mountpoint', '') or '') == preferred:
                            selected_mount = preferred
                            break
                    if selected_mount:
                        break
            if not selected_mount and parts:
                selected_mount = str(getattr(parts[0], 'mountpoint', '') or '')
            if selected_mount:
                try:
                    return float(psutil.disk_usage(selected_mount).percent)
                except Exception:
                    pass
        except Exception:
            pass
    try:
        st = os.statvfs('/')
        total = float(st.f_blocks) * float(st.f_frsize)
        avail = float(st.f_bavail) * float(st.f_frsize)
        used = max(0.0, total - avail)
        if total > 0:
            return (used * 100.0) / total
    except Exception:
        pass
    return 0.0

def docker_summary_counts(docker_data: list[dict[str, Any]]) -> Dict[str, int]:
    counts = {"running": 0, "stopped": 0, "unhealthy": 0}
    for c in docker_data:
        if not isinstance(c, dict):
            continue
        state_raw = str(c.get('State') or c.get('state') or '').lower()
        status_raw = str(c.get('Status') or c.get('status') or '').lower()
        combined = f'{state_raw} {status_raw}'
        is_running = ('running' in combined) or (' up ' in f' {combined} ')
        if is_running:
            counts['running'] += 1
        else:
            counts['stopped'] += 1
        if 'unhealthy' in combined:
            counts['unhealthy'] += 1
    return counts

def get_gpu_metrics(timeout: float) -> Dict[str, Any]:
    out: Dict[str, Any] = {"temp_c": 0.0, "util_pct": 0.0, "mem_pct": 0.0, "available": False}
    try:
        p = subprocess.run(
            [
                'nvidia-smi',
                '--query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total',
                '--format=csv,noheader,nounits',
            ],
            capture_output=True,
            text=True,
            timeout=max(1.0, float(timeout)),
            check=False,
        )
        if p.returncode == 0 and p.stdout:
            temps: list[float] = []
            utils: list[float] = []
            mem_pcts: list[float] = []
            for line in p.stdout.splitlines():
                parts = [x.strip() for x in line.split(',')]
                if len(parts) < 4:
                    continue
                t = safe_float(parts[0], None)
                u = safe_float(parts[1], None)
                mu = safe_float(parts[2], None)
                mt = safe_float(parts[3], None)
                if t is not None and -20.0 <= t <= 150.0:
                    temps.append(float(t))
                if u is not None and 0.0 <= u <= 100.0:
                    utils.append(float(u))
                if mu is not None and mt and mt > 0:
                    mem_pcts.append(max(0.0, min(100.0, (float(mu) * 100.0) / float(mt))))
            if temps:
                out['temp_c'] = max(temps)
            if utils:
                out['util_pct'] = max(utils)
            if mem_pcts:
                out['mem_pct'] = max(mem_pcts)
            if temps or utils or mem_pcts:
                out['available'] = True
    except Exception:
        pass
    return out

def _extract_temp_from_text(text: str) -> Optional[float]:
    for line in text.splitlines():
        ll = line.lower()
        if "temperature" not in ll and "composite" not in ll:
            continue
        nums = re.findall(r"-?\d+(?:\.\d+)?", line)
        for n in nums:
            v = safe_float(n, None)
            if v is None:
                continue
            if -20.0 <= v <= 150.0:
                return float(v)
    return None

def _normalize_disk_name(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    s = str(v).strip()
    if not s:
        return None
    if s.startswith("/dev/"):
        s = s[5:]
    if s.startswith("nvme") and "p" in s:
        s = re.sub(r"p\d+$", "", s)
    s = re.sub(r"\d+$", "", s)
    return s

def _disk_candidates(device_hint: Optional[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def add(path: str) -> None:
        if path not in seen:
            seen.add(path)
            out.append(path)

    hint_name = _normalize_disk_name(device_hint)
    if hint_name:
        add(f"/dev/{hint_name}")
    for d in ["/dev/nvme0", "/dev/nvme0n1", "/dev/sda"]:
        add(d)
    return out

def get_disk_temp_c(timeout: float, disk_device: Optional[str] = None) -> Optional[float]:
    hint_name = _normalize_disk_name(disk_device)
    if psutil:
        try:
            temps = psutil.sensors_temperatures(fahrenheit=False)
            for key, entries in temps.items():
                lk = key.lower()
                if not any(x in lk for x in ("nvme", "ssd", "smart", "drivetemp")):
                    continue
                for e in entries:
                    label = (getattr(e, "label", "") or "").lower()
                    if hint_name and hint_name not in label and hint_name not in lk:
                        continue
                    current = safe_float(getattr(e, "current", None), None)
                    if current is not None and -20.0 <= current <= 150.0:
                        return float(current)
        except Exception:
            pass

    for dev in _disk_candidates(disk_device):
        for cmd in (["nvme", "smart-log", dev], ["smartctl", "-A", dev]):
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
            except Exception:
                continue
            text = (p.stdout or "") + "\n" + (p.stderr or "")
            t = _extract_temp_from_text(text)
            if t is not None:
                return t
    return None

def _read_diskstats() -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    try:
        with open("/proc/diskstats", "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception:
        return out

    for line in lines:
        cols = line.split()
        if len(cols) < 14:
            continue
        name = cols[2]
        if re.search(r"\d+$", name) and not name.startswith("nvme"):
            continue
        if name.startswith(("loop", "ram", "dm-", "sr", "zram", "md")):
            continue
        if name.startswith("nvme") and re.search(r"p\d+$", name):
            continue
        try:
            sectors_read = float(cols[5])
            sectors_written = float(cols[9])
        except Exception:
            continue
        out[name] = (sectors_read * 512.0, sectors_written * 512.0)
    return out

def _psutil_diskstats() -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    if not psutil:
        return out
    try:
        rows = psutil.disk_io_counters(perdisk=True)
    except Exception:
        return out
    for name, row in rows.items():
        if name.startswith(("loop", "ram", "dm-", "sr", "zram", "md")):
            continue
        out[name] = (float(getattr(row, "read_bytes", 0.0)), float(getattr(row, "write_bytes", 0.0)))
    return out

def get_disk_bytes_local(disk_hint: Optional[str] = None, last_disk: Optional[str] = None) -> tuple[float, float, Optional[str]]:
    stats = _read_diskstats() or _psutil_diskstats()
    if not stats:
        return 0.0, 0.0, None

    hint_name = _normalize_disk_name(disk_hint)
    if hint_name:
        if hint_name in stats:
            rb, wb = stats[hint_name]
            return rb, wb, hint_name
        for name in stats:
            if name.startswith(hint_name):
                rb, wb = stats[name]
                return rb, wb, name

    if last_disk and last_disk in stats:
        rb, wb = stats[last_disk]
        return rb, wb, last_disk

    for name in sorted(stats.keys()):
        if name.startswith(("nvme", "sd", "vd", "xvd", "mmcblk", "disk")):
            rb, wb = stats[name]
            return rb, wb, name

    name = next(iter(stats.keys()))
    rb, wb = stats[name]
    return rb, wb, name

def get_docker_containers_from_engine(socket_path: str, timeout: float) -> Any:
    class UnixHTTPConnection(http.client.HTTPConnection):
        def __init__(self, unix_socket_path: str, timeout_s: float):
            super().__init__("localhost", timeout=timeout_s)
            self.unix_socket_path = unix_socket_path

        def connect(self) -> None:
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(self.timeout)
            self.sock.connect(self.unix_socket_path)

    conn = UnixHTTPConnection(socket_path, timeout)
    try:
        conn.request("GET", "/containers/json?all=1")
        resp = conn.getresponse()
        body = resp.read()
        if resp.status >= 400:
            raise RuntimeError(f"Docker API HTTP {resp.status}: {body[:200]!r}")
        return json.loads(body.decode("utf-8", errors="ignore"))
    finally:
        conn.close()

def _run_command_capture(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=max(1.0, float(timeout)),
        check=False,
    )

def _virsh_cmd(virsh_binary: str, virsh_uri: Optional[str], *parts: str) -> list[str]:
    argv = [virsh_binary or "virsh"]
    if virsh_uri:
        argv.extend(["-c", virsh_uri])
    argv.extend(parts)
    return argv

def _virsh_uri_candidates(virsh_uri: Optional[str]) -> list[Optional[str]]:
    if virsh_uri:
        return [virsh_uri]
    out: list[Optional[str]] = []
    seen: set[str] = set()
    for candidate in (None, "qemu:///system", "qemu:///session"):
        key = candidate or ""
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out

def _parse_virsh_mem_mib(v: Any) -> int:
    text = str(v or "").strip()
    if not text:
        return 0
    nums = re.findall(r"-?\d+(?:\.\d+)?", text)
    if not nums:
        return 0
    value = safe_float(nums[0], 0.0) or 0.0
    ll = text.lower()
    if "gib" in ll or "gb" in ll:
        return max(0, int(round(value * 1024.0)))
    if "mib" in ll or "mb" in ll:
        return max(0, int(round(value)))
    if "kib" in ll or "kb" in ll:
        return max(0, int(round(value / 1024.0)))
    return max(0, int(round(value / 1024.0)))

def _parse_virsh_dominfo(text: str) -> dict[str, Any]:
    info: dict[str, Any] = {}
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        k = key.strip().lower()
        v = value.strip()
        info[k] = v
    name = str(info.get("name") or "").strip()
    state = str(info.get("state") or "").strip()
    vcpus = max(0, safe_int(info.get("cpu(s)"), 0) or 0)
    max_mem_mib = _parse_virsh_mem_mib(info.get("max memory"))
    used_mem_mib = _parse_virsh_mem_mib(info.get("used memory"))
    autostart = str(info.get("autostart") or "").strip().lower() in {"enable", "enabled", "yes"}
    persistent = str(info.get("persistent") or "").strip().lower() in {"yes", "true"}
    dom_id = str(info.get("id") or "-").strip()
    return {
        "name": name,
        "state": state,
        "vcpus": vcpus,
        "max_mem_mib": max_mem_mib,
        "used_mem_mib": used_mem_mib,
        "autostart": autostart,
        "persistent": persistent,
        "id": dom_id,
    }

def get_virtual_machines_from_virsh(virsh_binary: str, virsh_uri: Optional[str], timeout: float) -> list[dict[str, Any]]:
    names: list[str] = []
    chosen_uri = virsh_uri
    errors: list[str] = []
    had_empty_success = False
    for candidate_uri in _virsh_uri_candidates(virsh_uri):
        base = _virsh_cmd(virsh_binary, candidate_uri, "list", "--all", "--name")
        p = _run_command_capture(base, timeout)
        if p.returncode != 0:
            errors.append((p.stderr or p.stdout or f"virsh list failed ({p.returncode})").strip())
            continue
        names = [line.strip() for line in (p.stdout or "").splitlines() if line.strip()]
        chosen_uri = candidate_uri
        if names:
            break
        had_empty_success = True
        if virsh_uri:
            return []
    else:
        if had_empty_success:
            return []
        raise RuntimeError("; ".join([e for e in errors if e][:3]) or "virsh list failed")

    if not names:
        return []

    out: list[dict[str, Any]] = []
    for name in names:
        dominfo_cmd = _virsh_cmd(virsh_binary, chosen_uri, "dominfo", name)
        try:
            info_p = _run_command_capture(dominfo_cmd, timeout)
        except Exception as e:
            logging.warning("virsh dominfo failed for %s (%s)", name, e)
            out.append({"name": name, "state": "unknown", "vcpus": 0, "max_mem_mib": 0, "used_mem_mib": 0})
            continue
        if info_p.returncode != 0:
            logging.warning(
                "virsh dominfo failed for %s (rc=%s: %s)",
                name,
                info_p.returncode,
                (info_p.stderr or info_p.stdout or "").strip()[:160],
            )
            out.append({"name": name, "state": "unknown", "vcpus": 0, "max_mem_mib": 0, "used_mem_mib": 0})
            continue
        item = _parse_virsh_dominfo(info_p.stdout or "")
        if not item.get("name"):
            item["name"] = name
        out.append(item)
    return out

def list_network_interface_choices() -> list[str]:
    try:
        stats = _parse_proc_net_dev()
    except Exception:
        stats = {}
    if not stats and psutil:
        try:
            io = psutil.net_io_counters(pernic=True)
            stats = {str(k): (0.0, 0.0) for k in io.keys()}
        except Exception:
            stats = {}
    names = [str(k) for k in stats.keys()]
    names = sorted(set(names), key=lambda x: (x.lower() in {"lo", "loopback", "lo0"}, x.lower()))
    return names

def list_disk_device_choices() -> list[str]:
    choices: list[str] = []
    seen: set[str] = set()

    def _add(v: Optional[str]) -> None:
        if not v:
            return
        x = str(v).strip()
        if not x or x in seen:
            return
        seen.add(x)
        choices.append(x)

    if psutil:
        try:
            for part in psutil.disk_partitions(all=False):
                dev = str(getattr(part, 'device', '') or '')
                if dev.startswith('/dev/'):
                    _add(dev)
        except Exception:
            pass

    try:
        for name in sorted(os.listdir('/sys/block')):
            if name.startswith(('loop', 'ram', 'zram', 'dm-')):
                continue
            _add(f'/dev/{name}')
    except Exception:
        pass

    return choices

def list_cpu_temp_sensor_choices() -> list[str]:
    choices: list[str] = []
    seen: set[str] = set()

    def _add(v: Optional[str]) -> None:
        if not v:
            return
        x = str(v).strip()
        if not x or x in seen:
            return
        seen.add(x)
        choices.append(x)

    if psutil:
        try:
            temps = psutil.sensors_temperatures(fahrenheit=False)
            for group, entries in (temps or {}).items():
                gl = str(group).lower()
                for e in entries:
                    label = (getattr(e, 'label', '') or '').strip()
                    if not label:
                        continue
                    ll = label.lower()
                    if 'core' in ll or 'cpu' in ll or 'package' in ll or 'tdie' in ll:
                        _add(f'psutil:{gl}:{ll}')
        except Exception:
            pass

    try:
        for tz in sorted([p for p in os.listdir('/sys/class/thermal') if p.startswith('thermal_zone')]):
            tpath = f'/sys/class/thermal/{tz}/type'
            try:
                ttype = _read_first_line(tpath).strip().lower()
            except Exception:
                ttype = ''
            if any(x in ttype for x in ('cpu', 'core', 'pkg', 'package', 'soc')):
                _add(f'/sys/class/thermal/{tz}')
    except Exception:
        pass

    return choices

def list_fan_sensor_choices() -> list[str]:
    choices: list[str] = []
    seen: set[str] = set()

    def _add(v: Optional[str]) -> None:
        if not v:
            return
        x = str(v).strip()
        if not x or x in seen:
            return
        seen.add(x)
        choices.append(x)

    if psutil and hasattr(psutil, 'sensors_fans'):
        try:
            fans = psutil.sensors_fans()  # type: ignore[attr-defined]
            for group, entries in (fans or {}).items():
                gl = str(group).lower()
                for idx, e in enumerate(entries):
                    label = (getattr(e, 'label', '') or '').strip().lower()
                    if label:
                        _add(f'psutil:{gl}:{label}')
                    _add(f'psutil:{gl}:fan{idx+1}')
        except Exception:
            pass

    try:
        for hw in sorted(os.listdir('/sys/class/hwmon')):
            base = f'/sys/class/hwmon/{hw}'
            for name in sorted(os.listdir(base)):
                if re.match(r'fan\d+_input$', name):
                    _add(f'{base}/{name}')
    except Exception:
        pass

    return choices

def detect_hardware_choices() -> dict[str, Any]:
    from .serial import list_serial_port_choices

    return {
        'serial_ports': list_serial_port_choices(),
        'network_ifaces': list_network_interface_choices(),
        'disk_devices': list_disk_device_choices(),
        'cpu_temp_sensors': list_cpu_temp_sensor_choices(),
        'fan_sensors': list_fan_sensor_choices(),
    }

__all__ = [
    "_run_command_capture",
    "_virsh_uri_candidates",
    "detect_hardware_choices",
    "docker_summary_counts",
    "get_cpu_percent",
    "get_cpu_temp_c",
    "get_disk_bytes_local",
    "get_disk_temp_c",
    "get_disk_usage_pct",
    "get_docker_containers_from_engine",
    "get_fan_rpm",
    "get_gpu_metrics",
    "get_home_assistant_addons",
    "get_home_assistant_integrations",
    "get_mem_percent",
    "get_net_bytes_local",
    "get_uptime_seconds",
    "get_virtual_machines_from_virsh",
    "list_cpu_temp_sensor_choices",
    "list_disk_device_choices",
    "list_fan_sensor_choices",
    "list_network_interface_choices",
    "normalize_docker_data",
    "vm_summary_counts",
]

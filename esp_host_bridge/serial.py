from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

try:
    import serial  # type: ignore
except Exception:
    serial = None

try:
    from serial.tools import list_ports  # type: ignore
except Exception:
    list_ports = None

from .config import _clean_str
from .runtime import SERIAL_RETRY_SECONDS


def get_available_ports() -> list[str]:
    if list_ports is None:
        return []
    try:
        return sorted(p.device for p in list_ports.comports())
    except Exception:
        return []

def list_serial_port_choices() -> list[str]:
    choices: list[str] = []
    seen: set[str] = set()

    def _add(path: Optional[str]) -> None:
        if not path:
            return
        p = str(path).strip()
        if not p or p in seen:
            return
        seen.add(p)
        choices.append(p)

    # Prefer stable Linux/Unraid symlinks first when present.
    by_id_dir = Path('/dev/serial/by-id')
    try:
        if by_id_dir.is_dir():
            for item in sorted(by_id_dir.iterdir(), key=lambda x: x.name.lower()):
                _add(str(item))
    except Exception:
        pass

    for port in get_available_ports():
        _add(port)

    return choices

def serial_io_bypassed(port: Optional[str]) -> bool:
    value = _clean_str(port, "")
    return value.upper() in {"NONE", "DEBUG"}

def test_serial_open(port: Optional[str], baud: int) -> tuple[bool, str]:
    if serial_io_bypassed(port):
        return True, "serial bypass mode enabled; no USB serial device will be opened"
    if serial is None:
        return False, 'pyserial is not installed. Install with: pip install pyserial'

    p = (port or '').strip()
    if not p:
        return False, 'serial port is required'

    try:
        baud_i = int(baud)
    except Exception:
        return False, 'invalid baud rate'
    if baud_i <= 0:
        return False, 'invalid baud rate'

    try:
        s = serial.Serial(p, baud_i, timeout=1, write_timeout=2)
        try:
            s.dtr = False
            s.rts = False
        except Exception:
            pass
        try:
            s.close()
        except Exception:
            pass
        return True, f'opened {p} @ {baud_i}'
    except Exception as e:
        return False, f'failed to open {p}: {e}'

def _safe_realpath(path: str) -> str:
    try:
        return os.path.realpath(path)
    except Exception:
        return path

def pick_serial_port(requested: Optional[str], last_port: Optional[str] = None) -> Optional[str]:
    available = get_available_ports()
    if requested:
        req = requested.strip()
        if not req:
            requested = None
        else:
            req_abs = req if req.startswith("/dev/") or re.match(r"^[A-Za-z]+\d+$", req) else f"/dev/{req}"
            req_real = _safe_realpath(req_abs)
            for p in available:
                if req == p or req_abs == p:
                    return p
            if os.path.exists(req_abs):
                return req_abs
            if os.path.exists(req_abs):
                for p in available:
                    if _safe_realpath(p) == req_real:
                        return p
            logging.warning("serial port not found: %s", requested)
            if available:
                logging.warning("available ports:")
                for p in available:
                    logging.warning("  - %s", p)
            else:
                logging.warning("no serial ports detected.")
            return None

    if last_port and last_port in available:
        return last_port

    for p in available:
        if p.startswith("/dev/ttyACM"):
            return p
    for p in available:
        if p.startswith("/dev/ttyUSB"):
            return p
    for p in ("/dev/ttyAMA0", "/dev/serial0", "/dev/ttyS0"):
        if p in available:
            return p
    for p in available:
        if p.startswith("/dev/cu.usbmodem"):
            return p
    for p in available:
        if p.startswith("/dev/cu.usb"):
            return p
    for p in available:
        if p.startswith("/dev/tty.usb"):
            return p
    for p in available:
        if p.upper().startswith("COM"):
            return p
    return available[0] if available else None

def open_serial(requested_port: Optional[str], baud: int, last_port: Optional[str] = None):
    if serial is None:
        raise RuntimeError("pyserial is not installed. Install with: pip install pyserial")
    while True:
        s, serial_port = try_open_serial_once(requested_port, baud, last_port=last_port)
        if s is not None:
            return s, serial_port
        time.sleep(SERIAL_RETRY_SECONDS)

def try_open_serial_once(requested_port: Optional[str], baud: int, last_port: Optional[str] = None):
    if serial is None:
        raise RuntimeError("pyserial is not installed. Install with: pip install pyserial")
    serial_port = pick_serial_port(requested_port, last_port=last_port)
    if serial_port is None:
        logging.warning("no serial port available, retrying in %ss", SERIAL_RETRY_SECONDS)
        return None, last_port
    try:
        s = serial.Serial(serial_port, baud, timeout=1, write_timeout=2)
        try:
            s.dtr = False
            s.rts = False
        except Exception:
            pass
        logging.info("serial connected: %s @ %s", serial_port, baud)
        return s, serial_port
    except Exception as e:
        logging.warning("serial open failed on %s (%s), retrying in %ss", serial_port, e, SERIAL_RETRY_SECONDS)
        return None, last_port

__all__ = [
    "get_available_ports",
    "list_serial_port_choices",
    "open_serial",
    "pick_serial_port",
    "serial_io_bypassed",
    "test_serial_open",
    "try_open_serial_once",
]

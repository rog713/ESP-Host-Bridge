from __future__ import annotations

import argparse
import unittest
from unittest import mock
from esp_host_bridge.runtime import (
    RuntimeState,
    build_browser_status_payload,
    build_runtime_snapshot,
)


class RuntimeSnapshotTests(unittest.TestCase):
    def test_build_runtime_snapshot_normalizes_metrics_and_usb_frames(self) -> None:
        args = argparse.Namespace(
            disable_docker_polling=False,
            disable_vm_polling=False,
            disable_gpu_polling=False,
        )
        state = RuntimeState()
        polled = {
            "host": {
                "enabled": True,
                "metrics": {
                    "cpu_pct": 12.3,
                    "mem_pct": 67.8,
                    "uptime_s": 1234,
                    "cpu_temp_c": 45.6,
                    "cpu_temp_available": True,
                    "disk_temp_available": True,
                    "gpu_enabled": True,
                    "fan_available": True,
                    "gpu_available": True,
                    "active_iface": "en13",
                    "active_disk": "/dev/disk3",
                    "rx_kbps": 10,
                    "tx_kbps": 20,
                    "disk_r_kbs": 30,
                    "disk_w_kbs": 40,
                    "disk_temp_c": 51.2,
                    "disk_usage_pct": 73.4,
                    "fan_rpm": 1234,
                    "gpu_temp_c": 65.4,
                    "gpu_util_pct": 9,
                    "gpu_mem_pct": 27,
                },
            },
            "docker": {
                "enabled": True,
                "counts": {"running": 1, "stopped": 2, "unhealthy": 3},
                "compact": "alpha|up;bravo|down",
                "api_ok": None,
            },
            "vms": {
                "enabled": True,
                "counts": {"running": 4, "stopped": 5, "paused": 6, "other": 7},
                "compact": "vm-a|running|2|2048|Running",
                "api_ok": None,
            },
        }
        with mock.patch("esp_host_bridge.runtime.poll_integrations", return_value=polled):
            snapshot = build_runtime_snapshot(
                args,
                state,
                now=100.0,
                homeassistant_mode=False,
            )

        self.assertEqual(snapshot["metric_snapshot"]["CPU"], "12.3")
        self.assertEqual(snapshot["metric_snapshot"]["IFACE"], "en13")
        self.assertEqual(snapshot["metric_snapshot"]["DOCKER"], "alpha|up;bravo|down")
        self.assertEqual(snapshot["metric_snapshot"]["VMS"], "vm-a|running|2|2048|Running")
        self.assertEqual(len(snapshot["usb_frames"]), 5)
        self.assertEqual(
            snapshot["usb_frames"][0],
            "CPU=12.3,TEMP=45.6,MEM=67.8,UP=1234,RX=10,TX=20,IFACE=en13,TEMPAV=1,HAMODE=0,HATOKEN=0,HADOCKAPI=-1,HAVMSAPI=-1,GPUEN=1,DOCKEREN=1,VMSEN=1,POWER=RUNNING\n",
        )
        self.assertEqual(state.active_iface, "en13")
        self.assertEqual(state.active_disk, "/dev/disk3")

    def test_build_browser_status_payload_derives_ui_contract_from_base_status(self) -> None:
        base_status = {
            "cmd": ["python3", "-m", "esp_host_bridge", "agent", "--demo-secret", "secret"],
            "last_metrics": {
                "CPU": "10.0",
                "TEMP": "45.0",
                "MEM": "50.0",
                "UP": "123",
                "RX": "1",
                "TX": "2",
                "IFACE": "en13",
                "TEMPAV": "1",
                "HAMODE": "0",
                "HATOKEN": "0",
                "HADOCKAPI": "-1",
                "HAVMSAPI": "-1",
                "GPUEN": "1",
                "DOCKEREN": "1",
                "VMSEN": "1",
                "POWER": "RUNNING",
                "DOCKRUN": "1",
                "DOCKSTOP": "1",
                "DOCKUNH": "0",
                "DOCKER": "alpha|up;bravo|down",
                "VMSRUN": "1",
                "VMSSTOP": "0",
                "VMSPAUSE": "0",
                "VMSOTHER": "0",
                "VMS": "vm-a|running|2|2048|Running",
            },
            "integration_health": {
                "host": {
                    "integration_id": "host",
                    "enabled": True,
                    "available": True,
                    "source": "local",
                    "last_refresh_age_s": 1.0,
                    "last_success_age_s": 1.0,
                    "last_error": None,
                    "commands": ["host_shutdown", "host_restart"],
                },
                "docker": {
                    "integration_id": "docker",
                    "enabled": True,
                    "available": True,
                    "source": "docker_socket",
                    "last_refresh_age_s": 1.0,
                    "last_success_age_s": 1.0,
                    "last_error": None,
                    "commands": ["docker_start", "docker_stop"],
                },
                "vms": {
                    "integration_id": "vms",
                    "enabled": True,
                    "available": True,
                    "source": "virsh",
                    "last_refresh_age_s": 1.0,
                    "last_success_age_s": 1.0,
                    "last_error": None,
                    "commands": ["vm_start", "vm_stop", "vm_force_stop", "vm_restart"],
                },
            },
            "command_registry": [
                {"command_id": "host_shutdown", "owner_id": "host", "patterns": ["shutdown"]},
                {"command_id": "docker_start", "owner_id": "docker", "patterns": ["docker_start:"]},
                {"command_id": "vm_start", "owner_id": "vms", "patterns": ["vm_start:"]},
            ],
        }

        with mock.patch(
            "esp_host_bridge.runtime.redact_agent_command_args",
            side_effect=lambda argv, mask: list(argv[:-1]) + [mask],
        ):
            payload = build_browser_status_payload(
                base_status,
                homeassistant_mode=False,
                redact_mask="***",
            )

        self.assertEqual(payload["cmd"][-1], "***")
        self.assertIn("preview_ui", payload)
        self.assertIn("summary_bar", payload)
        self.assertIn("monitor_dashboard", payload)
        self.assertIn("monitor_detail_payloads", payload)
        self.assertEqual(payload["preview_ui"]["pages"]["docker"]["render_kind"], "workload_list")
        self.assertEqual(payload["monitor_detail_payloads"]["docker_list"]["items"][0]["name"], "alpha")
        self.assertEqual(payload["integration_overview"]["ready_text"], "3/3 ready")


if __name__ == "__main__":
    unittest.main()

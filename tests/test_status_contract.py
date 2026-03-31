from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from esp_host_bridge.integrations import command_registry_snapshot
from esp_host_bridge.webui_app import create_app


class StatusContractTests(unittest.TestCase):
    def test_api_status_exposes_browser_contract(self) -> None:
        fake_status = {
            "host_name": "test-host",
            "bridge_version": "2026.03.31.dev10",
            "platform_mode": "host",
            "running": True,
            "pid": 1234,
            "started_at": 100.0,
            "last_exit": None,
            "cmd": ["python3", "-m", "esp_host_bridge", "agent"],
            "next_log_id": 10,
            "next_comm_log_id": 4,
            "comm_status": {
                "serial_connected": True,
                "serial_disconnect_count": 0,
                "last_serial_disconnect_at": None,
                "last_serial_reconnect_at": 120.0,
                "last_comm_event_at": 125.0,
                "last_comm_event_age_s": 1.5,
                "last_comm_event_text": "serial connected",
            },
            "esp_status": {
                "boot_count": 1,
                "last_boot_at": 110.0,
                "last_boot_age_s": 9.0,
                "last_boot_id": "boot-1",
                "last_boot_reason": "POWERON",
                "display_sleeping": False,
                "wifi_state": "CONNECTED",
                "wifi_rssi_dbm": -58,
                "wifi_ip": "10.0.1.9",
                "wifi_ssid": "ssid",
                "wifi_age_s": 2.0,
            },
            "last_metrics_at": 126.0,
            "last_metrics_age_s": 0.5,
            "last_metrics": {
                "CPU": "15.2",
                "MEM": "42.4",
                "TEMP": "61.3",
                "RX": "120",
                "TX": "40",
                "DISK": "39.0",
                "DISKPCT": "51.5",
                "GPUU": "8",
                "GPUT": "58.2",
                "GPUVM": "14",
                "FAN": "0",
                "UP": "12345",
                "DOCKRUN": "1",
                "DOCKSTOP": "1",
                "DOCKUNH": "0",
                "DOCKER": "alpha|up;bravo|down",
                "VMSRUN": "1",
                "VMSSTOP": "0",
                "VMSPAUSE": "0",
                "VMSOTHER": "0",
                "VMS": "vm-test|running|2|2048|Running",
                "IFACE": "en13",
                "POWER": "RUNNING",
            },
            "last_metrics_line": "CPU=15.2,...",
            "active_iface": "en13",
            "integration_health": {
                "host": {
                    "integration_id": "host",
                    "enabled": True,
                    "available": True,
                    "source": "local",
                    "last_refresh_ts": 120.0,
                    "last_success_ts": 120.0,
                    "last_error": None,
                    "last_error_ts": None,
                    "commands": ["host_shutdown", "host_restart"],
                    "last_refresh_age_s": 1.0,
                    "last_success_age_s": 1.0,
                },
                "docker": {
                    "integration_id": "docker",
                    "enabled": True,
                    "available": True,
                    "source": "docker_socket",
                    "last_refresh_ts": 120.0,
                    "last_success_ts": 120.0,
                    "last_error": None,
                    "last_error_ts": None,
                    "commands": ["docker_start", "docker_stop"],
                    "last_refresh_age_s": 1.0,
                    "last_success_age_s": 1.0,
                },
                "vms": {
                    "integration_id": "vms",
                    "enabled": True,
                    "available": True,
                    "source": "virsh",
                    "last_refresh_ts": 120.0,
                    "last_success_ts": 120.0,
                    "last_error": None,
                    "last_error_ts": None,
                    "commands": ["vm_start", "vm_stop", "vm_force_stop", "vm_restart"],
                    "last_refresh_age_s": 1.0,
                    "last_success_age_s": 1.0,
                },
            },
            "command_registry": command_registry_snapshot(),
            "metric_history": {"CPU": [10.0, 15.0], "MEM": [40.0, 42.0]},
        }

        class FakeRunnerManager:
            def __init__(self, self_script: Path, python_bin: str, package_module: str | None = None) -> None:
                self.self_script = self_script
                self.python_bin = python_bin
                self.package_module = package_module

            def status(self):
                return dict(fake_status)

            def stop_noexcept(self) -> None:
                return None

            def log_event(self, line: str) -> None:
                return None

        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            with (
                mock.patch("esp_host_bridge.webui_app.RunnerManager", FakeRunnerManager),
                mock.patch("esp_host_bridge.webui_app.default_webui_config_path", return_value=cfg_path),
                mock.patch("esp_host_bridge.webui_app.migrate_legacy_webui_config", return_value=(cfg_path, False, None)),
                mock.patch(
                    "esp_host_bridge.webui_app.load_cfg",
                    return_value={"webui_session_secret": "test-secret", "webui_auth_enabled": False},
                ),
                mock.patch(
                    "esp_host_bridge.webui_app.ensure_webui_session_secret",
                    side_effect=lambda cfg: (cfg, False),
                ),
                mock.patch("esp_host_bridge.webui_app.atomic_write_json"),
            ):
                app = create_app(autostart_override=False)
                client = app.test_client()
                response = client.get("/api/status")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIsInstance(payload, dict)
        assert isinstance(payload, dict)

        for key in (
            "bridge_version",
            "running",
            "comm_status",
            "esp_status",
            "last_metrics",
            "metric_history",
            "integration_health",
            "command_registry",
            "integration_dashboard",
            "monitor_dashboard",
            "monitor_details",
            "monitor_detail_payloads",
            "preview_ui",
            "preview_cards",
            "preview_action_groups",
            "summary_bar",
            "integration_overview",
        ):
            self.assertIn(key, payload)

        self.assertEqual(payload["bridge_version"], "2026.03.31.dev10")
        self.assertTrue(payload["running"])
        self.assertTrue(payload["comm_status"]["serial_connected"])
        self.assertEqual(payload["last_metrics"]["DOCKER"], "alpha|up;bravo|down")
        self.assertEqual(payload["last_metrics"]["VMS"], "vm-test|running|2|2048|Running")
        self.assertEqual(payload["preview_ui"]["pages"]["home"]["render_kind"], "home")
        self.assertEqual(payload["preview_ui"]["pages"]["docker"]["render_kind"], "workload_list")
        self.assertEqual(payload["preview_ui"]["pages"]["settings_1"]["render_kind"], "brightness")
        self.assertEqual(payload["preview_ui"]["pages"]["settings_2"]["render_kind"], "power")
        self.assertEqual(payload["monitor_detail_payloads"]["docker_list"]["items"][0]["name"], "alpha")
        self.assertEqual(payload["monitor_detail_payloads"]["vm_list"]["items"][0]["name"], "vm-test")
        self.assertEqual(payload["integration_overview"]["ready_text"], "3/3 ready")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from esp_host_bridge import mac
from esp_host_bridge import metrics as metrics_mod
from esp_host_bridge import runtime as runtime_mod
from esp_host_bridge import webui_app
from esp_host_bridge.integrations import host as host_integration_mod


class MacOverrideTests(unittest.TestCase):
    def test_apply_mac_overrides_patches_host_probe_refs(self) -> None:
        mac._apply_mac_overrides()

        self.assertIs(metrics_mod.get_cpu_temp_c, mac.mac_get_cpu_temp_c)
        self.assertIs(runtime_mod.get_cpu_temp_c, mac.mac_get_cpu_temp_c)
        self.assertIs(host_integration_mod.get_cpu_temp_c, mac.mac_get_cpu_temp_c)

        self.assertIs(metrics_mod.get_fan_rpm, mac.mac_get_fan_rpm)
        self.assertIs(runtime_mod.get_fan_rpm, mac.mac_get_fan_rpm)
        self.assertIs(host_integration_mod.get_fan_rpm, mac.mac_get_fan_rpm)

        self.assertIs(metrics_mod.get_gpu_metrics, mac.mac_get_gpu_metrics)
        self.assertIs(runtime_mod.get_gpu_metrics, mac.mac_get_gpu_metrics)
        self.assertIs(host_integration_mod.get_gpu_metrics, mac.mac_get_gpu_metrics)

    def test_create_app_uses_wrapper_script_for_agent_handoff(self) -> None:
        captured: dict[str, object] = {}

        class FakeRunnerManager:
            def __init__(self, self_script: Path, python_bin: str, package_module: str | None = None) -> None:
                captured["self_script"] = self_script
                captured["python_bin"] = python_bin
                captured["package_module"] = package_module

            def stop_noexcept(self) -> None:
                return None

        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            with (
                mock.patch.dict(os.environ, {"PORTABLE_HOST_METRICS_SCRIPT": "/tmp/fake-mac-wrapper.py"}, clear=False),
                mock.patch.object(webui_app, "RunnerManager", FakeRunnerManager),
                mock.patch.object(webui_app, "default_webui_config_path", return_value=cfg_path),
                mock.patch.object(webui_app, "load_cfg", return_value={"webui_session_secret": "test-secret"}),
                mock.patch.object(webui_app, "ensure_webui_session_secret", side_effect=lambda cfg: (cfg, False)),
                mock.patch.object(webui_app, "atomic_write_json"),
            ):
                app = webui_app.create_app(autostart_override=False)
                self.assertIsNotNone(app)

        self.assertEqual(captured["self_script"], Path("/tmp/fake-mac-wrapper.py"))
        self.assertIsNone(captured["package_module"])


if __name__ == "__main__":
    unittest.main()

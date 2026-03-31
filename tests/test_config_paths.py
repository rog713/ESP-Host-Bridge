from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from esp_host_bridge import config as config_mod


class ConfigPathTests(unittest.TestCase):
    def test_default_webui_config_path_honors_env_override(self) -> None:
        with mock.patch.dict(os.environ, {"WEBUI_CONFIG": "/tmp/custom-config.json"}, clear=False):
            self.assertEqual(config_mod.default_webui_config_path(), Path("/tmp/custom-config.json"))

    def test_default_webui_config_path_uses_macos_app_support(self) -> None:
        fake_home = Path("/tmp/fake-home")
        with mock.patch.dict(os.environ, {"WEBUI_CONFIG": ""}, clear=False), mock.patch.object(
            config_mod.sys, "platform", "darwin"
        ), mock.patch.object(config_mod.Path, "home", return_value=fake_home):
            self.assertEqual(
                config_mod.default_webui_config_path(),
                fake_home / "Library" / "Application Support" / "ESP Host Bridge" / "config.json",
            )

    def test_default_webui_config_path_uses_xdg_on_linux(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"WEBUI_CONFIG": "", "XDG_CONFIG_HOME": "/tmp/xdg-config"},
            clear=False,
        ), mock.patch.object(config_mod.sys, "platform", "linux"):
            self.assertEqual(
                config_mod.default_webui_config_path(),
                Path("/tmp/xdg-config/esp-host-bridge/config.json"),
            )

    def test_migrate_legacy_webui_config_prefers_real_config_over_default_package_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "stable" / "config.json"
            legacy_default = root / "dev" / "esp_host_bridge" / "config.json"
            legacy_real = root / "old" / "esp_host_bridge" / "config.json"
            legacy_default.parent.mkdir(parents=True, exist_ok=True)
            legacy_real.parent.mkdir(parents=True, exist_ok=True)

            legacy_default.write_text(
                json.dumps(config_mod.webui_default_cfg(), indent=2, sort_keys=True),
                encoding="utf-8",
            )

            configured = config_mod.webui_default_cfg()
            configured.update(
                {
                    "serial_port": "/dev/cu.usbmodem-test",
                    "iface": "en13",
                    "cpu_temp_sensor": "macmon:cpu_temp",
                    "disk_device": "/dev/disk3",
                    "disk_temp_device": "/dev/disk3",
                }
            )
            legacy_real.write_text(json.dumps(configured, indent=2, sort_keys=True), encoding="utf-8")

            os.utime(legacy_real, (100.0, 100.0))
            os.utime(legacy_default, (200.0, 200.0))

            with mock.patch.object(
                config_mod,
                "legacy_webui_config_paths",
                return_value=(legacy_default, legacy_real),
            ):
                path, migrated, source = config_mod.migrate_legacy_webui_config(target)

            self.assertTrue(migrated)
            self.assertEqual(path, target)
            self.assertEqual(source, legacy_real)
            loaded = config_mod.load_cfg(target)
            self.assertEqual(loaded["serial_port"], "/dev/cu.usbmodem-test")
            self.assertEqual(loaded["iface"], "en13")

    def test_migrate_legacy_webui_config_does_not_overwrite_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "stable" / "config.json"
            legacy = root / "old" / "esp_host_bridge" / "config.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            legacy.parent.mkdir(parents=True, exist_ok=True)

            current = config_mod.webui_default_cfg()
            current["serial_port"] = "/dev/current"
            target.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")

            older = config_mod.webui_default_cfg()
            older["serial_port"] = "/dev/older"
            legacy.write_text(json.dumps(older, indent=2, sort_keys=True), encoding="utf-8")

            with mock.patch.object(config_mod, "legacy_webui_config_paths", return_value=(legacy,)):
                path, migrated, source = config_mod.migrate_legacy_webui_config(target)

            self.assertEqual(path, target)
            self.assertFalse(migrated)
            self.assertIsNone(source)
            loaded = config_mod.load_cfg(target)
            self.assertEqual(loaded["serial_port"], "/dev/current")


if __name__ == "__main__":
    unittest.main()

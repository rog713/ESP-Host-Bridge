from __future__ import annotations

import unittest

from esp_host_bridge import mac
from esp_host_bridge import metrics as metrics_mod
from esp_host_bridge import runtime as runtime_mod
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


if __name__ == "__main__":
    unittest.main()

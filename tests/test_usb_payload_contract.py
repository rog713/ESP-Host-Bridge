from __future__ import annotations

import argparse
import unittest
from unittest import mock

from esp_host_bridge.runtime import RuntimeState, build_status_line


class UsbPayloadContractTests(unittest.TestCase):
    def test_host_mode_status_line_rotation_stays_stable(self) -> None:
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

        with (
            mock.patch("esp_host_bridge.runtime.poll_integrations", return_value=polled),
            mock.patch("esp_host_bridge.runtime.is_home_assistant_app_mode", return_value=False),
            mock.patch("esp_host_bridge.runtime.SUPERVISOR_TOKEN", ""),
        ):
            lines = [build_status_line(args, state) for _ in range(5)]

        self.assertEqual(
            lines,
            [
                "CPU=12.3,TEMP=45.6,MEM=67.8,UP=1234,RX=10,TX=20,IFACE=en13,TEMPAV=1,HAMODE=0,HATOKEN=0,HADOCKAPI=-1,HAVMSAPI=-1,GPUEN=1,DOCKEREN=1,VMSEN=1,POWER=RUNNING\n",
                "DISK=51.2,DISKPCT=73.4,DISKR=30,DISKW=40,FAN=1234,DISKTAV=1,FANAV=1,POWER=RUNNING\n",
                "GPUT=65.4,GPUU=9,GPUVM=27,GPUAV=1,POWER=RUNNING\n",
                "DOCKRUN=1,DOCKSTOP=2,DOCKUNH=3,DOCKER=alpha|up;bravo|down,POWER=RUNNING\n",
                "VMSRUN=4,VMSSTOP=5,VMSPAUSE=6,VMSOTHER=7,VMS=vm-a|running|2|2048|Running,POWER=RUNNING\n",
            ],
        )


if __name__ == "__main__":
    unittest.main()

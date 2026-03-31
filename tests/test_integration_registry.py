from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from esp_host_bridge.config import (
    REDACTED_SECRET_TEXT,
    cfg_to_agent_args,
    preserve_secret_fields,
    redact_cfg,
)
from esp_host_bridge.integrations import (
    command_registry_snapshot,
    dispatch_integration_command,
    get_integration_spec,
    get_registered_config_fields,
    integration_dashboard_snapshot,
    integration_health_snapshot,
    integration_overview_snapshot,
    monitor_dashboard_snapshot,
    monitor_detail_payload_snapshot,
    monitor_detail_snapshot,
    preview_cards_snapshot,
    preview_action_groups_snapshot,
    preview_ui_snapshot,
    redact_agent_command_args,
    summary_bar_snapshot,
)
from esp_host_bridge.integrations import registry as registry_mod
from esp_host_bridge.integrations.base import CommandContext, CommandSpec, ConfigFieldSpec, IntegrationSpec
from esp_host_bridge.runtime import (
    RunnerManager,
    build_host_power_command_defaults,
    build_host_power_command_previews,
)


class IntegrationRegistryTests(unittest.TestCase):
    def test_registered_field_names_include_current_integrations(self) -> None:
        names = {field.name for field in get_registered_config_fields()}
        self.assertTrue(
            {
                "iface",
                "gpu_polling_enabled",
                "disk_device",
                "disk_temp_device",
                "cpu_temp_sensor",
                "fan_sensor",
                "docker_socket",
                "docker_polling_enabled",
                "docker_interval",
                "virsh_binary",
                "vm_polling_enabled",
                "vm_interval",
            }.issubset(names)
        )

    def test_host_docker_and_vm_specs_expose_setup_ui_metadata(self) -> None:
        host = get_integration_spec("host")
        docker = get_integration_spec("docker")
        vms = get_integration_spec("vms")
        self.assertIsNotNone(host)
        self.assertIsNotNone(docker)
        self.assertIsNotNone(vms)
        assert host is not None
        assert docker is not None
        assert vms is not None
        self.assertEqual(host.section_key, "telemetry_sources")
        self.assertEqual(docker.section_key, "docker")
        self.assertEqual(vms.section_key, "virtual_machines")
        self.assertTrue(host.title)
        self.assertTrue(docker.title)
        self.assertTrue(vms.title)
        field_map = {field.name: field for field in host.config_fields}
        self.assertEqual(field_map["iface"].input_id, "ifaceInput")
        self.assertEqual(field_map["disk_device"].input_id, "diskDeviceInput")
        self.assertEqual(field_map["disk_temp_device"].input_id, "diskTempDeviceInput")
        self.assertEqual(field_map["cpu_temp_sensor"].input_id, "cpuTempSensorInput")
        self.assertEqual(field_map["cpu_temp_sensor"].chip_id, "cpuTempSensorChip")
        self.assertEqual(field_map["fan_sensor"].input_id, "fanSensorInput")
        self.assertEqual(field_map["fan_sensor"].chip_id, "fanSensorChip")

        choice_map = {choice.label: choice for choice in host.setup_choices}
        self.assertEqual(choice_map["Detected Interfaces"].select_id, "ifaceSelect")
        self.assertEqual(choice_map["Detected Disk Devices"].refresh_button_id, "refreshDiskBtn")
        self.assertEqual(choice_map["Detected CPU Temp Sensors"].result_id, "cpuTempSensorResult")
        self.assertEqual(choice_map["Detected Fan Sensors"].buttons[0].button_id, "useFanSensorBtn")

        for field in host.config_fields + docker.config_fields + vms.config_fields:
            self.assertTrue(field.label)
            self.assertTrue(field.section_key)
            if field.readonly_when_homeassistant:
                self.assertTrue(field.homeassistant_value)

    def test_command_registry_snapshot_exposes_expected_owners(self) -> None:
        snapshot = command_registry_snapshot()
        ids = {row["command_id"] for row in snapshot}
        owners = {row["owner_id"] for row in snapshot}
        self.assertTrue({"host", "docker", "vms"}.issubset(owners))
        self.assertTrue(
            {
                "host_shutdown",
                "host_restart",
                "docker_start",
                "docker_stop",
                "vm_start",
                "vm_stop",
                "vm_force_stop",
                "vm_restart",
            }.issubset(ids)
        )

    def test_integration_dashboard_snapshot_exposes_labels_and_action_groups(self) -> None:
        default_rows = integration_dashboard_snapshot(homeassistant_mode=False)
        homeassistant_rows = integration_dashboard_snapshot(homeassistant_mode=True)

        by_id = {row["integration_id"]: row for row in default_rows}
        by_id_ha = {row["integration_id"]: row for row in homeassistant_rows}

        self.assertEqual([row["integration_id"] for row in default_rows], ["host", "docker", "vms"])
        self.assertEqual(by_id["host"]["label"], "Telemetry Sources")
        self.assertEqual(by_id["host"]["action_group_title"], "Host Power")
        self.assertEqual(by_id["docker"]["label"], "Docker")
        self.assertEqual(by_id["docker"]["action_group_title"], "Docker Controls")
        self.assertEqual(by_id["vms"]["action_group_title"], "VM Controls")

        self.assertEqual(by_id_ha["docker"]["label"], "Add-ons")
        self.assertEqual(by_id_ha["docker"]["action_group_title"], "Add-on Controls")
        self.assertEqual(by_id_ha["vms"]["label"], "Integrations")
        self.assertEqual(by_id_ha["vms"]["action_group_title"], "Integration Controls")

    def test_monitor_dashboard_snapshot_exposes_grouped_cards(self) -> None:
        default_rows = monitor_dashboard_snapshot(homeassistant_mode=False)
        homeassistant_rows = monitor_dashboard_snapshot(homeassistant_mode=True)

        self.assertEqual(
            [row["group_id"] for row in default_rows],
            ["host_system", "host_network_storage", "host_cooling_gpu", "docker_summary", "vms_summary"],
        )

        system_group = default_rows[0]
        docker_group_ha = next(row for row in homeassistant_rows if row["group_id"] == "docker_summary")
        vms_group_ha = next(row for row in homeassistant_rows if row["group_id"] == "vms_summary")

        self.assertEqual(system_group["title"], "System")
        self.assertEqual(system_group["cards"][0]["card_id"], "CPU")
        self.assertEqual(system_group["cards"][0]["render_kind"], "percent_one_decimal")
        self.assertEqual(system_group["cards"][0]["spark_keys"], ["CPU"])
        self.assertEqual(system_group["cards"][0]["spark_color"], "#60a5fa")
        self.assertEqual(system_group["cards"][3]["render_kind"], "uptime")

        self.assertEqual(docker_group_ha["title"], "Add-ons")
        self.assertEqual(docker_group_ha["cards"][0]["label"], "Add-on Summary")
        self.assertEqual(docker_group_ha["cards"][0]["subtext"], "Started / Stopped / Issue")

        self.assertEqual(vms_group_ha["title"], "Integrations")
        self.assertEqual(vms_group_ha["cards"][0]["label"], "Integration Summary")
        self.assertEqual(vms_group_ha["cards"][0]["subtext"], "Loaded integrations")

    def test_monitor_detail_snapshot_exposes_workload_sections(self) -> None:
        default_rows = monitor_detail_snapshot(homeassistant_mode=False)
        homeassistant_rows = monitor_detail_snapshot(homeassistant_mode=True)

        self.assertEqual([row["detail_id"] for row in default_rows], ["docker_list", "vm_list"])

        docker_default = default_rows[0]
        docker_ha = homeassistant_rows[0]
        vm_ha = homeassistant_rows[1]

        self.assertEqual(docker_default["title"], "Containers")
        self.assertEqual(docker_default["render_kind"], "status_list")
        self.assertEqual(docker_default["waiting_text"], "Waiting for Docker data...")
        self.assertEqual(docker_default["show_all_text"], "Show all containers")

        self.assertEqual(docker_ha["title"], "Add-ons")
        self.assertEqual(docker_ha["waiting_text"], "Waiting for add-on data...")
        self.assertEqual(docker_ha["show_all_text"], "Show all add-ons")

        self.assertEqual(vm_ha["title"], "Integrations")
        self.assertEqual(vm_ha["render_kind"], "status_list")
        self.assertEqual(vm_ha["show_all_text"], "Show all integrations")

    def test_monitor_detail_payload_snapshot_normalizes_workload_rows(self) -> None:
        payloads = monitor_detail_payload_snapshot(
            {
                "DOCKER": "plex|up;db|down",
                "VMS": "ubuntu|running|2|4096|Running;test|paused|2|2048|Paused",
            },
            homeassistant_mode=False,
        )
        self.assertEqual([row["name"] for row in payloads["docker_list"]["items"]], ["plex", "db"])
        self.assertEqual(payloads["docker_list"]["items"][0]["state_class"], "up")
        self.assertEqual(payloads["docker_list"]["hint"], "2 containers detected")
        self.assertEqual([row["name"] for row in payloads["vm_list"]["items"]], ["ubuntu", "test"])
        self.assertEqual(payloads["vm_list"]["items"][0]["state_class"], "running")
        self.assertEqual(payloads["vm_list"]["hint"], "2 virtual machines detected")

    def test_integration_overview_snapshot_derives_cards_rows_and_groups(self) -> None:
        health = {
            "host": {
                "enabled": True,
                "available": True,
                "source": "local",
                "last_refresh_age_s": 3,
                "last_success_age_s": 5,
                "last_error": None,
                "commands": ["host_shutdown", "host_restart"],
            },
            "docker": {
                "enabled": True,
                "available": False,
                "source": "docker socket",
                "last_refresh_age_s": 12,
                "last_success_age_s": 90,
                "last_error": "socket unavailable",
                "commands": ["docker_start", "docker_stop"],
            },
        }
        commands = command_registry_snapshot()
        overview = integration_overview_snapshot(health, commands, homeassistant_mode=False)
        self.assertEqual(overview["ready_text"], "1/2 ready")
        self.assertEqual(overview["dashboard_cards"][0]["integration_id"], "host")
        self.assertEqual(overview["dashboard_cards"][0]["status_text"], "Ready")
        self.assertEqual(overview["dashboard_cards"][1]["integration_id"], "docker")
        self.assertEqual(overview["dashboard_cards"][1]["status_class"], "danger")
        self.assertEqual(overview["health_chips"][0]["text"], "Telemetry Sources: Ready")
        self.assertEqual(overview["health_rows"][1]["error_text"], "socket unavailable")
        self.assertEqual(overview["command_groups"][0]["owner_id"], "host")
        self.assertIn("registered commands", overview["command_hint"])

    def test_preview_action_groups_snapshot_derives_modal_actions(self) -> None:
        default_groups = preview_action_groups_snapshot(homeassistant_mode=False)
        ha_groups = preview_action_groups_snapshot(homeassistant_mode=True)
        self.assertEqual([group["target"] for group in default_groups], ["docker", "vms"])
        docker_group = default_groups[0]
        vm_group = default_groups[1]
        self.assertEqual([row["command_id"] for row in docker_group["actions"]], ["docker_start", "docker_stop"])
        self.assertEqual(docker_group["actions"][1]["destructive"], True)
        self.assertEqual(docker_group["actions"][1]["optimistic_patch"]["state"], "down")
        self.assertEqual(vm_group["footnote"], "Hold Stop on the device for force off")
        self.assertEqual([row["command_id"] for row in vm_group["actions"]], ["vm_start", "vm_stop", "vm_restart"])
        self.assertEqual([group["target"] for group in ha_groups], ["docker"])

    def test_preview_cards_snapshot_exposes_host_and_workload_preview_cards(self) -> None:
        default_rows = preview_cards_snapshot(homeassistant_mode=False)
        homeassistant_rows = preview_cards_snapshot(homeassistant_mode=True)

        self.assertEqual([row["card_id"] for row in default_rows], ["CPU", "MEM", "TEMP", "NET", "DISK", "DOCKER", "VMS"])
        self.assertEqual(default_rows[0]["label"], "CPU")
        self.assertEqual(default_rows[0]["icon_class"], "mdi-cpu-64-bit")
        self.assertEqual(default_rows[3]["render_kind"], "pair_metric")
        self.assertEqual(default_rows[4]["render_kind"], "disk_temp_usage")

        docker_ha = next(row for row in homeassistant_rows if row["card_id"] == "DOCKER")
        vms_ha = next(row for row in homeassistant_rows if row["card_id"] == "VMS")
        self.assertEqual(docker_ha["label"], "Add-ons")
        self.assertEqual(docker_ha["icon_class"], "mdi-puzzle-outline")
        self.assertEqual(docker_ha["subtext"], "On / Off / Issue")
        self.assertEqual(vms_ha["label"], "Integrations")
        self.assertEqual(vms_ha["icon_class"], "mdi-devices")

    def test_preview_ui_snapshot_exposes_pages_tabs_and_modals(self) -> None:
        default_ui = preview_ui_snapshot(homeassistant_mode=False)
        homeassistant_ui = preview_ui_snapshot(homeassistant_mode=True)

        self.assertEqual(default_ui["mode"], "host")
        self.assertEqual(
            default_ui["page_order"],
            ["home", "docker", "settings_1", "settings_2", "info_1", "info_2", "info_3", "info_4", "info_5", "info_6", "info_7", "info_8", "vms"],
        )
        self.assertEqual(default_ui["pages"]["docker"]["title"], "Docker")
        self.assertEqual(default_ui["pages"]["docker"]["render_kind"], "workload_list")
        self.assertEqual(default_ui["pages"]["docker"]["render_data"]["rows_id"], "espDockerRows")
        self.assertEqual(default_ui["pages"]["docker"]["nav"], {"down": "home"})
        self.assertEqual(default_ui["pages"]["home"]["render_kind"], "home")
        self.assertEqual(default_ui["pages"]["settings_1"]["render_kind"], "brightness")
        self.assertEqual(default_ui["pages"]["info_1"]["render_kind"], "dual_metric_graph")
        self.assertEqual(default_ui["pages"]["info_1"]["render_data"]["scale_id"], "espNetScale")
        self.assertEqual(default_ui["pages"]["info_1"]["render_data"]["left_unit"], "MB/s")
        self.assertEqual(default_ui["pages"]["info_1"]["render_data"]["right_unit"], "MB/s")
        self.assertEqual(default_ui["pages"]["info_2"]["render_kind"], "system_graph")
        self.assertEqual(default_ui["pages"]["info_3"]["render_kind"], "metric_graph")
        self.assertEqual(default_ui["pages"]["settings_1"]["nav"], {"up": "home", "left": "settings_2", "right": "settings_2"})
        self.assertEqual(default_ui["pages"]["info_1"]["indicator_count"], 8)
        self.assertEqual(default_ui["tabs"][0]["page_id"], "home")
        self.assertEqual(default_ui["home_buttons"][0]["position"], "bl")
        self.assertEqual(default_ui["modals"]["docker"]["title"], "Docker")
        self.assertEqual(default_ui["modals"]["vms"]["icon_class"], "mdi-monitor-multiple")

        self.assertEqual(homeassistant_ui["mode"], "homeassistant")
        self.assertEqual(homeassistant_ui["pages"]["docker"]["title"], "Add-ons")
        self.assertEqual(homeassistant_ui["pages"]["docker"]["tab_icon_class"], "mdi-puzzle-outline")
        self.assertEqual(homeassistant_ui["pages"]["vms"]["title"], "INTEGRATIONS")
        self.assertEqual(homeassistant_ui["modals"]["docker"]["subtitle"], "Home Assistant app control")
        self.assertEqual(homeassistant_ui["modals"]["vms"]["title"], "Integrations")

    def test_summary_bar_snapshot_exposes_expected_chip_metadata(self) -> None:
        default_rows = summary_bar_snapshot(homeassistant_mode=False)
        homeassistant_rows = summary_bar_snapshot(homeassistant_mode=True)

        self.assertEqual([row["chip_id"] for row in default_rows], ["Agent", "Workloads", "Age", "Integrations", "Power"])
        self.assertEqual(default_rows[1]["label"], "Serial / Workloads")
        self.assertEqual(default_rows[1]["render_kind"], "workload_summary")
        self.assertEqual(default_rows[4]["metric_key"], "POWER")
        self.assertEqual(default_rows[4]["fallback_text"], "RUNNING")

        self.assertEqual(homeassistant_rows[1]["label"], "Serial / HA")

    def test_cfg_to_agent_args_and_redaction_cover_registered_integrations(self) -> None:
        cfg = {
            "baud": 115200,
            "interval": 1.0,
            "timeout": 2.0,
            "serial_port": "/dev/ttyUSB0",
            "iface": "eth0",
            "gpu_polling_enabled": False,
            "disk_device": "/dev/nvme0n1",
            "disk_temp_device": "/dev/nvme0n1",
            "cpu_temp_sensor": "/tmp/cpu.temp",
            "fan_sensor": "fan1",
            "docker_socket": "/var/run/docker.sock",
            "docker_polling_enabled": True,
            "docker_interval": 2.0,
            "virsh_binary": "virsh",
            "vm_polling_enabled": True,
            "vm_interval": 5.0,
            "allow_host_cmds": False,
            "host_cmd_use_sudo": False,
            "shutdown_cmd": "",
            "restart_cmd": "",
            "webui_auth_enabled": False,
            "webui_password_hash": "",
            "webui_session_secret": "",
        }
        argv = cfg_to_agent_args(cfg)
        self.assertIn("--iface", argv)
        self.assertIn("eth0", argv)
        self.assertIn("--disable-gpu-polling", argv)
        self.assertIn("--docker-socket", argv)
        self.assertIn("/var/run/docker.sock", argv)
        self.assertIn("--virsh-binary", argv)
        self.assertIn("virsh", argv)

        fake_secret_field = ConfigFieldSpec("demo_secret", "str", "", secret=True, cli_flag="--demo-secret")
        with mock.patch(
            "esp_host_bridge.integrations.registry.get_registered_secret_config_fields",
            return_value=(fake_secret_field,),
        ):
            redacted = redact_agent_command_args(
                ["python3", "-m", "esp_host_bridge", "agent", "--demo-secret", "secret"],
                mask=REDACTED_SECRET_TEXT,
            )
        self.assertEqual(redacted[-1], REDACTED_SECRET_TEXT)

    def test_secret_preserve_and_redact_helpers_keep_masked_values(self) -> None:
        fake_secret_field = ConfigFieldSpec("demo_secret", "str", "", secret=True, cli_flag="--demo-secret")
        existing = {
            "webui_session_secret": "session-secret",
            "webui_password_hash": "password-hash",
            "demo_secret": "integration-secret",
        }
        candidate = {
            "webui_session_secret": "...",
            "webui_password_hash": "",
            "demo_secret": "xxx",
        }
        base_fields = tuple(get_registered_config_fields())
        with mock.patch(
            "esp_host_bridge.config.get_registered_secret_config_field_names",
            return_value=("demo_secret",),
        ), mock.patch(
            "esp_host_bridge.config.get_registered_config_fields",
            return_value=base_fields + (fake_secret_field,),
        ):
            preserved = preserve_secret_fields(candidate, existing, include_builtin=True)
            redacted = redact_cfg(existing)
        self.assertEqual(preserved["webui_session_secret"], "session-secret")
        self.assertEqual(preserved["webui_password_hash"], "password-hash")
        self.assertEqual(preserved["demo_secret"], "integration-secret")

        self.assertEqual(redacted["webui_session_secret"], REDACTED_SECRET_TEXT)
        self.assertEqual(redacted["webui_password_hash"], REDACTED_SECRET_TEXT)
        self.assertEqual(redacted["demo_secret"], REDACTED_SECRET_TEXT)

    def test_runner_manager_refreshes_health_from_metric_frames(self) -> None:
        mgr = RunnerManager(self_script=Path("/tmp/fake.py"), python_bin="python3", package_module="esp_host_bridge")
        mgr._integration_health_cache = {
            "host": {"enabled": True, "available": True, "last_refresh_ts": 0.0, "last_success_ts": 0.0},
            "docker": {"enabled": True, "available": True, "last_refresh_ts": 0.0, "last_success_ts": 0.0},
            "vms": {"enabled": True, "available": True, "last_refresh_ts": 0.0, "last_success_ts": 0.0},
        }
        mgr._refresh_integration_health_from_metrics({"CPU": "7.1", "DOCKRUN": "1", "VMSRUN": "0"}, 123.45)
        self.assertEqual(mgr._integration_health_cache["host"]["last_refresh_ts"], 123.45)
        self.assertEqual(mgr._integration_health_cache["docker"]["last_refresh_ts"], 123.45)
        self.assertEqual(mgr._integration_health_cache["vms"]["last_refresh_ts"], 123.45)

    def test_dispatch_integration_command_routes_to_matching_owner(self) -> None:
        calls: list[tuple[str, str]] = []

        def _docker_handler(cmd: str, ctx: CommandContext) -> bool:
            calls.append(("docker", cmd))
            return True

        def _vms_handler(cmd: str, ctx: CommandContext) -> bool:
            calls.append(("vms", cmd))
            return True

        fake_integrations = (
            IntegrationSpec(
                integration_id="docker",
                commands=(
                    CommandSpec("docker_start", "docker", ("docker_start:",), match_kind="prefix"),
                ),
                handle_command=_docker_handler,
            ),
            IntegrationSpec(
                integration_id="vms",
                commands=(
                    CommandSpec("vm_start", "vms", ("vm_start:",), match_kind="prefix"),
                ),
                handle_command=_vms_handler,
            ),
        )
        ctx = CommandContext(args=object(), state=object(), timeout=2.0, homeassistant_mode=False)
        with mock.patch.object(registry_mod, "_REGISTERED_INTEGRATIONS", fake_integrations):
            self.assertTrue(dispatch_integration_command("docker_start:plex", ctx))
            self.assertTrue(dispatch_integration_command("vm_start:ubuntu", ctx))
            self.assertFalse(dispatch_integration_command("unknown:thing", ctx))

        self.assertEqual(calls, [("docker", "docker_start:plex"), ("vms", "vm_start:ubuntu")])

    def test_integration_health_snapshot_prefers_polled_health_payloads(self) -> None:
        polled = {
            "host": {
                "enabled": True,
                "metrics": {"cpu_pct": 7.1},
                "health": {
                    "integration_id": "host",
                    "enabled": True,
                    "available": True,
                    "source": "local_probes",
                    "last_refresh_ts": 10.0,
                    "last_success_ts": 10.0,
                    "last_error": None,
                    "last_error_ts": None,
                    "commands": ["host_shutdown", "host_restart"],
                    "api_ok": None,
                },
            }
        }
        snapshot = integration_health_snapshot(polled)
        self.assertIn("host", snapshot)
        self.assertEqual(snapshot["host"]["source"], "local_probes")
        self.assertEqual(snapshot["host"]["commands"], ["host_shutdown", "host_restart"])

    def test_host_power_previews_follow_registered_host_commands(self) -> None:
        with mock.patch(
            "esp_host_bridge.runtime.resolve_host_command_argv",
            side_effect=lambda cmd, **kwargs: ([f"/fake/{cmd}"], None),
        ):
            items = build_host_power_command_previews(use_sudo=False)

        by_id = {row["command_id"]: row for row in items}
        self.assertIn("host_shutdown", by_id)
        self.assertIn("host_restart", by_id)
        self.assertEqual(by_id["host_shutdown"]["trigger"], "shutdown")
        self.assertEqual(by_id["host_shutdown"]["command"], "/fake/shutdown")
        self.assertEqual(by_id["host_restart"]["trigger"], "restart")
        self.assertEqual(by_id["host_restart"]["command"], "/fake/restart")

    def test_host_power_defaults_follow_registered_host_commands(self) -> None:
        with mock.patch(
            "esp_host_bridge.runtime.detect_host_power_command_defaults",
            return_value={
                "os": "linux",
                "shutdown_cmd": "systemctl poweroff",
                "restart_cmd": "systemctl reboot",
            },
        ):
            defaults = build_host_power_command_defaults()

        self.assertEqual(defaults["os"], "linux")
        by_id = {row["command_id"]: row for row in defaults["items"]}
        self.assertEqual(by_id["host_shutdown"]["trigger"], "shutdown")
        self.assertEqual(by_id["host_shutdown"]["default_command"], "systemctl poweroff")
        self.assertEqual(by_id["host_restart"]["trigger"], "restart")
        self.assertEqual(by_id["host_restart"]["default_command"], "systemctl reboot")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILES = [
    "install.sh",
    "setup.sh",
    "cellarctl",
    "cellar-update",
    "cellar_logger.py",
    "cellar_config.py",
    "cellar_core.py",
    "cellar_ui.py",
    "daily_report.py",
    "requirements.txt",
]


class ReleaseContractTests(unittest.TestCase):
    def test_runtime_files_have_no_carriage_returns(self) -> None:
        for name in RUNTIME_FILES:
            self.assertNotIn(b"\r", (ROOT / name).read_bytes(), name)

    def test_user_control_top_level_menu_is_locked(self) -> None:
        script = (ROOT / "cellar_ui.py").read_text(encoding="utf-8")
        for label in (
            '"Sensor"',
            '"Notifications"',
            '"System Status"',
            '"Advanced / Troubleshooting"',
        ):
            self.assertIn(label, script)
        self.assertIn("curses.wrapper(main)", script)
        self.assertIn("↑↓ Move", script)
        self.assertNotIn("--gauge", script)

    def test_notification_code_does_not_import_or_control_logger(self) -> None:
        script = (ROOT / "daily_report.py").read_text(encoding="utf-8")
        self.assertNotIn("import cellar_logger", script)
        self.assertNotIn("systemctl", script)

    def test_updater_installs_the_same_copy_it_validates(self) -> None:
        script = (ROOT / "cellar-update").read_text(encoding="utf-8")
        self.assertIn('CELLAR_SOURCE_DIR="$TEMP_DIR/repository"', script)
        self.assertIn("CELLAR_DEFER_UPDATER_INSTALL=1", script)

    def test_installer_enables_i2c_even_during_an_upgrade(self) -> None:
        script = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertIn("raspi-config", script)
        self.assertIn(
            "/usr/bin/raspi-config nonint do_i2c 0",
            script,
        )
        self.assertLess(
            script.index("/usr/bin/raspi-config nonint do_i2c 0"),
            script.index('if [[ "$MODE" == "--upgrade"'),
        )

    def test_sudo_rules_are_scoped(self) -> None:
        script = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertNotIn("NOPASSWD: ALL", script)
        self.assertNotIn(
            "cellar_config.py *",
            script,
        )
        for action in (
            "get *",
            "set-sensor *",
            "set-discord *",
            "remove-discord",
            "set-report-time *",
            "set-report-frequency *",
            "set-report-enabled *",
            "set-temperature-unit *",
            "show-sanitized",
            "backup",
            "restore *",
        ):
            self.assertIn(f"cellar_config.py {action}", script)
        for action in (
            "summary",
            "current",
            "recent *",
            "service *",
            "logs *",
            "config",
            "sensor-scan",
        ):
            self.assertIn(f"cellar_core.py {action}", script)
        self.assertIn(
            "cellar_logger.py --check-health-since *",
            script,
        )
        self.assertIn(
            "pip install --requirement $INSTALL_DIR/requirements.txt",
            script,
        )
        self.assertNotIn(
            "NOPASSWD: /usr/bin/systemctl",
            script,
        )

    def test_troubleshooting_has_a_read_only_sensor_scan(self) -> None:
        script = (ROOT / "cellar_ui.py").read_text(encoding="utf-8")
        core = (ROOT / "cellar_core.py").read_text(encoding="utf-8")
        self.assertIn('"Scan Connected Sensors"', script)
        self.assertIn('I2CDETECT = "/usr/sbin/i2cdetect"', core)
        self.assertIn("[I2CDETECT, \"-y\", \"1\"]", core)
        self.assertIn("Raw I2C scan:", core)

    def test_degree_words_are_not_user_facing(self) -> None:
        for name in (
            "setup.sh",
            "cellar_logger.py",
            "daily_report.py",
            "cellar_ui.py",
        ):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("deg F", text, name)
            self.assertNotIn("deg C", text, name)

    def test_report_frequency_and_graph_window_move_together(self) -> None:
        config_script = (ROOT / "cellar_config.py").read_text(encoding="utf-8")
        report_script = (ROOT / "daily_report.py").read_text(encoding="utf-8")
        control_script = (ROOT / "cellar_ui.py").read_text(encoding="utf-8")
        self.assertIn("VALID_REPORT_FREQUENCIES = {12, 24}", config_script)
        self.assertIn("read_recent_data(window_hours)", report_script)
        self.assertIn(
            'f"Cellar-pi - Last {window_hours} Hours"',
            report_script,
        )
        self.assertIn(
            '"Frequency / Graph Range"',
            control_script,
        )

    def test_v1_runtime_uses_only_the_supported_sht_family(self) -> None:
        for name in (
            "setup.sh",
            "cellar_ui.py",
            "cellar_logger.py",
            "requirements.txt",
        ):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("DHT11", text, name)
        self.assertIn(
            "adafruit-circuitpython-sht31d",
            (ROOT / "requirements.txt").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "adafruit-circuitpython-sht4x",
            (ROOT / "requirements.txt").read_text(encoding="utf-8"),
        )

        expected_sensors = ("SHT31", "SHT35", "SHT41", "SHT45")
        for name in ("setup.sh", "cellar_ui.py"):
            text = (ROOT / name).read_text(encoding="utf-8")
            for sensor in expected_sensors:
                self.assertIn(sensor, text, f"{sensor} missing from {name}")


if __name__ == "__main__":
    unittest.main()

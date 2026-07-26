from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cellar_config


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.config_file = root / "etc" / "config.ini"
        self.backup_dir = root / "data" / "backups"
        self.patchers = [
            patch.object(cellar_config, "CONFIG_FILE", self.config_file),
            patch.object(cellar_config, "BACKUP_DIR", self.backup_dir),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temporary_directory.cleanup()

    def save_defaults(self) -> None:
        cellar_config.save_config(cellar_config.default_config())

    def test_default_config_is_valid(self) -> None:
        cellar_config.validate(cellar_config.default_config())

    def test_all_supported_sht_models_validate(self) -> None:
        for sensor, address in (
            ("SHT31", "0x44"),
            ("SHT35", "0x45"),
            ("SHT41", "0x44"),
            ("SHT45", "0x44"),
        ):
            with self.subTest(sensor=sensor, address=address):
                config = cellar_config.default_config()
                config["sensor"]["type"] = sensor
                config["sensor"]["i2c_address"] = address
                cellar_config.validate(config)

    def test_sht3x_accepts_both_supported_addresses(self) -> None:
        for sensor in ("SHT31", "SHT35"):
            for address in ("0x44", "0x45"):
                with self.subTest(sensor=sensor, address=address):
                    config = cellar_config.default_config()
                    config["sensor"]["type"] = sensor
                    config["sensor"]["i2c_address"] = address
                    cellar_config.validate(config)

    def test_sht4x_rejects_the_sht3x_alternate_address(self) -> None:
        for sensor in ("SHT41", "SHT45"):
            with self.subTest(sensor=sensor):
                config = cellar_config.default_config()
                config["sensor"]["type"] = sensor
                config["sensor"]["i2c_address"] = "0x45"
                with self.assertRaisesRegex(
                    ValueError,
                    "SHT41 and SHT45 use I2C address 0x44",
                ):
                    cellar_config.validate(config)

    def test_old_dht11_config_migrates_to_sht31(self) -> None:
        self.config_file.parent.mkdir(parents=True)
        self.config_file.write_text(
            "[general]\n"
            "temperature_unit = fahrenheit\n"
            "[sensor]\n"
            "type = DHT11\n"
            "gpio_pin = 4\n"
            "i2c_address = 0x44\n"
            "[discord]\n"
            "webhook_url =\n"
            "report_enabled = false\n"
            "report_time = 19:00\n",
            encoding="utf-8",
        )
        loaded = cellar_config.load_config()
        self.assertEqual(
            loaded.getint("logging", "failure_retry_seconds"),
            5,
        )
        cellar_config.migrate_config()
        migrated = cellar_config.load_config()
        self.assertEqual(migrated["sensor"]["type"], "SHT31")
        self.assertFalse(migrated.has_option("sensor", "gpio_pin"))
        cellar_config.validate(migrated)

    def test_sensor_change_preserves_discord_settings(self) -> None:
        config = cellar_config.default_config()
        config["discord"]["webhook_url"] = (
            "https://discord.com/api/webhooks/example/token"
        )
        config["discord"]["report_enabled"] = "true"
        cellar_config.save_config(config)

        cellar_config.mutate(
            argparse.Namespace(
                command="set-sensor",
                sensor="SHT31",
                i2c="0x45",
            )
        )
        changed = cellar_config.load_config()
        self.assertEqual(changed["sensor"]["type"], "SHT31")
        self.assertEqual(changed["sensor"]["i2c_address"], "0x45")
        self.assertEqual(
            changed["discord"]["webhook_url"],
            "https://discord.com/api/webhooks/example/token",
        )
        self.assertTrue(changed.getboolean("discord", "report_enabled"))

    def test_sht4x_sensor_change_preserves_discord_settings(self) -> None:
        config = cellar_config.default_config()
        config["discord"]["webhook_url"] = (
            "https://discord.com/api/webhooks/example/token"
        )
        config["discord"]["report_enabled"] = "true"
        cellar_config.save_config(config)

        cellar_config.mutate(
            argparse.Namespace(
                command="set-sensor",
                sensor="SHT45",
                i2c="0x44",
            )
        )
        changed = cellar_config.load_config()
        self.assertEqual(changed["sensor"]["type"], "SHT45")
        self.assertEqual(changed["sensor"]["i2c_address"], "0x44")
        self.assertEqual(
            changed["discord"]["webhook_url"],
            "https://discord.com/api/webhooks/example/token",
        )
        self.assertTrue(changed.getboolean("discord", "report_enabled"))

    def test_discord_change_preserves_sensor_settings(self) -> None:
        config = cellar_config.default_config()
        config["sensor"]["type"] = "SHT31"
        config["sensor"]["i2c_address"] = "0x45"
        cellar_config.save_config(config)
        cellar_config.mutate(
            argparse.Namespace(
                command="set-discord",
                webhook="https://discord.com/api/webhooks/example/token",
            )
        )
        changed = cellar_config.load_config()
        self.assertEqual(changed["sensor"]["type"], "SHT31")
        self.assertEqual(changed["sensor"]["i2c_address"], "0x45")

    def test_removing_discord_disables_report_only(self) -> None:
        config = cellar_config.default_config()
        config["discord"]["webhook_url"] = (
            "https://discord.com/api/webhooks/example/token"
        )
        config["discord"]["report_enabled"] = "true"
        cellar_config.save_config(config)
        cellar_config.mutate(
            argparse.Namespace(command="remove-discord")
        )
        changed = cellar_config.load_config()
        self.assertEqual(changed["sensor"]["type"], "SHT31")
        self.assertEqual(changed["discord"]["webhook_url"], "")
        self.assertFalse(changed.getboolean("discord", "report_enabled"))

    def test_invalid_change_does_not_replace_good_config(self) -> None:
        self.save_defaults()
        original = self.config_file.read_bytes()
        with self.assertRaises(ValueError):
            cellar_config.mutate(
                argparse.Namespace(
                    command="set-discord",
                    webhook="https://example.com/not-discord",
                )
            )
        self.assertEqual(self.config_file.read_bytes(), original)

    def test_restore_is_atomic_and_rejects_outside_paths(self) -> None:
        self.save_defaults()
        backup = cellar_config.backup_config()
        self.assertIsNotNone(backup)
        cellar_config.mutate(
            argparse.Namespace(
                command="set-temperature-unit",
                unit="celsius",
            )
        )
        cellar_config.restore_config(str(backup))
        self.assertEqual(
            cellar_config.load_config()["general"]["temperature_unit"],
            "fahrenheit",
        )
        outside = Path(self.temporary_directory.name) / "outside.ini"
        outside.write_text("[general]\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            cellar_config.restore_config(str(outside))


if __name__ == "__main__":
    unittest.main()

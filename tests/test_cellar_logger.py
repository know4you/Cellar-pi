from __future__ import annotations

import csv
import configparser
import json
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import cellar_logger


class LoggerFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temporary_directory.name)
        self.csv_file = self.data_dir / "cellar_readings.csv"
        self.status_file = self.data_dir / "logger-status.json"
        self.config_file = self.data_dir / "config.ini"
        self.patchers = [
            patch.object(cellar_logger, "DATA_DIR", self.data_dir),
            patch.object(cellar_logger, "CSV_FILE", self.csv_file),
            patch.object(cellar_logger, "STATUS_FILE", self.status_file),
            patch.object(cellar_logger, "CONFIG_FILE", self.config_file),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temporary_directory.cleanup()

    def test_creates_current_csv_header(self) -> None:
        cellar_logger.ensure_csv_exists()
        with self.csv_file.open(newline="", encoding="utf-8") as handle:
            header = next(csv.reader(handle))
        self.assertEqual(header, cellar_logger.CSV_COLUMNS)

    def test_sht3x_models_use_the_sht3x_reader(self) -> None:
        for sensor in ("SHT31", "SHT35"):
            with self.subTest(sensor=sensor):
                config = configparser.ConfigParser()
                config["sensor"] = {
                    "type": sensor,
                    "i2c_address": "0x44",
                }
                reader = object()
                with patch.object(
                    cellar_logger,
                    "SHT3xReader",
                    return_value=reader,
                ) as constructor:
                    actual_reader, actual_sensor = (
                        cellar_logger.create_environment_reader(config)
                    )
                self.assertIs(actual_reader, reader)
                self.assertEqual(actual_sensor, sensor)
                constructor.assert_called_once_with(0x44)

    def test_sht4x_models_use_the_sht4x_reader(self) -> None:
        for sensor in ("SHT41", "SHT45"):
            with self.subTest(sensor=sensor):
                config = configparser.ConfigParser()
                config["sensor"] = {
                    "type": sensor,
                    "i2c_address": "0x44",
                }
                reader = object()
                with patch.object(
                    cellar_logger,
                    "SHT4xReader",
                    return_value=reader,
                ) as constructor:
                    actual_reader, actual_sensor = (
                        cellar_logger.create_environment_reader(config)
                    )
                self.assertIs(actual_reader, reader)
                self.assertEqual(actual_sensor, sensor)
                constructor.assert_called_once_with(0x44)

    def test_migrates_legacy_csv_without_losing_readings(self) -> None:
        self.csv_file.write_text(
            "timestamp,temperature_f,humidity_percent\n"
            "2026-07-26T10:00:00-05:00,70.7,88.0\n",
            encoding="utf-8",
        )
        cellar_logger.ensure_csv_exists()
        with self.csv_file.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["temperature_f"], "70.7")
        self.assertEqual(rows[0]["humidity_percent"], "88.0")
        self.assertEqual(rows[0]["co2_ppm"], "")
        self.assertTrue(
            (
                self.data_dir
                / "cellar_readings.before-schema-upgrade.csv"
            ).exists()
        )

    def test_rejects_unknown_csv_schema(self) -> None:
        self.csv_file.write_text("wrong,columns\n1,2\n", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            cellar_logger.ensure_csv_exists()

    def test_health_requires_new_success_from_expected_sensor(self) -> None:
        with patch.object(cellar_logger.time, "time", return_value=100):
            cellar_logger.write_runtime_status(
                "healthy",
                "SHT31",
                0,
                "70.7 deg F",
                successful=True,
            )
        self.assertEqual(cellar_logger.health_check(100, "SHT31"), 0)
        self.assertEqual(cellar_logger.health_check(101, "SHT31"), 1)
        self.assertEqual(cellar_logger.health_check(100, "OTHER"), 1)
        status = json.loads(self.status_file.read_text(encoding="utf-8"))
        self.assertEqual(status["state"], "healthy")

    def test_status_output_is_safe_and_readable(self) -> None:
        with patch.object(cellar_logger.time, "time", return_value=100):
            cellar_logger.write_runtime_status(
                "failed",
                "SHT31",
                10,
                "Sensor not found",
            )
        output = io.StringIO()
        with redirect_stdout(output):
            result = cellar_logger.show_runtime_status()
        self.assertEqual(result, 0)
        self.assertIn("Sensor health: failed", output.getvalue())
        self.assertIn("Consecutive failures: 10", output.getvalue())

    def test_status_write_failure_is_nonfatal(self) -> None:
        with patch.object(
            cellar_logger,
            "write_runtime_status",
            side_effect=OSError("read-only disk"),
        ):
            cellar_logger.publish_runtime_status(
                "healthy",
                "SHT31",
                0,
                "valid reading",
            )

    def test_latest_reading_uses_configured_temperature_unit(self) -> None:
        self.config_file.write_text(
            "[general]\ntemperature_unit = celsius\n",
            encoding="utf-8",
        )
        cellar_logger.ensure_csv_exists()
        cellar_logger.append_reading(
            cellar_logger.Reading(
                temperature_f=68.0,
                humidity_percent=55.0,
            ),
            "SHT31",
            "none",
            "none",
        )
        output = io.StringIO()
        with redirect_stdout(output):
            result = cellar_logger.show_latest_reading()
        self.assertEqual(result, 0)
        self.assertIn("Temperature: 20.0 deg C", output.getvalue())
        self.assertIn("Humidity: 55.0%", output.getvalue())


if __name__ == "__main__":
    unittest.main()

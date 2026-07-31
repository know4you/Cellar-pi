from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cellar_core


class CoreApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.config_file = root / "config.ini"
        self.csv_file = root / "readings.csv"
        self.status_file = root / "status.json"
        self.patches = [
            patch.object(cellar_core, "CONFIG_FILE", self.config_file),
            patch.object(cellar_core, "CSV_FILE", self.csv_file),
            patch.object(cellar_core, "STATUS_FILE", self.status_file),
            patch.object(cellar_core, "service_state", return_value="active"),
        ]
        for active_patch in self.patches:
            active_patch.start()

    def tearDown(self) -> None:
        for active_patch in reversed(self.patches):
            active_patch.stop()
        self.directory.cleanup()

    def test_summary_combines_core_health_without_exposing_webhook(self) -> None:
        self.config_file.write_text(
            "[general]\n"
            "temperature_unit = fahrenheit\n"
            "[sensor]\n"
            "type = SHT31\n"
            "[discord]\n"
            "webhook_url = https://discord.com/api/webhooks/example/token\n"
            "report_enabled = true\n"
            "report_time = 19:00\n"
            "report_frequency_hours = 24\n",
            encoding="utf-8",
        )
        self.status_file.write_text(
            json.dumps(
                {
                    "state": "healthy",
                    "message": "Reading saved",
                    "last_success_at": "2026-07-30T19:00:00-05:00",
                    "consecutive_failures": 0,
                }
            ),
            encoding="utf-8",
        )
        with self.csv_file.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "timestamp",
                    "temperature_f",
                    "humidity_percent",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "timestamp": "2026-07-30T19:00:00-05:00",
                    "temperature_f": "70.0",
                    "humidity_percent": "60.0",
                }
            )
        summary = cellar_core.summary()
        self.assertEqual(summary["logger"], "active")
        self.assertEqual(summary["sensor_state"], "healthy")
        self.assertEqual(summary["discord"], "configured")
        self.assertNotIn("webhook_url", summary)

    def test_sanitized_config_hides_webhook(self) -> None:
        self.config_file.write_text(
            "[discord]\n"
            "webhook_url = https://discord.com/api/webhooks/example/token\n",
            encoding="utf-8",
        )
        sanitized = cellar_core.sanitized_config()
        self.assertIn("webhook_url = [configured]", sanitized)
        self.assertNotIn("/example/token", sanitized)

    def test_service_api_controls_only_the_logger_unit(self) -> None:
        completed = cellar_core.subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
        )
        with patch.object(
            cellar_core,
            "run_command",
            return_value=completed,
        ) as command:
            cellar_core.service_action("restart")
        command.assert_any_call(
            [
                cellar_core.SYSTEMCTL,
                "restart",
                cellar_core.LOGGER_SERVICE,
            ]
        )


if __name__ == "__main__":
    unittest.main()

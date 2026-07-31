from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import daily_report
import pandas as pd
from cellar_config import default_config


class DailyReportTests(unittest.TestCase):
    def test_disabled_schedule_does_not_generate_a_report(self) -> None:
        config = default_config()
        with patch.object(daily_report, "send_full_report") as send:
            daily_report.scheduled_run(config)
        send.assert_not_called()

    def test_report_state_is_written_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "report-state.json"
            with patch.object(daily_report, "STATE_FILE", state_file):
                daily_report.save_report_state("2026-07-26T19:00-05:00")
            self.assertEqual(
                state_file.read_text(encoding="utf-8"),
                '{"last_report_slot": "2026-07-26T19:00-05:00"}',
            )

    def test_24_hour_schedule_has_one_daily_slot(self) -> None:
        before = datetime(2026, 7, 26, 18, 59, tzinfo=timezone.utc)
        at_report = datetime(2026, 7, 26, 19, 0, tzinfo=timezone.utc)
        self.assertIsNone(
            daily_report.latest_due_slot(before, "19:00", 24)
        )
        self.assertEqual(
            daily_report.latest_due_slot(at_report, "19:00", 24),
            at_report,
        )

    def test_12_hour_schedule_has_two_daily_slots(self) -> None:
        morning = datetime(2026, 7, 26, 7, 0, tzinfo=timezone.utc)
        evening = datetime(2026, 7, 26, 19, 0, tzinfo=timezone.utc)
        self.assertEqual(
            daily_report.latest_due_slot(morning, "19:00", 12),
            morning,
        )
        self.assertEqual(
            daily_report.latest_due_slot(evening, "19:00", 12),
            evening,
        )

    def test_scheduled_report_sends_only_once_per_slot(self) -> None:
        config = default_config()
        config["discord"]["webhook_url"] = (
            "https://discord.com/api/webhooks/example/token"
        )
        config["discord"]["report_enabled"] = "true"
        config["discord"]["report_frequency_hours"] = "12"
        now = datetime(2026, 7, 26, 19, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "report-state.json"
            lock_file = Path(directory) / "report-send.lock"
            with (
                patch.object(daily_report, "STATE_FILE", state_file),
                patch.object(daily_report, "LOCK_FILE", lock_file),
                patch.object(daily_report, "datetime") as mocked_datetime,
                patch.object(daily_report, "send_full_report") as send,
            ):
                mocked_datetime.now.return_value = now
                daily_report.scheduled_run(config)
                daily_report.scheduled_run(config)
        send.assert_called_once_with(config)

    def test_report_lock_blocks_a_second_sender(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock_file = Path(directory) / "report-send.lock"
            with patch.object(daily_report, "LOCK_FILE", lock_file):
                with daily_report.report_lock() as first:
                    with daily_report.report_lock() as second:
                        self.assertTrue(first)
                        self.assertFalse(second)
                with daily_report.report_lock() as after_release:
                    self.assertTrue(after_release)

    def test_discord_report_uses_symbols_and_omits_sensor_line(self) -> None:
        config = default_config()
        config["discord"]["webhook_url"] = (
            "https://discord.com/api/webhooks/example/token"
        )
        recent = pd.DataFrame(
            {
                "temperature_f": [70.0, 71.0],
                "humidity_percent": [60.0, 61.0],
                "temperature_humidity_sensor": ["SHT31", "SHT31"],
            }
        )
        graph = Path("report.png")
        with (
            patch.object(daily_report, "read_recent_data", return_value=recent),
            patch.object(
                daily_report,
                "make_graph",
                return_value=(graph, recent["temperature_f"], "°F"),
            ),
            patch.object(daily_report, "post_message") as post,
        ):
            daily_report.send_full_report(config)
        message = post.call_args.args[1]
        self.assertIn("71.0°F", message)
        self.assertIn("Readings: 2", message)
        self.assertNotIn("Sensor:", message)


if __name__ == "__main__":
    unittest.main()

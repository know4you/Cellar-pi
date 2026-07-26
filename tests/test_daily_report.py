from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import daily_report
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
                daily_report.save_report_state("2026-07-26")
            self.assertEqual(
                state_file.read_text(encoding="utf-8"),
                '{"last_report_date": "2026-07-26"}',
            )


if __name__ == "__main__":
    unittest.main()

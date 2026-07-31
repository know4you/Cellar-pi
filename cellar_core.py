#!/usr/bin/env python3
"""Small privileged API used by Cellar-pi user interfaces.

The logger and notification processes do not import this module.  It exists
only to give local user interfaces one narrow, validated path for status,
service control, logs, configuration display, and sensor discovery.
"""

from __future__ import annotations

import argparse
import configparser
import csv
import json
import subprocess
from pathlib import Path


CONFIG_FILE = Path("/etc/cellar-pi/config.ini")
CSV_FILE = Path("/var/lib/cellar-pi/cellar_readings.csv")
STATUS_FILE = Path("/var/lib/cellar-pi/logger-status.json")
LOGGER_SERVICE = "cellar-logger.service"
REPORT_TIMER = "cellar-report.timer"
SYSTEMCTL = "/usr/bin/systemctl"
JOURNALCTL = "/usr/bin/journalctl"
I2CDETECT = "/usr/sbin/i2cdetect"


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def service_state(unit: str) -> str:
    result = run_command([SYSTEMCTL, "is-active", unit])
    return result.stdout.strip() or "unknown"


def load_config() -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    if CONFIG_FILE.exists():
        config.read(CONFIG_FILE)
    return config


def load_status() -> dict[str, object]:
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def latest_reading() -> dict[str, str]:
    if not CSV_FILE.exists():
        return {}
    latest: dict[str, str] = {}
    with CSV_FILE.open("r", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            latest = {key: value or "" for key, value in row.items()}
    return latest


def summary() -> dict[str, object]:
    config = load_config()
    status = load_status()
    webhook = config.get("discord", "webhook_url", fallback="").strip()
    return {
        "logger": service_state(LOGGER_SERVICE),
        "report_timer": service_state(REPORT_TIMER),
        "sensor": config.get("sensor", "type", fallback="unknown"),
        "sensor_state": status.get("state", "unknown"),
        "sensor_message": status.get("message", "No sensor status yet"),
        "last_success": status.get("last_success_at", ""),
        "consecutive_failures": status.get("consecutive_failures", 0),
        "discord": "configured" if webhook else "not configured",
        "reports_enabled": config.getboolean(
            "discord",
            "report_enabled",
            fallback=False,
        ),
        "report_time": config.get(
            "discord",
            "report_time",
            fallback="19:00",
        ),
        "report_frequency_hours": config.getint(
            "discord",
            "report_frequency_hours",
            fallback=24,
        ),
        "temperature_unit": config.get(
            "general",
            "temperature_unit",
            fallback="fahrenheit",
        ),
        "latest": latest_reading(),
    }


def recent_readings(limit: int) -> str:
    if not CSV_FILE.exists():
        return "No readings have been recorded yet."
    lines = CSV_FILE.read_text(encoding="utf-8").splitlines()
    if len(lines) <= 1:
        return "No readings have been recorded yet."
    selected = [lines[0], *lines[-limit:]]
    return "\n".join(selected)


def sanitized_config() -> str:
    config = load_config()
    if not config.sections():
        return "Cellar-pi configuration does not exist."
    lines: list[str] = []
    for section in config.sections():
        lines.append(f"[{section}]")
        for key, value in config.items(section):
            if key == "webhook_url":
                value = "[configured]" if value.strip() else "[not configured]"
            lines.append(f"{key} = {value}")
        lines.append("")
    return "\n".join(lines).rstrip()


def service_action(action: str) -> str:
    if action == "status":
        result = run_command(
            [SYSTEMCTL, "status", LOGGER_SERVICE, "--no-pager"]
        )
    else:
        result = run_command([SYSTEMCTL, action, LOGGER_SERVICE])
    if result.returncode != 0:
        raise RuntimeError(
            result.stdout.strip() or f"Could not {action} the logger."
        )
    if action == "stop":
        return "Logger stopped."
    if action in {"start", "restart"}:
        return f"Logger {action}ed. Current state: {service_state(LOGGER_SERVICE)}"
    return result.stdout


def logger_logs(lines: int) -> str:
    result = run_command(
        [
            JOURNALCTL,
            "-u",
            LOGGER_SERVICE,
            "-n",
            str(lines),
            "--no-pager",
        ]
    )
    return result.stdout.strip() or "No logger entries were found."


def sensor_scan() -> str:
    if not Path("/dev/i2c-1").exists():
        return (
            "I2C bus: NOT READY\n\n"
            "The Pi cannot see /dev/i2c-1. Enable I2C, reboot, and try again."
        )
    result = run_command([I2CDETECT, "-y", "1"])
    if result.returncode != 0:
        raise RuntimeError(result.stdout.strip() or "The I2C scan failed.")
    return "I2C bus: ready\n\nRaw I2C scan:\n" + result.stdout.rstrip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("summary")
    subparsers.add_parser("current")
    recent = subparsers.add_parser("recent")
    recent.add_argument("--limit", type=int, default=30)
    service = subparsers.add_parser("service")
    service.add_argument("action", choices=("start", "stop", "restart", "status"))
    logs = subparsers.add_parser("logs")
    logs.add_argument("--lines", type=int, default=100)
    subparsers.add_parser("config")
    subparsers.add_parser("sensor-scan")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "summary":
        print(json.dumps(summary()))
    elif args.command == "current":
        print(json.dumps(latest_reading()))
    elif args.command == "recent":
        print(recent_readings(max(1, min(args.limit, 500))))
    elif args.command == "service":
        print(service_action(args.action))
    elif args.command == "logs":
        print(logger_logs(max(1, min(args.lines, 1000))))
    elif args.command == "config":
        print(sanitized_config())
    elif args.command == "sensor-scan":
        print(sensor_scan())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ERROR: {error}")
        raise SystemExit(1)

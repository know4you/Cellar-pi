#!/usr/bin/env python3
"""Validated, atomic configuration management for Cellar-pi."""

from __future__ import annotations

import argparse
import configparser
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path


CONFIG_FILE = Path("/etc/cellar-pi/config.ini")
BACKUP_DIR = Path("/var/lib/cellar-pi/backups")
VALID_SENSORS = {"DHT11", "SHT31"}
VALID_UNITS = {"fahrenheit", "celsius"}
TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def default_config() -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    config["general"] = {"temperature_unit": "fahrenheit"}
    config["sensor"] = {
        "type": "DHT11",
        "gpio_pin": "4",
        "i2c_address": "0x44",
    }
    config["logging"] = {
        "interval_seconds": "60",
        "max_consecutive_failures": "10",
    }
    config["discord"] = {
        "webhook_url": "",
        "report_enabled": "false",
        "report_time": "19:00",
    }
    return config


def load_config() -> configparser.ConfigParser:
    config = default_config()
    if CONFIG_FILE.exists():
        config.read(CONFIG_FILE)
    return config


def validate(config: configparser.ConfigParser) -> None:
    unit = config.get("general", "temperature_unit").strip().lower()
    if unit not in VALID_UNITS:
        raise ValueError("temperature_unit must be fahrenheit or celsius")

    sensor = config.get("sensor", "type").strip().upper()
    if sensor not in VALID_SENSORS:
        raise ValueError(f"unsupported sensor type: {sensor}")

    gpio = config.getint("sensor", "gpio_pin")
    if not 0 <= gpio <= 27:
        raise ValueError("gpio_pin must be between 0 and 27")

    address_text = config.get("sensor", "i2c_address").strip()
    try:
        address = int(address_text, 0)
    except ValueError as error:
        raise ValueError(f"invalid I2C address: {address_text}") from error
    if not 0x03 <= address <= 0x77:
        raise ValueError("i2c_address must be between 0x03 and 0x77")

    interval = config.getint("logging", "interval_seconds")
    if interval < 5:
        raise ValueError("interval_seconds cannot be less than 5")

    failures = config.getint("logging", "max_consecutive_failures")
    if failures < 1:
        raise ValueError("max_consecutive_failures must be at least 1")

    report_time = config.get("discord", "report_time").strip()
    if not TIME_PATTERN.fullmatch(report_time):
        raise ValueError("report_time must use 24-hour HH:MM format")

    report_enabled = config.getboolean("discord", "report_enabled")
    webhook = config.get("discord", "webhook_url").strip()
    if webhook and not (
        webhook.startswith("https://discord.com/api/webhooks/")
        or webhook.startswith("https://discordapp.com/api/webhooks/")
    ):
        raise ValueError("Discord webhook URL is not valid")
    if report_enabled and not webhook:
        raise ValueError("daily reporting requires a configured Discord webhook")


def backup_config() -> Path | None:
    if not CONFIG_FILE.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / (
        "config-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".ini"
    )
    shutil.copy2(CONFIG_FILE, backup)
    return backup


def save_config(config: configparser.ConfigParser) -> Path | None:
    validate(config)
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    backup = backup_config()
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=".config-", suffix=".ini", dir=CONFIG_FILE.parent
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            config.write(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, CONFIG_FILE)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return backup


def restore_config(path: str) -> None:
    source = Path(path).resolve()
    backup_root = BACKUP_DIR.resolve()
    if backup_root not in source.parents or not source.is_file():
        raise ValueError("restore path is not a Cellar-pi config backup")
    config = configparser.ConfigParser()
    config.read(source)
    validate(config)
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, CONFIG_FILE)
    os.chmod(CONFIG_FILE, 0o600)


def print_sanitized(config: configparser.ConfigParser) -> None:
    for section in config.sections():
        print(f"[{section}]")
        for key, value in config.items(section):
            if key == "webhook_url":
                value = "[configured]" if value.strip() else "[not configured]"
            print(f"{key} = {value}")
        print()


def configure_all(args: argparse.Namespace) -> Path | None:
    config = load_config()
    config["general"]["temperature_unit"] = args.unit
    config["sensor"]["type"] = args.sensor.upper()
    config["sensor"]["gpio_pin"] = str(args.gpio)
    config["sensor"]["i2c_address"] = args.i2c
    config["discord"]["report_time"] = args.report_time
    config["discord"]["report_enabled"] = str(args.report_enabled).lower()
    if args.webhook != "__KEEP__":
        config["discord"]["webhook_url"] = args.webhook
    return save_config(config)


def mutate(args: argparse.Namespace) -> Path | None:
    config = load_config()
    if args.command == "set-sensor":
        config["sensor"]["type"] = args.sensor.upper()
        config["sensor"]["gpio_pin"] = str(args.gpio)
        config["sensor"]["i2c_address"] = args.i2c
    elif args.command == "set-discord":
        config["discord"]["webhook_url"] = args.webhook
    elif args.command == "remove-discord":
        config["discord"]["webhook_url"] = ""
        config["discord"]["report_enabled"] = "false"
    elif args.command == "set-report-time":
        config["discord"]["report_time"] = args.time
    elif args.command == "set-report-enabled":
        if args.enabled == "true" and not config["discord"]["webhook_url"].strip():
            raise ValueError("configure a Discord webhook before enabling reports")
        config["discord"]["report_enabled"] = args.enabled
    elif args.command == "set-temperature-unit":
        config["general"]["temperature_unit"] = args.unit
    return save_config(config)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("validate")
    subparsers.add_parser("show-sanitized")
    subparsers.add_parser("backup")
    get_parser = subparsers.add_parser("get")
    get_parser.add_argument("section")
    get_parser.add_argument("key")
    get_parser.add_argument("--fallback", default="")

    configure = subparsers.add_parser("configure")
    configure.add_argument("--sensor", required=True, choices=sorted(VALID_SENSORS))
    configure.add_argument("--gpio", type=int, default=4)
    configure.add_argument("--i2c", default="0x44")
    configure.add_argument("--unit", required=True, choices=sorted(VALID_UNITS))
    configure.add_argument("--report-time", required=True)
    configure.add_argument(
        "--report-enabled", action=argparse.BooleanOptionalAction, default=False
    )
    configure.add_argument("--webhook", default="__KEEP__")

    sensor = subparsers.add_parser("set-sensor")
    sensor.add_argument("sensor", choices=sorted(VALID_SENSORS))
    sensor.add_argument("--gpio", type=int, default=4)
    sensor.add_argument("--i2c", default="0x44")

    discord = subparsers.add_parser("set-discord")
    discord.add_argument("webhook")
    subparsers.add_parser("remove-discord")

    report_time = subparsers.add_parser("set-report-time")
    report_time.add_argument("time")
    report_enabled = subparsers.add_parser("set-report-enabled")
    report_enabled.add_argument("enabled", choices=("true", "false"))

    unit = subparsers.add_parser("set-temperature-unit")
    unit.add_argument("unit", choices=sorted(VALID_UNITS))

    restore = subparsers.add_parser("restore")
    restore.add_argument("path")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = load_config()

    if args.command == "validate":
        validate(config)
        print("Configuration is valid.")
    elif args.command == "show-sanitized":
        validate(config)
        print_sanitized(config)
    elif args.command == "backup":
        validate(config)
        print(backup_config() or "")
    elif args.command == "get":
        print(config.get(args.section, args.key, fallback=args.fallback))
    elif args.command == "configure":
        backup = configure_all(args)
        print(backup or "")
    elif args.command == "restore":
        restore_config(args.path)
        print("Configuration restored.")
    else:
        backup = mutate(args)
        print(backup or "")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, configparser.Error) as error:
        print(f"ERROR: {error}")
        raise SystemExit(2)


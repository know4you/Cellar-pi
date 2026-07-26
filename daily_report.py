#!/usr/bin/env python3
"""Independent Discord reporting for Cellar-pi.

This process never controls or imports the sensor logger. A notification failure
therefore cannot stop environmental logging.
"""

from __future__ import annotations

import argparse
import configparser
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path


CONFIG_FILE = Path("/etc/cellar-pi/config.ini")
CSV_FILE = Path("/var/lib/cellar-pi/cellar_readings.csv")
GRAPH_DIR = Path("/var/lib/cellar-pi/graphs")
GRAPH_FILE = GRAPH_DIR / "cellar-last-24-hours.png"
STATE_FILE = Path("/var/lib/cellar-pi/report-state.json")


def load_config() -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    if not CONFIG_FILE.exists():
        raise RuntimeError("Cellar-pi configuration does not exist")
    config.read(CONFIG_FILE)
    return config


def webhook_url(config: configparser.ConfigParser) -> str:
    url = config.get("discord", "webhook_url", fallback="").strip()
    if not url:
        raise RuntimeError("Discord webhook is not configured")
    return url


def post_message(url: str, message: str, graph: Path | None = None) -> None:
    import requests

    if graph is None:
        response = requests.post(url, json={"content": message}, timeout=30)
    else:
        with graph.open("rb") as handle:
            response = requests.post(
                url,
                data={"content": message},
                files={"file": (graph.name, handle, "image/png")},
                timeout=30,
            )
    response.raise_for_status()


def read_recent_data():
    import pandas as pd

    if not CSV_FILE.exists():
        raise RuntimeError("No sensor readings have been recorded yet")
    data = pd.read_csv(CSV_FILE)
    required = {"timestamp", "temperature_f", "humidity_percent"}
    if not required.issubset(data.columns):
        raise RuntimeError("The readings file is missing required columns")
    data["timestamp"] = pd.to_datetime(
        data["timestamp"],
        errors="coerce",
        utc=True,
    )
    local_timezone = datetime.now().astimezone().tzinfo
    data["timestamp"] = data["timestamp"].dt.tz_convert(local_timezone)
    data["temperature_f"] = pd.to_numeric(data["temperature_f"], errors="coerce")
    data["humidity_percent"] = pd.to_numeric(
        data["humidity_percent"], errors="coerce"
    )
    data = data.dropna(subset=list(required)).sort_values("timestamp")
    if data.empty:
        raise RuntimeError("No valid sensor readings are available")
    cutoff = data["timestamp"].max() - pd.Timedelta(hours=24)
    return data[data["timestamp"] >= cutoff].copy()


def temperature_values(recent, unit: str):
    if unit == "celsius":
        return (recent["temperature_f"] - 32) * 5 / 9, "deg C"
    return recent["temperature_f"], "deg F"


def make_graph(recent, unit: str):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    temperatures, suffix = temperature_values(recent, unit)
    figure, temperature_axis = plt.subplots(figsize=(14, 7))
    humidity_axis = temperature_axis.twinx()

    temperature_axis.plot(
        recent["timestamp"], temperatures, color="red", linewidth=2, label="Temperature"
    )
    humidity_axis.plot(
        recent["timestamp"],
        recent["humidity_percent"],
        color="blue",
        linewidth=2,
        label="Humidity",
    )
    temperature_axis.set_title("Cellar-pi - Last 24 Hours", fontweight="bold")
    temperature_axis.set_ylabel(f"Temperature ({suffix})", color="red")
    humidity_axis.set_ylabel("Humidity (%)", color="blue")
    temperature_axis.tick_params(axis="y", colors="red")
    humidity_axis.tick_params(axis="y", colors="blue")
    temperature_axis.xaxis.set_major_locator(mdates.HourLocator(interval=3))
    temperature_axis.xaxis.set_major_formatter(mdates.DateFormatter("%-I %p"))
    temperature_axis.grid(True, alpha=0.3)
    lines = temperature_axis.lines + humidity_axis.lines
    temperature_axis.legend(lines, [line.get_label() for line in lines], loc="best")
    figure.tight_layout()
    figure.savefig(GRAPH_FILE, dpi=150)
    plt.close(figure)
    return GRAPH_FILE, temperatures, suffix


def save_report_state(report_date: str) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=".report-state-",
        suffix=".json",
        dir=STATE_FILE.parent,
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            json.dump({"last_report_date": report_date}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, STATE_FILE)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def send_full_report(config: configparser.ConfigParser) -> None:
    recent = read_recent_data()
    unit = config.get("general", "temperature_unit", fallback="fahrenheit").lower()
    graph, temperatures, suffix = make_graph(recent, unit)
    humidity = recent["humidity_percent"]
    sensor = "unknown"
    if "temperature_humidity_sensor" in recent.columns:
        sensor = str(recent["temperature_humidity_sensor"].iloc[-1])
    elif config.has_option("sensor", "type"):
        sensor = config.get("sensor", "type")

    message = (
        "**Cellar-pi Daily Report**\n"
        f"Temperature: **{temperatures.iloc[-1]:.1f}{suffix}** "
        f"(low {temperatures.min():.1f}, high {temperatures.max():.1f}, "
        f"average {temperatures.mean():.1f})\n"
        f"Humidity: **{humidity.iloc[-1]:.1f}%** "
        f"(low {humidity.min():.1f}, high {humidity.max():.1f}, "
        f"average {humidity.mean():.1f})\n"
        f"Sensor: {sensor} | Readings: {len(recent)}"
    )
    post_message(webhook_url(config), message, graph)


def scheduled_run(config: configparser.ConfigParser) -> None:
    if not config.getboolean("discord", "report_enabled", fallback=False):
        return
    now = datetime.now().astimezone()
    report_time = config.get("discord", "report_time", fallback="19:00")
    if now.strftime("%H:%M") < report_time:
        return
    state = {}
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {}
    today = now.date().isoformat()
    if state.get("last_report_date") == today:
        return
    send_full_report(config)
    save_report_state(today)


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--test-notification", action="store_true")
    group.add_argument("--test-report", action="store_true")
    args = parser.parse_args()
    config = load_config()
    if args.test_notification:
        post_message(
            webhook_url(config),
            "[OK] Cellar-pi successfully connected to Discord.",
        )
    elif args.test_report:
        send_full_report(config)
    else:
        scheduled_run(config)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ERROR: {error}")
        raise SystemExit(1)

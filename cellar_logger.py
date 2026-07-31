#!/usr/bin/env python3

from __future__ import annotations

import argparse
import configparser
import csv
import json
import logging
import os
import shutil
import signal
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


CONFIG_FILE = Path("/etc/cellar-pi/config.ini")
DATA_DIR = Path("/var/lib/cellar-pi")
CSV_FILE = DATA_DIR / "cellar_readings.csv"
LOG_FILE = Path("/var/log/cellar-pi/cellar-pi.log")
STATUS_FILE = DATA_DIR / "logger-status.json"

CSV_COLUMNS = [
    "timestamp",
    "temperature_f",
    "humidity_percent",
    "pressure_hpa",
    "co2_ppm",
    "water_detected",
    "temperature_humidity_sensor",
    "pressure_sensor",
    "co2_sensor",
]
LEGACY_CSV_COLUMNS = [
    "timestamp",
    "temperature_f",
    "humidity_percent",
]

RUNNING = True


@dataclass
class Reading:
    temperature_f: Optional[float] = None
    humidity_percent: Optional[float] = None
    pressure_hpa: Optional[float] = None
    co2_ppm: Optional[int] = None
    water_detected: Optional[bool] = None


def stop_logger(signum: int, frame: object) -> None:
    global RUNNING
    logging.info("Shutdown signal received.")
    RUNNING = False


def interruptible_sleep(seconds: float) -> None:
    """Sleep in short steps so systemd can stop the logger promptly."""
    deadline = time.monotonic() + max(0.0, seconds)
    while RUNNING:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(1.0, remaining))


def write_runtime_status(
    state: str,
    sensor: str,
    consecutive_failures: int,
    message: str,
    *,
    successful: bool = False,
) -> None:
    """Publish a small atomic status record for /uc health checks."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    previous: dict[str, object] = {}
    if STATUS_FILE.exists():
        try:
            previous = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = {}

    now = datetime.now().astimezone()
    status: dict[str, object] = {
        "state": state,
        "sensor": sensor,
        "updated_at": now.isoformat(timespec="seconds"),
        "updated_epoch": int(time.time()),
        "consecutive_failures": consecutive_failures,
        "message": message,
        "last_success_at": previous.get("last_success_at", ""),
        "last_success_epoch": previous.get("last_success_epoch", 0),
    }
    if successful:
        status["last_success_at"] = now.isoformat(timespec="seconds")
        status["last_success_epoch"] = int(time.time())

    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=".logger-status-",
        suffix=".json",
        dir=DATA_DIR,
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            json.dump(status, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, STATUS_FILE)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def publish_runtime_status(*args, **kwargs) -> None:
    """Never let the optional status file interrupt sensor logging."""
    try:
        write_runtime_status(*args, **kwargs)
    except OSError as error:
        logging.warning("Could not update the runtime status file: %s", error)


def health_check(since_epoch: int, expected_sensor: str) -> int:
    try:
        status = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 1
    if status.get("state") != "healthy":
        return 1
    if str(status.get("sensor", "")).upper() != expected_sensor.upper():
        return 1
    if int(status.get("last_success_epoch", 0)) < since_epoch:
        return 1
    return 0


def show_runtime_status() -> int:
    try:
        status = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("Sensor health: No status yet")
        return 1
    print(f"Sensor health: {status.get('state', 'unknown')}")
    print(f"Last success: {status.get('last_success_at') or 'Never'}")
    print(
        "Consecutive failures: "
        f"{status.get('consecutive_failures', 'unknown')}"
    )
    if status.get("message"):
        print(f"Detail: {status['message']}")
    return 0


def show_latest_reading() -> int:
    if not CSV_FILE.exists():
        return 1
    with CSV_FILE.open("r", newline="", encoding="utf-8") as handle:
        row = None
        for row in csv.DictReader(handle):
            pass
    if row is None:
        return 1
    if not row.get("timestamp"):
        return 1

    config = load_config()
    unit = config.get(
        "general",
        "temperature_unit",
        fallback="fahrenheit",
    ).lower()
    temperature_text = "Unavailable"
    if row.get("temperature_f"):
        temperature = float(row["temperature_f"])
        if unit == "celsius":
            temperature = (temperature - 32) * 5 / 9
            temperature_text = f"{temperature:.1f}°C"
        else:
            temperature_text = f"{temperature:.1f}°F"

    humidity_text = "Unavailable"
    if row.get("humidity_percent"):
        humidity_text = f"{float(row['humidity_percent']):.1f}%"

    print(f"Time: {row['timestamp']}")
    print(f"Temperature: {temperature_text}")
    print(f"Humidity: {humidity_text}")
    print(
        "Sensor: "
        f"{row.get('temperature_humidity_sensor') or 'unknown'}"
    )
    return 0


def configure_logging() -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler(sys.stdout),
        ],
    )


def load_config() -> configparser.ConfigParser:
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(
            f"Configuration file not found: {CONFIG_FILE}. "
            "Run the Cellar-pi setup wizard first."
        )

    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)

    return config


class SHT3xReader:
    def __init__(self, i2c_address: int) -> None:
        import board
        import adafruit_sht31d

        self.i2c = board.I2C()
        self.sensor = adafruit_sht31d.SHT31D(
            self.i2c,
            address=i2c_address,
        )

    def read(self) -> Reading:
        temperature_c = self.sensor.temperature
        humidity = self.sensor.relative_humidity

        temperature_f = (temperature_c * 9 / 5) + 32

        return Reading(
            temperature_f=round(float(temperature_f), 2),
            humidity_percent=round(float(humidity), 2),
        )

    def close(self) -> None:
        try:
            self.i2c.deinit()
        except Exception:
            pass


class SHT4xReader:
    def __init__(self, i2c_address: int) -> None:
        import adafruit_sht4x
        import board

        self.i2c = board.I2C()
        self.sensor = adafruit_sht4x.SHT4x(
            self.i2c,
            address=i2c_address,
        )
        self.sensor.mode = adafruit_sht4x.Mode.NOHEAT_HIGHPRECISION

    def read(self) -> Reading:
        temperature_c, humidity = self.sensor.measurements
        temperature_f = (temperature_c * 9 / 5) + 32
        return Reading(
            temperature_f=round(float(temperature_f), 2),
            humidity_percent=round(float(humidity), 2),
        )

    def close(self) -> None:
        try:
            self.i2c.deinit()
        except Exception:
            pass


class NoSensorReader:
    def read(self) -> Reading:
        return Reading()

    def close(self) -> None:
        pass


def parse_i2c_address(value: str, default: int) -> int:
    value = value.strip()

    if not value:
        return default

    try:
        return int(value, 0)
    except ValueError as error:
        raise ValueError(f"Invalid I2C address: {value}") from error


def create_environment_reader(config: configparser.ConfigParser):
    sensor_type = config.get(
        "temperature_humidity_sensor",
        "type",
        fallback=config.get("sensor", "type", fallback="none"),
    ).strip().upper()

    if sensor_type in {"SHT31", "SHT35", "SHT41", "SHT45"}:
        address_text = config.get(
            "temperature_humidity_sensor",
            "i2c_address",
            fallback=config.get(
                "sensor",
                "i2c_address",
                fallback="0x44",
            ),
        )

        address = parse_i2c_address(address_text, 0x44)

        logging.info(
            "Using %s at I2C address 0x%02X.",
            sensor_type,
            address,
        )
        if sensor_type in {"SHT31", "SHT35"}:
            return SHT3xReader(address), sensor_type
        return SHT4xReader(address), sensor_type

    if sensor_type in {"NONE", "DISABLED", ""}:
        logging.warning("No temperature/humidity sensor configured.")
        return NoSensorReader(), "none"

    raise ValueError(
        f"Unsupported temperature/humidity sensor: {sensor_type}"
    )


def migrate_csv_schema() -> None:
    """Upgrade the original three-column CSV without losing readings."""
    temporary_name = ""
    with CSV_FILE.open("r", newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        header = reader.fieldnames or []
        if header == CSV_COLUMNS:
            return
        if header != LEGACY_CSV_COLUMNS:
            raise RuntimeError(
                "The readings file has an unsupported header. "
                f"Expected {LEGACY_CSV_COLUMNS} or {CSV_COLUMNS}, got {header}."
            )

        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=".cellar-readings-",
            suffix=".csv",
            dir=DATA_DIR,
        )
        try:
            with os.fdopen(
                file_descriptor,
                "w",
                newline="",
                encoding="utf-8",
            ) as destination:
                writer = csv.DictWriter(destination, fieldnames=CSV_COLUMNS)
                writer.writeheader()
                for old_row in reader:
                    writer.writerow(
                        {
                            column: old_row.get(column, "")
                            for column in CSV_COLUMNS
                        }
                    )
                destination.flush()
                os.fsync(destination.fileno())
        except Exception:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
            raise

    try:
        backup = DATA_DIR / "cellar_readings.before-schema-upgrade.csv"
        if not backup.exists():
            shutil.copy2(CSV_FILE, backup)
        os.replace(temporary_name, CSV_FILE)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)

    logging.info("Upgraded the readings file to the current CSV schema.")


def ensure_csv_exists() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if CSV_FILE.exists() and CSV_FILE.stat().st_size > 0:
        migrate_csv_schema()
        return

    with CSV_FILE.open("w", newline="", encoding="utf-8") as csv_handle:
        writer = csv.DictWriter(csv_handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()

    logging.info("Created CSV file: %s", CSV_FILE)


def append_reading(
    reading: Reading,
    environment_sensor: str,
    pressure_sensor: str,
    co2_sensor: str,
) -> None:
    row = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "temperature_f": (
            "" if reading.temperature_f is None else reading.temperature_f
        ),
        "humidity_percent": (
            "" if reading.humidity_percent is None else reading.humidity_percent
        ),
        "pressure_hpa": (
            "" if reading.pressure_hpa is None else reading.pressure_hpa
        ),
        "co2_ppm": (
            "" if reading.co2_ppm is None else reading.co2_ppm
        ),
        "water_detected": (
            ""
            if reading.water_detected is None
            else str(reading.water_detected).lower()
        ),
        "temperature_humidity_sensor": environment_sensor,
        "pressure_sensor": pressure_sensor,
        "co2_sensor": co2_sensor,
    }

    with CSV_FILE.open("a", newline="", encoding="utf-8") as csv_handle:
        writer = csv.DictWriter(csv_handle, fieldnames=CSV_COLUMNS)
        writer.writerow(row)


def merge_readings(base: Reading, extra: Reading) -> Reading:
    return Reading(
        temperature_f=(
            extra.temperature_f
            if extra.temperature_f is not None
            else base.temperature_f
        ),
        humidity_percent=(
            extra.humidity_percent
            if extra.humidity_percent is not None
            else base.humidity_percent
        ),
        pressure_hpa=(
            extra.pressure_hpa
            if extra.pressure_hpa is not None
            else base.pressure_hpa
        ),
        co2_ppm=(
            extra.co2_ppm
            if extra.co2_ppm is not None
            else base.co2_ppm
        ),
        water_detected=(
            extra.water_detected
            if extra.water_detected is not None
            else base.water_detected
        ),
    )


def describe_reading(reading: Reading) -> str:
    values = []

    if reading.temperature_f is not None:
        values.append(f"{reading.temperature_f:.2f}°F")

    if reading.humidity_percent is not None:
        values.append(f"{reading.humidity_percent:.2f}% RH")

    if reading.pressure_hpa is not None:
        values.append(f"{reading.pressure_hpa:.2f} hPa")

    if reading.co2_ppm is not None:
        values.append(f"{reading.co2_ppm} ppm CO2")

    if reading.water_detected is not None:
        values.append(
            "WATER DETECTED"
            if reading.water_detected
            else "water sensor dry"
        )

    return " | ".join(values) if values else "No sensor values"


def run_logger() -> int:
    configure_logging()
    environment_sensor = "unknown"

    signal.signal(signal.SIGTERM, stop_logger)
    signal.signal(signal.SIGINT, stop_logger)

    try:
        config = load_config()

        interval_seconds = config.getint(
            "logging",
            "interval_seconds",
            fallback=60,
        )

        if interval_seconds < 5:
            raise ValueError("Logging interval cannot be less than 5 seconds.")

        failure_retry_seconds = config.getint(
            "logging",
            "failure_retry_seconds",
            fallback=5,
        )
        if failure_retry_seconds < 2:
            raise ValueError("Failure retry interval cannot be less than 2 seconds.")

        max_failures = config.getint(
            "logging",
            "max_consecutive_failures",
            fallback=10,
        )

        environment_reader, environment_sensor = create_environment_reader(
            config
        )

        pressure_sensor = config.get(
            "pressure_sensor",
            "type",
            fallback="none",
        ).strip()

        co2_sensor = config.get(
            "co2_sensor",
            "type",
            fallback="none",
        ).strip()

        ensure_csv_exists()

        publish_runtime_status(
            "starting",
            environment_sensor,
            0,
            "Waiting for the first valid sensor reading.",
        )
        logging.info("Cellar-pi logger started.")
        logging.info("Logging every %s seconds.", interval_seconds)
        logging.info(
            "Failed sensor reads retry every %s seconds.",
            failure_retry_seconds,
        )

        consecutive_failures = 0

        try:
            while RUNNING:
                loop_started = time.monotonic()
                reading_succeeded = False

                try:
                    reading = environment_reader.read()

                    # Future pressure, CO2, and water readers merge here.
                    #
                    # reading = merge_readings(
                    #     reading,
                    #     pressure_reader.read(),
                    # )
                    #
                    # reading = merge_readings(
                    #     reading,
                    #     co2_reader.read(),
                    # )

                    append_reading(
                        reading=reading,
                        environment_sensor=environment_sensor,
                        pressure_sensor=pressure_sensor,
                        co2_sensor=co2_sensor,
                    )

                    if consecutive_failures:
                        logging.info(
                            "Sensor recovered after %s failed attempt(s).",
                            consecutive_failures,
                        )
                    consecutive_failures = 0
                    reading_succeeded = True
                    publish_runtime_status(
                        "healthy",
                        environment_sensor,
                        0,
                        describe_reading(reading),
                        successful=True,
                    )

                    logging.info(
                        "Reading saved: %s",
                        describe_reading(reading),
                    )

                except RuntimeError as error:
                    consecutive_failures += 1

                    if consecutive_failures <= 3:
                        logging.warning(
                            "Temporary sensor read failure %s/%s: %s",
                            consecutive_failures,
                            max_failures,
                            error,
                        )
                        publish_runtime_status(
                            "degraded",
                            environment_sensor,
                            consecutive_failures,
                            str(error),
                        )
                    elif consecutive_failures == max_failures:
                        logging.error(
                            "Sensor failed %s consecutive times. "
                            "Continuing to retry without writing false data.",
                            consecutive_failures,
                        )
                        publish_runtime_status(
                            "failed",
                            environment_sensor,
                            consecutive_failures,
                            str(error),
                        )
                    elif consecutive_failures % 12 == 0:
                        logging.warning(
                            "Sensor is still unavailable after %s attempts: %s",
                            consecutive_failures,
                            error,
                        )
                        publish_runtime_status(
                            "failed",
                            environment_sensor,
                            consecutive_failures,
                            str(error),
                        )

                except Exception as error:
                    consecutive_failures += 1

                    logging.exception(
                        "Sensor failure %s/%s.",
                        consecutive_failures,
                        max_failures,
                    )
                    publish_runtime_status(
                        "failed",
                        environment_sensor,
                        consecutive_failures,
                        str(error),
                    )

                elapsed = time.monotonic() - loop_started
                next_interval = (
                    interval_seconds
                    if reading_succeeded
                    else failure_retry_seconds
                )
                sleep_time = max(0.0, next_interval - elapsed)

                if sleep_time > 0:
                    interruptible_sleep(sleep_time)

        finally:
            environment_reader.close()

        publish_runtime_status(
            "stopped",
            environment_sensor,
            consecutive_failures,
            "Logger stopped.",
        )
        logging.info("Cellar-pi logger stopped cleanly.")
        return 0

    except Exception as error:
        try:
            publish_runtime_status(
                "failed",
                environment_sensor,
                0,
                str(error),
            )
        except Exception:
            pass
        logging.exception("Logger could not start.")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-health-since", type=int)
    parser.add_argument("--expected-sensor")
    parser.add_argument("--show-status", action="store_true")
    parser.add_argument("--show-latest", action="store_true")
    args = parser.parse_args()
    if args.show_status:
        return show_runtime_status()
    if args.show_latest:
        return show_latest_reading()
    if args.check_health_since is not None:
        if not args.expected_sensor:
            parser.error("--expected-sensor is required with --check-health-since")
        return health_check(args.check_health_since, args.expected_sensor)
    return run_logger()


if __name__ == "__main__":
    raise SystemExit(main())

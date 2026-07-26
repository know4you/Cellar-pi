#!/usr/bin/env python3

from __future__ import annotations

import configparser
import csv
import logging
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


CONFIG_FILE = Path("/etc/cellar-pi/config.ini")
DATA_DIR = Path("/var/lib/cellar-pi")
CSV_FILE = DATA_DIR / "cellar_readings.csv"
LOG_FILE = Path("/var/log/cellar-pi/cellar-pi.log")

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


def gpio_pin_to_board_pin(gpio_pin: int):
    import board

    pin_name = f"D{gpio_pin}"

    if not hasattr(board, pin_name):
        raise ValueError(f"GPIO{gpio_pin} is not available through Blinka.")

    return getattr(board, pin_name)


class DHT11Reader:
    def __init__(self, gpio_pin: int) -> None:
        import adafruit_dht

        board_pin = gpio_pin_to_board_pin(gpio_pin)

        self.sensor = adafruit_dht.DHT11(
            board_pin,
            use_pulseio=False,
        )

    def read(self) -> Reading:
        temperature_c = self.sensor.temperature
        humidity = self.sensor.humidity

        if temperature_c is None or humidity is None:
            raise RuntimeError("DHT11 returned an incomplete reading.")

        temperature_f = (temperature_c * 9 / 5) + 32

        return Reading(
            temperature_f=round(temperature_f, 1),
            humidity_percent=round(float(humidity), 1),
        )

    def close(self) -> None:
        try:
            self.sensor.exit()
        except Exception:
            pass


class SHT31Reader:
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

    if sensor_type == "DHT11":
        gpio_pin = config.getint(
            "temperature_humidity_sensor",
            "gpio_pin",
            fallback=config.getint("sensor", "gpio_pin", fallback=4),
        )

        logging.info("Using DHT11 on GPIO%s.", gpio_pin)
        return DHT11Reader(gpio_pin), sensor_type

    if sensor_type == "SHT31":
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

        logging.info("Using SHT31 at I2C address 0x%02X.", address)
        return SHT31Reader(address), sensor_type

    if sensor_type in {"NONE", "DISABLED", ""}:
        logging.warning("No temperature/humidity sensor configured.")
        return NoSensorReader(), "none"

    raise ValueError(
        f"Unsupported temperature/humidity sensor: {sensor_type}"
    )


def ensure_csv_exists() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if CSV_FILE.exists() and CSV_FILE.stat().st_size > 0:
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


def main() -> int:
    configure_logging()

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

                    consecutive_failures = 0
                    reading_succeeded = True

                    logging.info(
                        "Reading saved: %s",
                        describe_reading(reading),
                    )

                except RuntimeError as error:
                    consecutive_failures += 1

                    logging.warning(
                        "Temporary sensor read failure %s/%s: %s",
                        consecutive_failures,
                        max_failures,
                        error,
                    )

                except Exception:
                    consecutive_failures += 1

                    logging.exception(
                        "Sensor failure %s/%s.",
                        consecutive_failures,
                        max_failures,
                    )

                if consecutive_failures >= max_failures:
                    logging.error(
                        "Sensor failed %s consecutive times. "
                        "Continuing to retry without writing false data.",
                        consecutive_failures,
                    )

                elapsed = time.monotonic() - loop_started
                next_interval = (
                    interval_seconds
                    if reading_succeeded
                    else failure_retry_seconds
                )
                sleep_time = max(0.0, next_interval - elapsed)

                if sleep_time > 0:
                    time.sleep(sleep_time)

        finally:
            environment_reader.close()

        logging.info("Cellar-pi logger stopped cleanly.")
        return 0

    except Exception:
        logging.exception("Logger could not start.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


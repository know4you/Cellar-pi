# Cellar-pi

Turn a Raspberry Pi into an easy environmental monitor with temperature,
humidity, graphs, Discord reports, and a simple terminal interface.

> We keep track of temps, no matter what Pi gets thrown at us.

## What it does

- Logs sensor readings automatically
- Supports SHT31, SHT35, SHT41, and SHT45 sensors over I2C
- Generates temperature and humidity graphs
- Sends optional daily reports through Discord
- Keeps Discord failures isolated from the sensor logger
- Provides the `/uc` User Control interface
- Safely changes sensor and notification settings
- Validates configuration before applying it
- Rolls back failed sensor changes and software updates
- Starts automatically after a reboot or power outage

## Hardware status

Cellar-pi's installer and logger have been tested on:

- Raspberry Pi Zero WH
- Raspberry Pi OS Lite 32-bit
- 32 GB microSD card

The software supports SHT31/SHT31-D, SHT35, SHT41, and SHT45 breakout
boards. Hands-on sensor validation is currently focused on SHT31-D; the other
models use the same tested configuration and driver paths but still need
real-hardware reports.

It should work on other Raspberry Pi models running a compatible Raspberry
Pi OS release, but those combinations have not been fully tested yet.

## SHT sensor wiring

Connect the sensor while the Pi is powered off:

| SHT breakout | Raspberry Pi |
| --- | --- |
| VIN/VCC | 3.3V, physical pin 1 |
| GND | Ground, physical pin 6 |
| SDA | GPIO2/SDA, physical pin 3 |
| SCL | GPIO3/SCL, physical pin 5 |

SHT31/SHT31-D and SHT35 normally use `0x44` and can optionally use `0x45`.
SHT41 and SHT45 use `0x44`.

## Install

See [INSTALL.md](INSTALL.md) for the full fresh-install walkthrough.

```bash
git clone https://github.com/know4you/Cellar-pi.git
cd Cellar-pi
sudo bash install.sh
```

After installation:

```bash
/uc
```

## Design rule

Sensor logging is the core of Cellar-pi. Notifications, graphs, updates, and
the user interface are optional layers. A failure in an optional layer must
not stop environmental logging.

## Project status

Cellar-pi is in early development. Back up important data and test your sensor
before relying on it for equipment protection.

## Disclaimer

Cellar-pi is provided as-is, without warranty. Verify all wiring before
powering the system. The author is not responsible for damaged equipment,
lost data, property damage, injury, or other problems resulting from use of
this project.

## License

Cellar-pi is available under the [MIT License](LICENSE).

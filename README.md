# Cellar-pi

Turn a Raspberry Pi into an easy environmental monitor with temperature,
humidity, graphs, Discord reports, and a simple terminal interface.

> We keep track of temps, no matter what Pi gets thrown at us.

## What it does

- Logs sensor readings automatically
- Supports SHT31, SHT35, SHT41, and SHT45 sensors over I2C
- Generates temperature and humidity graphs
- Sends optional Discord reports every 12 or 24 hours
- Matches each graph to the selected 12-hour or 24-hour report range
- Keeps Discord failures isolated from the sensor logger
- Provides a full-screen, keyboard-first `/uc` User Control interface
- Scans the I2C bus for connected SHT sensors from Troubleshooting
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

The Raspberry Pi does not run a web UI. `/uc` is the local management layer,
and the logger continues operating if that interface is closed or unavailable.

## Project boundary

This public repository is the source-available Raspberry Pi core. It contains
the on-device sensor, logging, reporting, configuration, update, and local
management software.

Centralized multi-device monitoring, remote dashboards, accounts, fleet
management, hosted services, enterprise features, and commercial integrations
belong to **Cellar Monitoring Server (CMS)**, a separate private and proprietary
repository. CMS may integrate with this project through documented interfaces,
but CMS source code is not covered by this repository's license.

No CMS code has been moved out of this repository because no clearly separable
server, cloud, or web-dashboard implementation is currently present here.

## Project status

Cellar-pi is in early development. Back up important data and test your sensor
before relying on it for equipment protection.

## Disclaimer

Cellar-pi is provided as-is, without warranty. Verify all wiring before
powering the system. The author is not responsible for damaged equipment,
lost data, property damage, injury, or other problems resulting from use of
this project.

## License

The current version of Cellar-pi is available under the
[PolyForm Noncommercial License 1.0.0](LICENSE).

Personal, home, hobby, and other noncommercial uses permitted by that license
are free. Commercial use—including resale, paid bundling, or installing
Cellar-pi as part of a product or service—requires a separate written
commercial license. See [Commercial Licensing](COMMERCIAL-LICENSING.md).

This is a source-available license, not an OSI-approved open-source license,
because it restricts commercial use.

Versions through commit
[`4d1f4787`](https://github.com/know4you/Cellar-pi/commit/4d1f4787fd2af3ae95ca866b439aefff445b5fe0)
were released under the MIT License and remain available under those terms.
The current version and future versions are offered under the license in this
repository's `LICENSE` file.

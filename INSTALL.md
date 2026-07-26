# Fresh Install Guide

Cellar-pi has currently been tested on Raspberry Pi OS Lite 32-bit, a
Raspberry Pi Zero WH, and a 32 GB microSD card.

Start with a fresh Raspberry Pi OS Lite installation, then sign in to the Pi
through SSH.

## 1. Confirm that you are on the correct Pi

Copy and paste:

```bash
hostname
whoami
cat /etc/os-release | grep PRETTY_NAME
```

Make sure the hostname and username belong to the Pi you intended to use.

## 2. Wire the SHT sensor

Power the Pi off before connecting the sensor:

| SHT breakout | Raspberry Pi |
| --- | --- |
| VIN/VCC | 3.3V, physical pin 1 |
| GND | Ground, physical pin 6 |
| SDA | GPIO2/SDA, physical pin 3 |
| SCL | GPIO3/SCL, physical pin 5 |

Cellar-pi enables I2C during setup. It supports SHT31/SHT31-D, SHT35, SHT41,
and SHT45. SHT31/SHT31-D and SHT35 use `0x44` or `0x45`; SHT41 and SHT45
use `0x44`.

## 3. Install Git

```bash
sudo apt update
sudo apt install -y git
```

Let that finish completely before continuing.

## 4. Download Cellar-pi

```bash
cd ~
git clone https://github.com/know4you/Cellar-pi.git
cd Cellar-pi
```

Check that the files downloaded:

```bash
ls -la
```

You should see files including:

```text
README.md
INSTALL.md
cellar_logger.py
install.sh
requirements.txt
setup.sh
```

## 5. Run a quick sanity check

```bash
bash -n install.sh setup.sh cellarctl cellar-update
python3 -m py_compile cellar_logger.py cellar_config.py daily_report.py
```

No output is good. It means the files passed their basic syntax checks.

## 6. Install Cellar-pi

```bash
sudo bash install.sh
```

Some package-installation steps can look frozen on a Pi Zero. Give them
several minutes before assuming something went wrong.

The setup wizard will ask for:

- SHT sensor model and I2C address
- Fahrenheit or Celsius
- Report time and a 12-hour or 24-hour graph schedule
- Optional Discord webhook

## 7. Open User Control

After installation finishes:

```bash
/uc
```

`/uc` stands for User Control. It lets you view readings, change the sensor,
configure notifications, check system health, update Cellar-pi, and
troubleshoot the logger.

If a sensor is not showing up, choose:

```text
Advanced / Troubleshooting
-> Scan Connected Sensors
```

The scan shows whether I2C is ready, whether a supported sensor was found at
`0x44` or `0x45`, and whether that address matches the saved sensor setting.
It does not change settings or interrupt logging.

## Updating later

Open `/uc`, then choose:

```text
Advanced / Troubleshooting
-> Update Cellar-pi
```

The updater validates the downloaded files, preserves configuration and
readings, and restores the previous installation if the update fails.

## Thank you

Thank you for installing Cellar-pi.

This project started because I wanted to move my homelab into my cellar. It
was making my bedroom way too hot. What started as a simple temperature
monitor slowly turned into this.

I genuinely hope someone enjoys using it. I have tried my hardest to make it
simple enough that nearly anyone can get it running.

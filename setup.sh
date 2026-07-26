#!/usr/bin/env bash

set -Eeuo pipefail

CONFIG_DIR="/etc/cellar-pi"
CONFIG_FILE="$CONFIG_DIR/config.ini"
BACKUP_DIR="/var/lib/cellar-pi/backups"

if [[ $EUID -ne 0 ]]; then
    echo "Run this setup with sudo."
    exit 1
fi

command -v whiptail >/dev/null 2>&1 || {
    echo "whiptail is missing. Run install.sh first."
    exit 1
}

mkdir -p "$CONFIG_DIR" "$BACKUP_DIR"

whiptail \
    --title "Cellar-pi Setup" \
    --msgbox "Welcome to Cellar-pi.\n\nThis wizard will configure your sensor and Discord reporting." \
    12 65

sensor=$(whiptail \
    --title "Choose Sensor" \
    --menu "Which sensor are you using?" \
    16 65 5 \
    "DHT11" "Temperature and humidity using a GPIO pin" \
    "SHT31" "Temperature and humidity using I2C" \
    "BME280" "Temperature, humidity and pressure — future support" \
    3>&1 1>&2 2>&3) || exit 0

gpio_pin="4"
i2c_address=""

case "$sensor" in
    DHT11)
        gpio_pin=$(whiptail \
            --title "DHT11 GPIO Pin" \
            --inputbox "Enter the GPIO pin number.\n\nDefault: GPIO4" \
            12 60 "4" \
            3>&1 1>&2 2>&3) || exit 0

        if ! [[ "$gpio_pin" =~ ^[0-9]+$ ]] || (( gpio_pin < 0 || gpio_pin > 27 )); then
            whiptail \
                --title "Invalid GPIO Pin" \
                --msgbox "GPIO must be a number from 0 through 27." \
                10 55
            exit 1
        fi
        ;;

    SHT31)
        i2c_address="0x44"

        if command -v raspi-config >/dev/null 2>&1; then
            raspi-config nonint do_i2c 0
        fi
        ;;

    BME280)
        whiptail \
            --title "Not Supported Yet" \
            --msgbox "BME280 support is planned but not ready yet.\n\nNo configuration was changed." \
            12 60
        exit 0
        ;;
esac

report_time=$(whiptail \
    --title "Daily Discord Report" \
    --inputbox "Enter the daily report time using 24-hour HH:MM format.\n\nDefault: 19:00" \
    12 68 "19:00" \
    3>&1 1>&2 2>&3) || exit 0

if ! [[ "$report_time" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]]; then
    whiptail \
        --title "Invalid Time" \
        --msgbox "Use 24-hour HH:MM format.\n\nExamples:\n07:00\n19:00\n23:30" \
        13 55
    exit 1
fi

discord_webhook=$(whiptail \
    --title "Discord Webhook" \
    --passwordbox "Paste your Discord webhook URL.\n\nLeave blank to configure Discord later." \
    12 72 \
    3>&1 1>&2 2>&3) || exit 0

summary="Sensor: $sensor"

if [[ "$sensor" == "DHT11" ]]; then
    summary+="\nGPIO pin: $gpio_pin"
else
    summary+="\nI2C address: $i2c_address"
fi

summary+="\nDaily report: $report_time"

if [[ -n "$discord_webhook" ]]; then
    summary+="\nDiscord: Configured"
else
    summary+="\nDiscord: Not configured"
fi

if ! whiptail \
    --title "Confirm Configuration" \
    --yesno "$summary\n\nSave these settings?" \
    18 65
then
    exit 0
fi

if [[ -f "$CONFIG_FILE" ]]; then
    backup_name="$BACKUP_DIR/config-$(date +%Y%m%d-%H%M%S).ini"
    cp "$CONFIG_FILE" "$backup_name"
fi

temp_config=$(mktemp)

cat >"$temp_config" <<EOF
[general]
temperature_unit = fahrenheit

[sensor]
type = $sensor
gpio_pin = $gpio_pin
i2c_address = $i2c_address

[discord]
webhook_url = $discord_webhook
report_time = $report_time
EOF

install -m 600 "$temp_config" "$CONFIG_FILE"
rm -f "$temp_config"

whiptail \
    --title "Setup Complete" \
    --msgbox "Configuration saved successfully.\n\nSensor: $sensor\nDaily report: $report_time\n\nThe logger will be installed in the next step." \
    15 65

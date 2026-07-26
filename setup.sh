#!/usr/bin/env bash

set -Eeuo pipefail

WHIPTAIL="/usr/bin/whiptail"
PYTHON="/opt/cellar-pi/venv/bin/python"
CONFIG_TOOL="/opt/cellar-pi/cellar_config.py"
SETUP_BACKUP=$(/usr/bin/mktemp)
SETUP_ERROR=$(/usr/bin/mktemp)

cleanup() {
    /usr/bin/rm -f "$SETUP_BACKUP" "$SETUP_ERROR"
}

trap cleanup EXIT

if [[ $EUID -ne 0 ]]; then
    echo "Run this setup with sudo."
    exit 1
fi

if [[ ! -x "$WHIPTAIL" || ! -x "$PYTHON" || ! -f "$CONFIG_TOOL" ]]; then
    echo "Cellar-pi setup dependencies are missing. Run install.sh first."
    exit 1
fi

get_value() {
    "$PYTHON" "$CONFIG_TOOL" get "$1" "$2" --fallback "$3"
}

"$WHIPTAIL" \
    --title "Cellar-pi Setup" \
    --msgbox "This wizard configures the initial sensor, units, and Discord reporting.\n\nUse /uc later to change one setting without rerunning everything." \
    14 72

current_sensor=$(get_value sensor type DHT11)
sensor=$("$WHIPTAIL" \
    --title "Choose Sensor" \
    --default-item "$current_sensor" \
    --menu "Which sensor are you using?" \
    16 70 5 \
    "DHT11" "Temperature and humidity using GPIO" \
    "SHT31" "Temperature and humidity using I2C" \
    3>&1 1>&2 2>&3) || exit 0

gpio_pin=$(get_value sensor gpio_pin 4)
i2c_address=$(get_value sensor i2c_address 0x44)

if [[ "$sensor" == "DHT11" ]]; then
    gpio_pin=$("$WHIPTAIL" \
        --title "DHT11 GPIO Pin" \
        --inputbox "Enter the BCM GPIO number (0-27):" \
        11 62 "$gpio_pin" \
        3>&1 1>&2 2>&3) || exit 0
    if ! [[ "$gpio_pin" =~ ^[0-9]+$ ]] || ((gpio_pin < 0 || gpio_pin > 27)); then
        "$WHIPTAIL" --title "Invalid GPIO" \
            --msgbox "GPIO must be a number from 0 through 27." 10 58
        exit 1
    fi
else
    i2c_address=$("$WHIPTAIL" \
        --title "SHT31 I2C Address" \
        --inputbox "Enter the I2C address:" \
        11 62 "$i2c_address" \
        3>&1 1>&2 2>&3) || exit 0
    if ! [[ "$i2c_address" =~ ^0x[0-9A-Fa-f]{2}$ ]]; then
        "$WHIPTAIL" --title "Invalid Address" \
            --msgbox "Use a hexadecimal address such as 0x44." 10 58
        exit 1
    fi
    if [[ -x /usr/bin/raspi-config ]]; then
        /usr/bin/raspi-config nonint do_i2c 0
    fi
fi

current_unit=$(get_value general temperature_unit fahrenheit)
temperature_unit=$("$WHIPTAIL" \
    --title "Temperature Units" \
    --default-item "$current_unit" \
    --menu "Choose the display unit:" \
    15 66 5 \
    "fahrenheit" "Fahrenheit (Â°F)" \
    "celsius" "Celsius (Â°C)" \
    3>&1 1>&2 2>&3) || exit 0

current_time=$(get_value discord report_time 19:00)
report_time=$("$WHIPTAIL" \
    --title "Daily Discord Report" \
    --inputbox "Enter the report time using 24-hour HH:MM format:" \
    11 70 "$current_time" \
    3>&1 1>&2 2>&3) || exit 0

if ! [[ "$report_time" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]]; then
    "$WHIPTAIL" --title "Invalid Time" \
        --msgbox "Use 24-hour HH:MM format, such as 07:00 or 19:00." 11 64
    exit 1
fi

current_webhook=$(get_value discord webhook_url "")
webhook_argument="__KEEP__"
if [[ -n "$current_webhook" ]]; then
    webhook_action=$("$WHIPTAIL" \
        --title "Discord Webhook" \
        --menu "A Discord webhook is already configured." \
        16 70 5 \
        "keep" "Keep the existing webhook" \
        "replace" "Replace the existing webhook" \
        "remove" "Remove the webhook and disable reports" \
        3>&1 1>&2 2>&3) || exit 0
else
    webhook_action=$("$WHIPTAIL" \
        --title "Discord Webhook" \
        --menu "Discord is not configured." \
        14 70 4 \
        "replace" "Add a Discord webhook" \
        "keep" "Skip Discord for now" \
        3>&1 1>&2 2>&3) || exit 0
fi

case "$webhook_action" in
    replace)
        webhook_argument=$("$WHIPTAIL" \
            --title "Discord Webhook" \
            --passwordbox "Paste the Discord webhook URL:" \
            11 78 \
            3>&1 1>&2 2>&3) || exit 0
        ;;
    remove)
        webhook_argument=""
        ;;
esac

if [[ "$webhook_action" == "remove" ]] ||
   [[ "$webhook_action" == "keep" && -z "$current_webhook" ]]; then
    report_enabled="false"
elif "$WHIPTAIL" \
    --title "Daily Report" \
    --yesno "Enable the daily Discord report at $report_time?" \
    11 68
then
    report_enabled="true"
else
    report_enabled="false"
fi

discord_summary="Not configured"
if [[ "$webhook_argument" == "__KEEP__" && -n "$current_webhook" ]]; then
    discord_summary="Keep existing"
elif [[ -n "$webhook_argument" ]]; then
    discord_summary="Configured"
fi

summary="Sensor: $sensor"
if [[ "$sensor" == "DHT11" ]]; then
    summary+="\nGPIO pin: $gpio_pin"
else
    summary+="\nI2C address: $i2c_address"
fi
summary+="\nTemperature unit: $temperature_unit"
summary+="\nDaily report: $report_enabled at $report_time"
summary+="\nDiscord: $discord_summary"

"$WHIPTAIL" \
    --title "Confirm Configuration" \
    --yesno "$summary\n\nSave these settings?" \
    19 70 || exit 0

arguments=(
    configure
    --sensor "$sensor"
    --gpio "$gpio_pin"
    --i2c "$i2c_address"
    --unit "$temperature_unit"
    --report-time "$report_time"
    --webhook "$webhook_argument"
)
if [[ "$report_enabled" == "true" ]]; then
    arguments+=(--report-enabled)
else
    arguments+=(--no-report-enabled)
fi

if ! "$PYTHON" "$CONFIG_TOOL" "${arguments[@]}" >"$SETUP_BACKUP" \
    2>"$SETUP_ERROR"
then
    "$WHIPTAIL" --title "Setup Failed" --scrolltext \
        --textbox "$SETUP_ERROR" 18 80
    exit 1
fi

"$PYTHON" "$CONFIG_TOOL" validate >/dev/null

"$WHIPTAIL" \
    --title "Setup Complete" \
    --msgbox "Configuration saved and validated.\n\nSensor: $sensor\nTemperature unit: $temperature_unit\nDaily report: $report_enabled at $report_time" \
    15 70


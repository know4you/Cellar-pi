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
    --msgbox "Cellar-pi V1 supports SHT31, SHT35, SHT41, and SHT45 temperature and humidity sensors.\n\nThis wizard configures the sensor, units, and optional Discord reporting." \
    14 72 || exit 0

current_sensor=$(get_value sensor type SHT31)
if [[ ! "$current_sensor" =~ ^SHT(31|35|41|45)$ ]]; then
    current_sensor="SHT31"
fi
sensor=$("$WHIPTAIL" \
    --title "Choose SHT Sensor" \
    --default-item "$current_sensor" \
    --menu "Which sensor are you using?" \
    17 70 6 \
    "SHT31" "SHT31 and SHT31-D" \
    "SHT35" "Higher-accuracy SHT3x family" \
    "SHT41" "Higher-accuracy SHT4x family" \
    "SHT45" "Highest-accuracy SHT4x family" \
    3>&1 1>&2 2>&3) || exit 0

i2c_address=$(get_value sensor i2c_address 0x44)
if [[ "$sensor" == "SHT31" || "$sensor" == "SHT35" ]]; then
    if [[ "$i2c_address" != "0x44" && "$i2c_address" != "0x45" ]]; then
        i2c_address="0x44"
    fi
    i2c_address=$("$WHIPTAIL" \
        --title "$sensor I2C Address" \
        --default-item "$i2c_address" \
        --menu "Choose the sensor address:" \
        14 62 4 \
        "0x44" "Default address" \
        "0x45" "Alternate address" \
        3>&1 1>&2 2>&3) || exit 0
else
    i2c_address="0x44"
fi
if [[ -x /usr/bin/raspi-config ]]; then
    /usr/bin/raspi-config nonint do_i2c 0
fi

current_unit=$(get_value general temperature_unit fahrenheit)
temperature_unit=$("$WHIPTAIL" \
    --title "Temperature Units" \
    --default-item "$current_unit" \
    --menu "Choose the display unit:" \
    15 66 5 \
    "fahrenheit" "Fahrenheit (deg F)" \
    "celsius" "Celsius (deg C)" \
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
summary+="\nI2C address: $i2c_address"
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
    15 70 || true

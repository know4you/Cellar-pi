#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_NAME="Cellar-pi"
REPO_URL="https://github.com/know4you/Cellar-pi.git"
INSTALL_DIR="/opt/cellar-pi"
CONFIG_DIR="/etc/cellar-pi"
DATA_DIR="/var/lib/cellar-pi"
LOG_DIR="/var/log/cellar-pi"
VENV_DIR="$INSTALL_DIR/venv"
SUDOERS_FILE="/etc/sudoers.d/cellar-pi"
TEMP_DIR=""
SOURCE_DIR=""
MODE="${1:-install}"
I2C_REBOOT_REQUIRED="false"


cleanup() {
    if [[ -n "${TEMP_DIR:-}" && -d "$TEMP_DIR" ]]; then
        /usr/bin/rm -rf -- "$TEMP_DIR"
    fi
}


fail() {
    echo
    echo "ERROR: $1"
    echo
    exit 1
}


if [[ "$MODE" != "install" && "$MODE" != "--upgrade" ]]; then
    fail "Unknown installer mode: $MODE"
fi


trap cleanup EXIT
trap 'fail "Installation stopped unexpectedly near line $LINENO."' ERR

echo
echo "======================================"
echo "        Cellar-pi Installer"
echo "======================================"
echo

if [[ $EUID -ne 0 ]]; then
    fail "Run this installer with sudo."
fi

INSTALL_USER="${SUDO_USER:-}"
if [[ -z "$INSTALL_USER" || "$INSTALL_USER" == "root" ]]; then
    INSTALL_USER=$(/usr/bin/logname 2>/dev/null || true)
fi
if [[ -z "$INSTALL_USER" || "$INSTALL_USER" == "root" ]] ||
   ! /usr/bin/id "$INSTALL_USER" >/dev/null 2>&1; then
    fail "Run the installer from the normal account that will use /uc."
fi
if ! [[ "$INSTALL_USER" =~ ^[a-z_][a-z0-9_-]*$ ]]; then
    fail "The install username contains unsupported characters."
fi

if [[ ! -r /proc/device-tree/model ]] ||
   ! /usr/bin/grep -qi "raspberry pi" /proc/device-tree/model; then
    echo "WARNING: This does not appear to be a Raspberry Pi."
    read -r -p "Continue anyway? [y/N]: " answer
    [[ "$answer" =~ ^[Yy]$ ]] || exit 1
fi

echo "[1/12] Updating package information..."
/usr/bin/apt-get update

echo "[2/12] Installing operating-system packages..."
/usr/bin/apt-get install -y \
    git \
    curl \
    whiptail \
    sudo \
    python3 \
    python3-venv \
    python3-pip \
    python3-dev \
    python3-matplotlib \
    python3-pandas \
    python3-requests \
    python3-smbus \
    i2c-tools \
    raspi-config

echo "Enabling the Raspberry Pi I2C interface..."
/usr/bin/raspi-config nonint do_i2c 0
if [[ ! -e /dev/i2c-1 ]]; then
    I2C_REBOOT_REQUIRED="true"
fi

echo "[3/12] Downloading Cellar-pi..."
if [[ -n "${CELLAR_SOURCE_DIR:-}" ]]; then
    SOURCE_DIR=$(/usr/bin/readlink -f -- "$CELLAR_SOURCE_DIR")
    [[ -d "$SOURCE_DIR" ]] ||
        fail "The validated update source directory does not exist."
    echo "Using the update files already downloaded and validated."
else
    TEMP_DIR=$(/usr/bin/mktemp -d)
    SOURCE_DIR="$TEMP_DIR/repository"
    /usr/bin/git clone --depth 1 "$REPO_URL" "$SOURCE_DIR"
fi

for text_file in \
    install.sh \
    setup.sh \
    cellarctl \
    cellar-update \
    cellar_logger.py \
    cellar_config.py \
    daily_report.py \
    requirements.txt
do
    /usr/bin/sed -i 's/\r$//' "$SOURCE_DIR/$text_file"
done

required_files=(
    install.sh
    cellar_logger.py
    cellar_config.py
    daily_report.py
    cellarctl
    cellar-update
    setup.sh
    requirements.txt
)
for required_file in "${required_files[@]}"; do
    [[ -s "$SOURCE_DIR/$required_file" ]] ||
        fail "Repository file is missing: $required_file"
done
/usr/bin/bash -n \
    "$SOURCE_DIR/install.sh" \
    "$SOURCE_DIR/setup.sh" \
    "$SOURCE_DIR/cellarctl" \
    "$SOURCE_DIR/cellar-update"
/usr/bin/python3 -m py_compile \
    "$SOURCE_DIR/cellar_logger.py" \
    "$SOURCE_DIR/cellar_config.py" \
    "$SOURCE_DIR/daily_report.py"

echo "[4/12] Creating directories..."
/usr/bin/mkdir -p \
    "$INSTALL_DIR" \
    "$CONFIG_DIR" \
    "$DATA_DIR/graphs" \
    "$DATA_DIR/backups" \
    "$LOG_DIR"

/usr/bin/chmod 755 "$INSTALL_DIR" "$DATA_DIR" "$DATA_DIR/graphs" "$LOG_DIR"
/usr/bin/chmod 750 "$CONFIG_DIR"
/usr/bin/chmod 700 "$DATA_DIR/backups"

echo "[5/12] Preserving existing configuration and readings..."
if [[ -f "$CONFIG_DIR/config.ini" ]]; then
    /usr/bin/cp "$CONFIG_DIR/config.ini" \
        "$DATA_DIR/backups/config-$(/usr/bin/date +%Y%m%d-%H%M%S).ini"
fi
LEGACY_CSV="/home/$INSTALL_USER/cellar_readings.csv"
CURRENT_CSV="$DATA_DIR/cellar_readings.csv"
if [[ -s "$LEGACY_CSV" ]]; then
    current_lines=0
    if [[ -s "$CURRENT_CSV" ]]; then
        current_lines=$(/usr/bin/wc -l <"$CURRENT_CSV")
    fi
    if ((current_lines <= 1)); then
        /usr/bin/cp -p "$LEGACY_CSV" "$CURRENT_CSV"
        /usr/bin/chmod 644 "$CURRENT_CSV"
        echo "Imported the existing readings from $LEGACY_CSV."
    fi
fi

echo "[6/12] Installing project files..."
/usr/bin/install -m 755 "$SOURCE_DIR/cellar_logger.py" \
    "$INSTALL_DIR/cellar_logger.py"
/usr/bin/install -m 755 "$SOURCE_DIR/cellar_config.py" \
    "$INSTALL_DIR/cellar_config.py"
/usr/bin/install -m 755 "$SOURCE_DIR/daily_report.py" \
    "$INSTALL_DIR/daily_report.py"
/usr/bin/install -m 755 "$SOURCE_DIR/setup.sh" \
    "$INSTALL_DIR/setup.sh"
/usr/bin/install -m 755 "$SOURCE_DIR/cellarctl" \
    /usr/local/bin/cellarctl
if [[ "${CELLAR_DEFER_UPDATER_INSTALL:-0}" != "1" ]]; then
    /usr/bin/install -m 755 "$SOURCE_DIR/cellar-update" \
        /usr/local/bin/cellar-update
fi
/usr/bin/install -m 644 "$SOURCE_DIR/requirements.txt" \
    "$INSTALL_DIR/requirements.txt"
/usr/bin/ln -sfn /usr/local/bin/cellarctl /uc

echo "[7/12] Creating Python environment..."
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    /usr/bin/python3 -m venv --system-site-packages "$VENV_DIR"
fi
"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
"$VENV_DIR/bin/python" -m pip install \
    --requirement "$INSTALL_DIR/requirements.txt"

echo "[8/12] Creating system services..."
/usr/bin/tee /etc/systemd/system/cellar-logger.service >/dev/null <<EOF
[Unit]
Description=Cellar-pi environmental sensor logger
After=local-fs.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV_DIR/bin/python $INSTALL_DIR/cellar_logger.py
Restart=on-failure
RestartSec=10
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
EOF

/usr/bin/tee /etc/systemd/system/cellar-report.service >/dev/null <<EOF
[Unit]
Description=Cellar-pi independent Discord report
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV_DIR/bin/python $INSTALL_DIR/daily_report.py
EOF

/usr/bin/tee /etc/systemd/system/cellar-report.timer >/dev/null <<'EOF'
[Unit]
Description=Check the Cellar-pi daily report schedule

[Timer]
OnCalendar=*-*-* *:*:00
Persistent=true
AccuracySec=1s
Unit=cellar-report.service

[Install]
WantedBy=timers.target
EOF

echo "[9/12] Installing narrow /uc sudo permissions..."
/usr/bin/tee "$SUDOERS_FILE" >/dev/null <<EOF
# Cellar-pi User Control: generated by install.sh
$INSTALL_USER ALL=(root) NOPASSWD: $VENV_DIR/bin/python $INSTALL_DIR/cellar_config.py get *
$INSTALL_USER ALL=(root) NOPASSWD: $VENV_DIR/bin/python $INSTALL_DIR/cellar_config.py set-sensor *
$INSTALL_USER ALL=(root) NOPASSWD: $VENV_DIR/bin/python $INSTALL_DIR/cellar_config.py set-discord *
$INSTALL_USER ALL=(root) NOPASSWD: $VENV_DIR/bin/python $INSTALL_DIR/cellar_config.py remove-discord
$INSTALL_USER ALL=(root) NOPASSWD: $VENV_DIR/bin/python $INSTALL_DIR/cellar_config.py set-report-time *
$INSTALL_USER ALL=(root) NOPASSWD: $VENV_DIR/bin/python $INSTALL_DIR/cellar_config.py set-report-enabled *
$INSTALL_USER ALL=(root) NOPASSWD: $VENV_DIR/bin/python $INSTALL_DIR/cellar_config.py set-temperature-unit *
$INSTALL_USER ALL=(root) NOPASSWD: $VENV_DIR/bin/python $INSTALL_DIR/cellar_config.py show-sanitized
$INSTALL_USER ALL=(root) NOPASSWD: $VENV_DIR/bin/python $INSTALL_DIR/cellar_config.py backup
$INSTALL_USER ALL=(root) NOPASSWD: $VENV_DIR/bin/python $INSTALL_DIR/cellar_config.py restore *
$INSTALL_USER ALL=(root) NOPASSWD: $VENV_DIR/bin/python $INSTALL_DIR/cellar_logger.py --check-health-since *
$INSTALL_USER ALL=(root) NOPASSWD: $VENV_DIR/bin/python $INSTALL_DIR/cellar_logger.py --show-status
$INSTALL_USER ALL=(root) NOPASSWD: $VENV_DIR/bin/python $INSTALL_DIR/cellar_logger.py --show-latest
$INSTALL_USER ALL=(root) NOPASSWD: $VENV_DIR/bin/python $INSTALL_DIR/daily_report.py --test-notification
$INSTALL_USER ALL=(root) NOPASSWD: $VENV_DIR/bin/python $INSTALL_DIR/daily_report.py --test-report
$INSTALL_USER ALL=(root) NOPASSWD: $VENV_DIR/bin/python -m pip install --requirement $INSTALL_DIR/requirements.txt
$INSTALL_USER ALL=(root) NOPASSWD: $INSTALL_DIR/setup.sh
$INSTALL_USER ALL=(root) NOPASSWD: /usr/local/bin/cellar-update
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/systemctl start cellar-logger.service
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/systemctl stop cellar-logger.service
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart cellar-logger.service
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/systemctl status cellar-logger.service --no-pager
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/systemctl is-active cellar-logger.service
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/systemctl is-active --quiet cellar-logger.service
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/systemctl is-active cellar-report.timer
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/journalctl -u cellar-logger.service *
EOF
/usr/bin/chmod 440 "$SUDOERS_FILE"
/usr/sbin/visudo -cf "$SUDOERS_FILE" >/dev/null ||
    fail "The Cellar-pi sudoers file did not validate."

echo "[10/12] Running initial setup..."
if [[ "$MODE" == "--upgrade" && -s "$CONFIG_DIR/config.ini" ]]; then
    echo "Migrating the existing configuration to the SHT-family V1 schema."
    "$VENV_DIR/bin/python" "$INSTALL_DIR/cellar_config.py" migrate >/dev/null
else
    "$INSTALL_DIR/setup.sh"
fi
"$VENV_DIR/bin/python" "$INSTALL_DIR/cellar_config.py" validate >/dev/null

echo "[11/12] Enabling services..."
/usr/bin/systemctl daemon-reload
/usr/bin/systemctl enable cellar-logger.service cellar-report.timer
/usr/bin/systemctl restart cellar-logger.service
/usr/bin/systemctl restart cellar-report.timer

echo "[12/12] Verifying installation..."
/usr/bin/test -x /uc
/usr/bin/test -s "$CONFIG_DIR/config.ini"
/usr/bin/systemctl is-active --quiet cellar-report.timer
if /usr/bin/systemctl is-active --quiet cellar-logger.service; then
    LOGGER_RESULT="running"
else
    LOGGER_RESULT="not running - use /uc > Advanced / Troubleshooting > View Logger Logs"
fi

echo
echo "======================================"
echo "      Cellar-pi installation done"
echo "======================================"
echo
echo "User Control: /uc"
echo "Logger: $LOGGER_RESULT"
echo "Report timer: running"
echo "Sudo rules: validated for $INSTALL_USER"
if [[ "$I2C_REBOOT_REQUIRED" == "true" ]]; then
    echo "I2C: enabled; reboot the Pi before testing the SHT sensor"
else
    echo "I2C: enabled"
fi
echo

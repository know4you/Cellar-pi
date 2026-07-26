#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_NAME="Cellar-pi"
REPO_URL="https://github.com/know4you/Cellar-pi.git"

INSTALL_DIR="/opt/cellar-pi"
CONFIG_DIR="/etc/cellar-pi"
DATA_DIR="/var/lib/cellar-pi"
LOG_DIR="/var/log/cellar-pi"
VENV_DIR="$INSTALL_DIR/venv"

TEMP_DIR=""

cleanup() {
    if [[ -n "${TEMP_DIR:-}" && -d "$TEMP_DIR" ]]; then
        rm -rf "$TEMP_DIR"
    fi
}

fail() {
    echo
    echo "ERROR: $1"
    echo
    exit 1
}

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

if [[ ! -r /proc/device-tree/model ]] ||
   ! grep -qi "raspberry pi" /proc/device-tree/model; then
    echo "WARNING: This does not appear to be a Raspberry Pi."
    read -r -p "Continue anyway? [y/N]: " answer

    if [[ ! "$answer" =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo "[1/10] Updating package information..."
apt-get update

echo "[2/10] Installing operating-system packages..."
apt-get install -y \
    git \
    curl \
    whiptail \
    python3 \
    python3-venv \
    python3-pip \
    python3-dev \
    python3-matplotlib \
    python3-pandas \
    python3-requests \
    python3-smbus \
    i2c-tools \
    libgpiod2

echo "[3/10] Downloading Cellar-pi..."
TEMP_DIR=$(mktemp -d)
git clone --depth 1 "$REPO_URL" "$TEMP_DIR/repository"

echo "[4/10] Creating directories..."
mkdir -p \
    "$INSTALL_DIR" \
    "$CONFIG_DIR" \
    "$DATA_DIR/graphs" \
    "$DATA_DIR/backups" \
    "$LOG_DIR"

chmod 755 "$INSTALL_DIR"
chmod 750 "$CONFIG_DIR"
chmod 755 "$DATA_DIR"
chmod 755 "$DATA_DIR/graphs"
chmod 700 "$DATA_DIR/backups"
chmod 755 "$LOG_DIR"

echo "[5/10] Preserving existing configuration and readings..."

if [[ -f "$CONFIG_DIR/config.ini" ]]; then
    cp "$CONFIG_DIR/config.ini" \
        "$DATA_DIR/backups/config-$(date +%Y%m%d-%H%M%S).ini"
fi

echo "[6/10] Installing project files..."

install -m 755 \
    "$TEMP_DIR/repository/cellar_logger.py" \
    "$INSTALL_DIR/cellar_logger.py"

install -m 755 \
    "$TEMP_DIR/repository/setup.sh" \
    "$INSTALL_DIR/setup.sh"

install -m 644 \
    "$TEMP_DIR/repository/requirements.txt" \
    "$INSTALL_DIR/requirements.txt"

echo "[7/10] Creating Python environment..."

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    python3 -m venv --system-site-packages "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel

"$VENV_DIR/bin/python" -m pip install \
    --requirement "$INSTALL_DIR/requirements.txt"

echo "[8/10] Creating logger service..."

cat > /etc/systemd/system/cellar-logger.service <<EOF
[Unit]
Description=Cellar-pi environmental sensor logger
After=network.target
Wants=network.target

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

echo "[9/10] Creating /uc control panel..."

cat > /usr/local/bin/cellarctl <<'EOF'
#!/usr/bin/env bash

CONFIG="/etc/cellar-pi/config.ini"
CSV="/var/lib/cellar-pi/cellar_readings.csv"
PYTHON="/opt/cellar-pi/venv/bin/python"
SETUP="/opt/cellar-pi/setup.sh"
LOGGER="cellar-logger.service"

show_text() {
    local title="$1"
    shift

    local temp_file
    temp_file=$(mktemp)

    "$@" >"$temp_file" 2>&1 || true

    whiptail \
        --title "$title" \
        --scrolltext \
        --textbox "$temp_file" \
        24 90

    rm -f "$temp_file"
}

while true; do
    choice=$(whiptail \
        --title "Cellar-pi Control" \
        --menu "Choose an option:" \
        23 72 13 \
        "1" "Current sensor reading" \
        "2" "Logger status" \
        "3" "View recent readings" \
        "4" "View logger errors" \
        "5" "Test configured sensor" \
        "6" "Change sensor or settings" \
        "7" "Restart logger" \
        "8" "Stop logger" \
        "9" "Start logger" \
        "10" "View configuration" \
        "11" "Repair Python packages" \
        "12" "Exit" \
        3>&1 1>&2 2>&3
    ) || exit 0

    case "$choice" in
        1)
            if [[ -f "$CSV" ]]; then
                latest=$(tail -n 1 "$CSV")

                whiptail \
                    --title "Current Sensor Reading" \
                    --msgbox "$latest" \
                    12 78
            else
                whiptail \
                    --title "Current Sensor Reading" \
                    --msgbox "No readings have been recorded yet." \
                    10 60
            fi
            ;;

        2)
            show_text \
                "Logger Status" \
                systemctl status "$LOGGER" --no-pager
            ;;

        3)
            if [[ -f "$CSV" ]]; then
                show_text \
                    "Recent Readings" \
                    tail -n 30 "$CSV"
            else
                whiptail \
                    --title "Recent Readings" \
                    --msgbox "No CSV file exists yet." \
                    10 55
            fi
            ;;

        4)
            show_text \
                "Logger Errors" \
                journalctl -u "$LOGGER" -n 100 --no-pager
            ;;

        5)
            whiptail \
                --title "Sensor Test" \
                --infobox "Please wait...\n\nRestarting the logger and checking for a reading." \
                10 65

            sudo systemctl restart "$LOGGER"
            sleep 8

            if systemctl is-active --quiet "$LOGGER"; then
                whiptail \
                    --title "Sensor Test" \
                    --msgbox "Logger is running.\n\nCheck Current sensor reading in a minute." \
                    12 65
            else
                show_text \
                    "Sensor Test Failed" \
                    journalctl -u "$LOGGER" -n 40 --no-pager
            fi
            ;;

        6)
            sudo systemctl stop "$LOGGER" || true
            sudo "$SETUP"
            sudo systemctl daemon-reload
            sudo systemctl restart "$LOGGER" || true

            if systemctl is-active --quiet "$LOGGER"; then
                whiptail \
                    --title "Configuration Updated" \
                    --msgbox "Settings saved and logger restarted." \
                    10 60
            else
                show_text \
                    "Logger Failed After Setup" \
                    journalctl -u "$LOGGER" -n 50 --no-pager
            fi
            ;;

        7)
            if whiptail \
                --title "Restart Logger" \
                --yesno "Restart the logger now?" \
                10 55
            then
                sudo systemctl restart "$LOGGER"

                whiptail \
                    --title "Restart Logger" \
                    --msgbox "Logger restarted." \
                    9 50
            fi
            ;;

        8)
            if whiptail \
                --title "Stop Logger" \
                --yesno "Stop environmental logging?" \
                10 55
            then
                sudo systemctl stop "$LOGGER"

                whiptail \
                    --title "Stop Logger" \
                    --msgbox "Logger stopped." \
                    9 50
            fi
            ;;

        9)
            sudo systemctl start "$LOGGER"

            whiptail \
                --title "Start Logger" \
                --msgbox "Logger started." \
                9 50
            ;;

        10)
            if [[ -f "$CONFIG" ]]; then
                show_text \
                    "Cellar-pi Configuration" \
                    sed \
                    -E \
                    's#(webhook_url[[:space:]]*=[[:space:]]*).+#\1[hidden]#' \
                    "$CONFIG"
            else
                whiptail \
                    --title "Configuration" \
                    --msgbox "No configuration exists yet." \
                    10 55
            fi
            ;;

        11)
            if whiptail \
                --title "Repair Python Packages" \
                --yesno "Reinstall required Python packages?" \
                10 60
            then
                (
                    echo 10
                    echo "XXX"
                    echo "Please wait..."
                    echo "Updating Python tools."
                    echo "XXX"

                    "$PYTHON" -m pip install \
                        --upgrade pip setuptools wheel \
                        >/tmp/cellar-pip-repair.log 2>&1

                    echo 50
                    echo "XXX"
                    echo "Please wait..."
                    echo "Installing sensor libraries."
                    echo "XXX"

                    "$PYTHON" -m pip install \
                        --requirement /opt/cellar-pi/requirements.txt \
                        >>/tmp/cellar-pip-repair.log 2>&1

                    echo 100
                ) | whiptail \
                    --title "Cellar-pi Repair" \
                    --gauge "Please wait..." \
                    11 70 0

                whiptail \
                    --title "Repair Complete" \
                    --msgbox "Python packages were reinstalled." \
                    10 60
            fi
            ;;

        12)
            exit 0
            ;;
    esac
done
EOF

chmod 755 /usr/local/bin/cellarctl

ln -sfn /usr/local/bin/cellarctl /uc

echo "[10/10] Running initial setup..."

"$INSTALL_DIR/setup.sh"

systemctl daemon-reload
systemctl enable cellar-logger.service
systemctl restart cellar-logger.service

echo
echo "======================================"
echo "      Cellar-pi installation done"
echo "======================================"
echo
echo "Open the control panel with:"
echo
echo "    /uc"
echo
echo "Logger status:"
echo
systemctl --no-pager --full status cellar-logger.service || true
echo

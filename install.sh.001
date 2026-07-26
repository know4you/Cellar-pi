#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_NAME="Cellar-pi"
INSTALL_DIR="/opt/cellar-pi"
CONFIG_DIR="/etc/cellar-pi"
DATA_DIR="/var/lib/cellar-pi"
LOG_DIR="/var/log/cellar-pi"

echo
echo "======================================"
echo "        Cellar-pi Installer"
echo "======================================"
echo

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: Run this installer with sudo."
    exit 1
fi

if ! grep -qi "raspberry pi" /proc/device-tree/model 2>/dev/null; then
    echo "WARNING: This does not appear to be a Raspberry Pi."
    read -r -p "Continue anyway? [y/N]: " answer

    if [[ ! "$answer" =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo "Updating package information..."
apt-get update

echo "Installing required packages..."
apt-get install -y \
    python3 \
    python3-venv \
    python3-pip \
    python3-matplotlib \
    python3-pandas \
    python3-requests \
    python3-smbus \
    i2c-tools \
    whiptail \
    curl \
    git

echo "Creating Cellar-pi directories..."
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

echo
echo "Base installation completed."
echo
echo "The full setup wizard is still being built."
echo "Nothing from an existing installation was deleted."
echo

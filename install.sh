#!/usr/bin/env bash
#
# Installer for the Inky pHAT weather dashboard on Raspberry Pi OS Trixie.
#
# It:
#   - installs system dependencies via apt (prebuilt, avoids compiling numpy)
#   - enables SPI and I2C
#   - creates a virtual environment with --system-site-packages
#   - installs the Python requirements into that venv
#   - installs and enables the systemd timer
#
# Run from inside the cloned repo directory:
#   chmod +x install.sh
#   ./install.sh
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$HOME/.virtualenvs/inky"
RUN_USER="$(whoami)"

echo "==> Repo:  $REPO_DIR"
echo "==> Venv:  $VENV_DIR"
echo "==> User:  $RUN_USER"

echo "==> Updating apt and installing system packages..."
sudo apt update
# Prebuilt system packages so pip does NOT have to compile numpy/Pillow.
sudo apt install -y \
    git \
    python3-full \
    python3-venv \
    python3-pip \
    python3-numpy \
    python3-pil \
    python3-spidev \
    python3-rpi.gpio \
    python3-requests \
    libopenblas0-pthread \
    libgfortran5

echo "==> Enabling SPI and I2C interfaces..."
sudo raspi-config nonint do_spi 0
sudo raspi-config nonint do_i2c 0

# Free up the SPI chip-select pin (needed by some Inky boards).
CONFIG_TXT="/boot/firmware/config.txt"
if [ -f "$CONFIG_TXT" ]; then
    if ! grep -q "^dtoverlay=spi0-0cs" "$CONFIG_TXT"; then
        echo "==> Adding dtoverlay=spi0-0cs to $CONFIG_TXT"
        echo "dtoverlay=spi0-0cs" | sudo tee -a "$CONFIG_TXT" >/dev/null
    fi
fi

echo "==> Creating virtual environment (with system site packages)..."
python3 -m venv --system-site-packages "$VENV_DIR"

echo "==> Installing Python requirements..."
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$REPO_DIR/requirements.txt"

echo "==> Installing systemd service and timer..."
# Generate unit files with the correct paths/user substituted in.
sed \
    -e "s|__RUN_USER__|$RUN_USER|g" \
    -e "s|__VENV_DIR__|$VENV_DIR|g" \
    -e "s|__REPO_DIR__|$REPO_DIR|g" \
    "$REPO_DIR/systemd/inky-dashboard.service.in" \
    | sudo tee /etc/systemd/system/inky-dashboard.service >/dev/null

sudo cp "$REPO_DIR/systemd/inky-dashboard.timer" /etc/systemd/system/inky-dashboard.timer

sudo systemctl daemon-reload
sudo systemctl enable --now inky-dashboard.timer

echo ""
echo "==> Done!"
echo "The dashboard will update every hour at :15, except 23:00-05:00."
echo ""
echo "Test a one-off update now with:"
echo "    sudo systemctl start inky-dashboard.service"
echo ""
echo "Check the timer schedule with:"
echo "    systemctl list-timers inky-dashboard.timer"
echo ""
echo "NOTE: If this was the first time enabling SPI/I2C, reboot once:"
echo "    sudo reboot"

#!/bin/bash
# =============================================================================
# Pi 5 AIoT Smart Conducting System — One-shot Installer
# =============================================================================
# Run on a fresh Raspberry Pi OS (64-bit, Bookworm):
#   chmod +x install.sh
#   ./install.sh
#
# What this does:
#   1. System updates + required apt packages
#   2. Python venv + pip dependencies
#   3. Mosquitto MQTT broker setup
#   4. Enable Camera, I2C, SPI via raspi-config
#   5. Copy systemd units + enable services
#   6. Download MediaPipe hand_landmarker.task model
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$SCRIPT_DIR/venv"
MODEL_DIR="$PROJECT_DIR/models"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERR]${NC} $*"; }

# =============================================================================
# Step 1: System packages
# =============================================================================
echo ""
echo "============================================"
echo " Step 1: System packages"
echo "============================================"

sudo apt update -y
sudo apt upgrade -y

sudo apt install -y \
    python3-pip \
    python3-venv \
    python3-dev \
    python3-numpy \
    mosquitto \
    mosquitto-clients \
    i2c-tools \
    git \
    cmake \
    libcap-dev \
    libatlas-base-dev \
    libopenblas-dev \
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    libavcodec-dev \
    libavformat-dev \
    libswscale-dev \
    libv4l-dev \
    libxvidcore-dev \
    libx264-dev \
    libgtk-3-dev \
    libcanberra-gtk3-module \
    ffmpeg

log "System packages installed"

# =============================================================================
# Step 2: Python virtual environment
# =============================================================================
echo ""
echo "============================================"
echo " Step 2: Python venv + dependencies"
echo "============================================"

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    log "Virtual environment created at $VENV_DIR"
else
    log "Virtual environment already exists"
fi

source "$VENV_DIR/bin/activate"
pip install --upgrade pip setuptools wheel

# Install numpy first (required by opencv-python)
pip install numpy>=1.24

# Install main dependencies
pip install paho-mqtt>=2.0 bleak>=0.22
pip install flask>=3.0 flask-cors>=4.0 flask-socketio>=5.3
pip install joblib>=1.3

# OpenCV — use pre-built wheel for speed (or fall back to pip)
if ! pip install opencv-python>=4.8 2>/dev/null; then
    warn "opencv-python wheel not available, trying opencv-python-headless..."
    pip install opencv-python-headless>=4.8
fi

# MediaPipe — only install if not already present (large download)
if ! pip show mediapipe >/dev/null 2>&1; then
    log "Installing mediapipe (this may take a few minutes)..."
    pip install mediapipe>=0.10
else
    log "mediapipe already installed"
fi

# Pi Camera
pip install picamera2 2>/dev/null || warn "picamera2 not available (pre-installed on Pi OS Bookworm)"

# LED Matrix
pip install rpi_ws281x>=5.0 2>/dev/null || warn "rpi_ws281x requires GPIO access (run LED driver with sudo)"

log "Python dependencies installed"

# =============================================================================
# Step 3: Mosquitto MQTT Broker
# =============================================================================
echo ""
echo "============================================"
echo " Step 3: Mosquitto MQTT Broker"
echo "============================================"

# Allow anonymous connections (local network only by default)
sudo bash -c 'cat > /etc/mosquitto/conf.d/aiot.conf << EOF
# AIoT Smart Conducting — MQTT Configuration
listener 1883 0.0.0.0
allow_anonymous true

# Optional: restrict to local network (uncomment and change)
# listener 1883 192.168.1.0/24
EOF'

sudo systemctl enable mosquitto
sudo systemctl restart mosquitto

# Verify
if systemctl is-active --quiet mosquitto; then
    log "Mosquitto is running"
else
    err "Mosquitto failed to start — check: sudo journalctl -u mosquitto"
fi

# =============================================================================
# Step 4: raspi-config (Camera, I2C, SPI)
# =============================================================================
echo ""
echo "============================================"
echo " Step 4: Enable Camera + I2C + SPI"
echo "============================================"

# Non-interactive enable
if command -v raspi-config &>/dev/null; then
    sudo raspi-config nonint do_camera 0   2>/dev/null || warn "Camera enable: already enabled or legacy camera"
    sudo raspi-config nonint do_i2c 0       2>/dev/null || warn "I2C already enabled"
    sudo raspi-config nonint do_spi 0       2>/dev/null || warn "SPI already enabled"
    log "Camera, I2C, SPI enabled (reboot may be required)"
else
    warn "raspi-config not found — manually enable in: sudo raspi-config"
fi

# Add user to i2c and gpio groups
sudo usermod -aG i2c,gpio,video "$USER" 2>/dev/null || true

# =============================================================================
# Step 5: MediaPipe Model
# =============================================================================
echo ""
echo "============================================"
echo " Step 5: MediaPipe Hand Landmarker Model"
echo "============================================"

MODEL_URL="https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"

if [ ! -f "$MODEL_DIR/hand_landmarker.task" ]; then
    mkdir -p "$MODEL_DIR"
    log "Downloading hand_landmarker.task..."
    wget -q --show-progress -O "$MODEL_DIR/hand_landmarker.task" "$MODEL_URL" || {
        warn "Download failed — copy manually from PC: models/hand_landmarker.task"
    }
else
    log "hand_landmarker.task already present"
fi

# Also copy trained model if available
if [ -f "$PROJECT_DIR/model/models/gesture_classifier.pkl" ]; then
    cp "$PROJECT_DIR/model/models/gesture_classifier.pkl" "$MODEL_DIR/" 2>/dev/null || true
    cp "$PROJECT_DIR/model/models/gesture_classifier.meta.pkl" "$MODEL_DIR/" 2>/dev/null || true
    log "Gesture model copied to $MODEL_DIR"
fi

# =============================================================================
# Step 6: Systemd Services
# =============================================================================
echo ""
echo "============================================"
echo " Step 6: Install systemd services"
echo "============================================"

SYSTEMD_DIR="/etc/systemd/system"

# Copy and enable each service
for svc in pi-ble-receiver pi-landmarks pi-led-driver pi-flask; do
    SRC="$SCRIPT_DIR/systemd/${svc}.service"
    if [ -f "$SRC" ]; then
        sudo cp "$SRC" "$SYSTEMD_DIR/"
        log "Installed ${svc}.service"
    else
        warn "${svc}.service not found — skipping"
    fi
done

sudo systemctl daemon-reload

# Enable services (but don't start yet — user should verify first)
echo ""
echo "Available services:"
for svc in pi-ble-receiver pi-landmarks pi-led-driver pi-flask; do
    if [ -f "$SYSTEMD_DIR/${svc}.service" ]; then
        echo "  sudo systemctl enable --now ${svc}"
    fi
done

# =============================================================================
# Done
# =============================================================================
echo ""
echo "============================================"
echo " Installation complete!"
echo "============================================"
echo ""
echo " Next steps:"
echo "  1. Reboot:  sudo reboot"
echo "  2. Verify:  mosquitto_sub -t '#' -v  (check MQTT)"
echo "  3. Start services:"
echo "       sudo systemctl enable --now pi-ble-receiver"
echo "       sudo systemctl enable --now pi-landmarks"
echo "       sudo systemctl enable --now pi-led-driver"
echo "       sudo systemctl enable --now pi-flask"
echo "  4. Dashboard: http://$(hostname -I | awk '{print $1}'):5000"
echo "  5. Check logs: sudo journalctl -u pi-flask -f"
echo ""

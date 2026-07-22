#!/bin/bash
# Pi 5 Remote Deploy — run via: bash deploy_remote.sh
set -e

echo "=== Installing systemd services ==="
sudo cp /home/ag1_client/aiot_project/pi5/systemd/pi-flask.service /etc/systemd/system/
sudo cp /home/ag1_client/aiot_project/pi5/systemd/pi-ble-receiver.service /etc/systemd/system/
sudo cp /home/ag1_client/aiot_project/pi5/systemd/pi-led-driver.service /etc/systemd/system/

echo "=== Fixing paths ==="
sudo sed -i 's|/home/pi/aiot|/home/ag1_client/aiot_project|g' /etc/systemd/system/pi-flask.service
sudo sed -i 's|/home/pi/aiot|/home/ag1_client/aiot_project|g' /etc/systemd/system/pi-ble-receiver.service
sudo sed -i 's|/home/pi/aiot|/home/ag1_client/aiot_project|g' /etc/systemd/system/pi-led-driver.service
sudo sed -i 's|User=pi|User=ag1_client|g' /etc/systemd/system/pi-flask.service
sudo sed -i 's|/venv/bin/python|/aiot_project/venv/bin/python|g' /etc/systemd/system/pi-flask.service
sudo sed -i 's|/venv/bin/python|/aiot_project/venv/bin/python|g' /etc/systemd/system/pi-ble-receiver.service
sudo sed -i 's|/venv/bin/python|/aiot_project/venv/bin/python|g' /etc/systemd/system/pi-led-driver.service

echo "=== Reloading systemd ==="
sudo systemctl daemon-reload

echo "=== Starting Flask ==="
sudo systemctl enable pi-flask
sudo systemctl start pi-flask
sleep 2
systemctl is-active pi-flask && echo "Flask: ACTIVE" || echo "Flask: FAILED"

echo "=== Done ==="
echo "Dashboard: http://$(hostname -I | awk '{print $1}'):5000"

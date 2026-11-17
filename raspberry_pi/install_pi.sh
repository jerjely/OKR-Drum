#!/bin/bash
# OKR Drum - Raspberry Pi side (camera recorder). Run once:  bash install_pi.sh
# Installs the packages from Raspberry Pi OS, enables the GPIO 14/15 serial port
# for the trial markers, and checks the recorder with its self-test.
set -e
cd "$(dirname "$0")"
sudo apt-get update
sudo apt-get install -y python3-picamera2 python3-opencv python3-serial python3-numpy
# serial port on GPIO 14/15 (pins 8 and 10), no login console on it
sudo raspi-config nonint do_serial_hw 0 || true
sudo raspi-config nonint do_serial_cons 1 || true
CFG=/boot/firmware/config.txt; [ -f "$CFG" ] || CFG=/boot/config.txt
if grep -q "Raspberry Pi 5" /proc/device-tree/model 2>/dev/null && ! grep -q "^dtparam=uart0=on" "$CFG"; then
  echo "dtparam=uart0=on" | sudo tee -a "$CFG" >/dev/null
  echo "Pi 5: enabled /dev/ttyAMA0 on pins 8/10 (reboot needed)."
fi
sudo usermod -aG dialout "$USER" || true
python3 okr_record_pi.py --selftest
echo
echo "Done. Reboot once (sudo reboot), then run okr_record_pi.py in Thonny."

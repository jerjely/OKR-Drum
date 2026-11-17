# OKR Drum – Raspberry Pi camera recorder

Records the overhead IR camera (grayscale, fixed frame rate), timestamps every frame,
logs the stimulus markers coming from the lab PC over the serial line and matches each
grating to its video frames. While a grating runs, the preview gets a red frame with the
trial number and parameters.

**Hardware:** Raspberry Pi (tested design: Pi 5) + Pi HQ Camera (or Camera Module 3),
USB-TTL adapter (CH340/CH341, set to 3.3 V and TTL/UART) from the lab PC:
adapter TXD → Pi pin 10, RXD → pin 8, GND → pin 6.

**Install (once):** `bash install_pi.sh`, then reboot. It installs picamera2, OpenCV and
pyserial from Raspberry Pi OS, enables the serial port (on a Pi 5 it adds
`dtparam=uart0=on`) and runs the self-test.

**Use:** open `okr_record_pi.py` in Thonny and Run. Answer mouse / treatment /
experiment, click on the camera image, then **R** = start recording, **ESC/Q** = stop.
Sliders set exposure, gain, brightness and contrast (remembered between sessions);
the green `sharp` number peaks when a manual lens is in focus.

Files per recording (in `OUTPUT_DIRECTORY`, set at the top of the script):
`_raw.mp4`, `_frames.csv` (timestamp + running trial per frame), `_markers.csv`,
`_info.json`.

Check without a camera: `python3 okr_record_pi.py --selftest`

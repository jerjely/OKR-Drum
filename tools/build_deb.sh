#!/bin/bash
# Builds the Raspberry Pi package:  bash tools/build_deb.sh <version> <out_dir>
# -> <out_dir>/OKR-Drum-<version>-RaspberryPi.deb  (architecture "all": pure Python, uses the
#    Raspberry Pi OS packages for the camera, Qt, OpenCV and serial).
set -e
VER="${1:?version}"; OUT="${2:-dist}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEBVER="$(echo "$VER" | sed 's/[^0-9A-Za-z.+~]/~/g')"
STAGE="$(mktemp -d)/okr-recorder"
mkdir -p "$STAGE/DEBIAN" "$STAGE/usr/lib/okr-recorder" "$STAGE/usr/bin" "$STAGE/usr/share/applications" \
         "$STAGE/usr/share/icons/hicolor/256x256/apps" "$STAGE/usr/share/okr-recorder" "$STAGE/usr/share/doc/okr-recorder"
cp -r "$ROOT/pi_app/okr_recorder" "$STAGE/usr/lib/okr-recorder/"
find "$STAGE" -name __pycache__ -prune -exec rm -rf {} +
sed -i "s/^__version__ = .*/__version__ = \"$VER\"     # set by the release build/" "$STAGE/usr/lib/okr-recorder/okr_recorder/__init__.py"
cp "$ROOT/pi_app/run.py" "$STAGE/usr/lib/okr-recorder/run.py"
printf '#!/bin/sh\nexec python3 /usr/lib/okr-recorder/run.py "$@"\n' > "$STAGE/usr/bin/okr-recorder"
cp "$ROOT/pi_app/okr-recorder-setup" "$STAGE/usr/bin/okr-recorder-setup"
chmod 755 "$STAGE/usr/bin/okr-recorder" "$STAGE/usr/bin/okr-recorder-setup"
cp "$ROOT/pi_app/okr-recorder.desktop" "$STAGE/usr/share/applications/"
cp "$ROOT/assets/icon/okr_drum_256.png" "$STAGE/usr/share/icons/hicolor/256x256/apps/okr-recorder.png"
cp "$ROOT/assets/icon/okr_drum_256.png" "$STAGE/usr/share/okr-recorder/okr_drum_256.png"
cp "$ROOT/LICENSE" "$STAGE/usr/share/doc/okr-recorder/copyright"
cat > "$STAGE/DEBIAN/control" <<CTRL
Package: okr-recorder
Version: $DEBVER
Architecture: all
Maintainer: Gergely Szarka <szarka.gergely@pte.hu>
Depends: python3 (>= 3.9), python3-pyqt5, python3-picamera2, python3-opencv, python3-numpy, python3-serial
Recommends: rclone
Section: science
Priority: optional
Homepage: https://github.com/jerjely/OKR-Drum
Description: OKR Drum camera recorder for the Raspberry Pi
 Records the optokinetic drum's overhead camera at a fixed frame rate, logs the
 stimulus markers and session info sent by OKR Drum on the lab PC over a serial
 line, matches them to video frames, and can upload every recording to Google
 Drive with rclone.
CTRL
printf '#!/bin/sh\nset -e\ncommand -v update-desktop-database >/dev/null && update-desktop-database -q || true\necho "OKR Drum recorder installed. First time: sudo okr-recorder-setup, then reboot."\nexit 0\n' > "$STAGE/DEBIAN/postinst"
chmod 755 "$STAGE/DEBIAN/postinst"
mkdir -p "$OUT"
dpkg-deb --root-owner-group --build "$STAGE" "$OUT/OKR-Drum-$VER-RaspberryPi.deb"

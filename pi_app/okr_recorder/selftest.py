"""Recorder self-test with a simulated camera (no Pi needed):  okr-recorder --selftest
Runs the real window offscreen; the lab PC is simulated on a pseudo-terminal (Linux / macOS):
session info -> automatic start, two gratings, run end -> automatic stop."""
from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import threading
import time

import cv2
import numpy as np

from . import __version__, core


class _Req:
    def __init__(self, i, ts, W, H):
        self.i, self.ts, self.W, self.H = i, ts, W, H

    def make_array(self, name):
        yuv = np.full((self.H * 3 // 2, self.W), 60, np.uint8)
        cx = int(self.W / 2 + 60 * np.cos(self.i / 10))
        cv2.ellipse(yuv[:self.H], (cx, self.H // 2), (50, 25), self.i * 3 % 180, 0, 360, 200, -1)
        return yuv

    def get_metadata(self):
        return {"SensorTimestamp": self.ts, "ExposureTime": 8000, "AnalogueGain": 4.0}

    def release(self):
        pass


class FakeCamera:
    camera_controls = {}

    def __init__(self, W, H, fps):
        self.W, self.H, self.fps, self.i = W, H, fps, 0

    def set_controls(self, c):
        pass

    def stop(self):
        pass

    def capture_request(self):
        time.sleep(1.0 / self.fps)
        self.i += 1
        return _Req(self.i, core.now_ns(), self.W, self.H)


def run():
    fails = []

    def check(c, m):
        print(("  ok    " if c else "  FAIL  ") + m, flush=True)
        if not c:
            fails.append(m)

    print("OKR Drum recorder self-test, version %s" % __version__)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    tmp = tempfile.mkdtemp(prefix="okr_rec_selftest_")
    core.CONFIG_DIR = os.path.join(tmp, "cfg")
    core.CONFIG_FILE = os.path.join(core.CONFIG_DIR, "config.json")
    from . import uploader as up
    up.QUEUE_FILE = os.path.join(core.CONFIG_DIR, "queue.json")
    cfg = core.load_config()
    cfg.update(output_dir=os.path.join(tmp, "rec"), width=640, height=480, fps=30, auto_record=True, upload=False)
    use_pty = hasattr(os, "openpty")
    master = None
    if use_pty:
        master, slave = os.openpty()
        cfg["serial_port"] = os.ttyname(slave)
    else:
        cfg["serial_port"] = "COM_SELFTEST_NONE"
    listener = core.SerialListener(cfg["serial_port"], 115200, 120)
    if listener.ok:
        listener.start()
    rec = core.Recorder(cfg, camera=FakeCamera(640, 480, 30), listener=listener)
    from .app import STYLE, RecorderWindow
    from .qt import QtCore, QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    app.setStyleSheet(STYLE)
    w = RecorderWindow(recorder=rec, config=cfg)
    w.show()

    def pc():
        time.sleep(0.3)
        # "Send session info" button: fills the fields but must not start a recording
        os.write(master, ("S " + json.dumps({"animal": "M06", "treatment": "pre"}) + "\n").encode())
        time.sleep(0.6)
        info = {"animal": "M07", "session": "2", "treatment": "saline", "stim_log": "M07_s2_x.csv",
                "run_start": True}
        os.write(master, ("S " + json.dumps(info) + "\n").encode())
        time.sleep(0.8)
        for k, wait in ((1, 0.6), (2, 0.5)):
            os.write(master, b"T%d c=1 w=5.000 v=12 CW\n" % k)
            time.sleep(wait)
            os.write(master, b"E%d\n" % k)
            time.sleep(0.3)
        os.write(master, b"X\n")

    def spin(seconds):
        t0 = time.time()
        while time.time() - t0 < seconds:
            app.processEvents()
            time.sleep(0.01)

    if use_pty:
        threading.Thread(target=pc, daemon=True).start()
        spin(0.6)
        check(w.mouse.text() == "M06" and not rec.recording,
              "'Send session info' fills the fields without starting a recording")
        spin(0.7)
        check(w.mouse.text() == "M07" and w.treat.text() == "saline", "session info from the PC filled the fields")
        check(rec.recording, "recording started automatically with the run")
        spin(4.5)
        check(not rec.recording, "recording stopped automatically at the run end")
    else:
        rec.listener.handle('S {"animal": "M07"}', core.now_ns())
        spin(0.3)
        check(w.mouse.text() == "M07", "session info handled (no pseudo-terminal on this OS)")
        w.toggle()
        spin(1.5)
        w.toggle()
    files = sorted(os.listdir(cfg["output_dir"])) if os.path.isdir(cfg["output_dir"]) else []
    vid = [f for f in files if f.endswith(("_raw.mp4", "_raw.avi"))]
    check(len(vid) == 1, "video written (%s)" % (vid[0] if vid else "none"))
    if vid:
        cap = cv2.VideoCapture(os.path.join(cfg["output_dir"], vid[0]))
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        check(n > 20, "video readable, %d frames" % n)
        base = os.path.join(cfg["output_dir"], vid[0][: -len("_raw.mp4")])
        info = json.load(open(base + "_info.json"))
        check(info.get("app_version") == __version__, "info.json written")
        if use_pty:
            check(info.get("session_info", {}).get("stim_log") == "M07_s2_x.csv", "session info saved with the video")
            mk = list(csv.DictReader(open(base + "_markers.csv")))
            check([m["message"].split()[0] for m in mk] == ["T1", "E1", "T2", "E2"], "markers T1 E1 T2 E2 logged")
            check(all(m["frame"] != "" for m in mk), "markers matched to video frames")
            rows = list(csv.DictReader(open(base + "_frames.csv")))
            tr = [r["trial"] for r in rows]
            check(tr.count("1") > 5 and tr.count("2") > 5, "trial column filled during both gratings")
    # uploader with a stand-in for rclone
    up.QUEUE_FILE = os.path.join(tempfile.mkdtemp(), "queue.json")
    class Bad:
        returncode, stderr = 1, 'ERROR : x: Failed to copy: {"error":"invalid_grant","error_codes":[700082]}'
    ub = up.Uploader("onedrive:OKR Drum/recordings", runner=lambda cmd: Bad())
    ub.add([os.path.join(cfg["output_dir"], files[0])], day="2026-01-01")
    ub.start()
    t0 = time.time()
    while "waiting to retry" not in ub.status and time.time() - t0 < 5:
        time.sleep(0.05)
    ub.close()
    check("rclone config reconnect onedrive:" in ub.status, "a sign-in error is explained (%s)" % ub.status[:60])
    calls = []

    class R:
        returncode, stderr = 0, ""
    u = up.Uploader("gdrive:OKR Drum/recordings", runner=lambda cmd: (calls.append(cmd), R())[1])
    u.add([os.path.join(cfg["output_dir"], f) for f in files], day="2026-01-01")
    u.start()
    t0 = time.time()
    while u.pending() and time.time() - t0 < 5:
        time.sleep(0.05)
    u.close()
    check(calls and calls[0][3].startswith("gdrive:OKR Drum/recordings/2026-01-01/"),
          "files stuck for the old destination go to the new one")
    check(u.pending() == 0 and len(calls) == len(files) + 1 and calls and calls[0][1] == "copyto"
          and calls[0][3].startswith("gdrive:OKR Drum/recordings/2026-01-01/"),
          "upload queue sends every file with rclone (%d calls)" % len(calls))
    w.close()
    print("\nSELF-TEST %s (%d problem%s)" % ("PASSED" if not fails else "FAILED", len(fails), "" if len(fails) == 1 else "s"))
    return 0 if not fails else 1

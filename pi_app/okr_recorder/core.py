"""Camera, serial markers and file writing - no GUI here (also used by the self-test).

Files per recording (in the output folder):
    <time>_<mouse>_<treatment>_<experiment>_<date-time>_raw.mp4   grayscale video at exactly FPS
    ..._frames.csv     every frame: sensor timestamp, unix time, exposure, gain, running trial
    ..._markers.csv    every grating onset (T) and end (E) from the lab PC, with its video frame
    ..._info.json      mouse / treatment / experiment, camera settings, app version
"""
from __future__ import annotations

import csv
import json
import os
import queue
import threading
import time
from datetime import datetime

import cv2
import numpy as np

from . import __version__

DEFAULT_CONFIG = {
    "output_dir": os.path.join(os.path.expanduser("~"), "Desktop", "Behaviour"),
    "width": 1280, "height": 960, "fps": 30,
    "serial_port": "auto", "baud": 115200, "stim_timeout_s": 120,
    "auto_record": False,
    "upload": False, "rclone_remote": "gdrive:OKR Drum/recordings", "upload_delete_local": False,
    "sliders": {"Auto exposure": 0, "Exposure 0.1ms": 80, "Gain x10": 40, "Brightness": 100,
                "Contrast x10": 10, "Focus x10": 57},
}
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".okr-recorder")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")


def load_config():
    c = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            d = json.load(f)
        for k, v in d.items():
            if isinstance(v, dict) and isinstance(c.get(k), dict):
                c[k].update(v)
            elif k in c:
                c[k] = v
    except Exception:
        pass
    return c


def save_config(c):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(c, f, indent=1)
    except Exception:
        pass


def now_ns():
    """Same clock as the camera's SensorTimestamp (time since boot)."""
    if hasattr(time, "CLOCK_BOOTTIME"):
        return time.clock_gettime_ns(time.CLOCK_BOOTTIME)
    return time.monotonic_ns()


def slider_max(fps):
    return {"Auto exposure": 1, "Exposure 0.1ms": int(1e6 / fps / 100), "Gain x10": 160, "Brightness": 200,
            "Contrast x10": 40, "Focus x10": 150}


def sliders_to_controls(v, has_focus):
    c = {"Brightness": (v["Brightness"] - 100) / 100.0, "Contrast": max(v["Contrast x10"], 1) / 10.0}
    if v["Auto exposure"]:
        c["AeEnable"] = True
    else:
        c.update({"AeEnable": False, "ExposureTime": max(v["Exposure 0.1ms"], 1) * 100,
                  "AnalogueGain": max(v["Gain x10"], 10) / 10.0})
    if has_focus:
        c.update({"AfMode": 0, "LensPosition": v["Focus x10"] / 10.0})
    return c


def open_video_writer(path, fps, size):
    """Absolute path + codec fallback (mp4v -> avc1 -> MJPG .avi). Returns (writer, path)."""
    path = os.path.abspath(path)
    stem, _ = os.path.splitext(path)
    for fourcc, ext in (("mp4v", ".mp4"), ("avc1", ".mp4"), ("MJPG", ".avi")):
        w = cv2.VideoWriter(stem + ext, cv2.VideoWriter_fourcc(*fourcc), float(fps), size, isColor=False)
        if w.isOpened():
            return w, stem + ext
        w.release()
    raise RuntimeError("could not open a video writer for %s" % path)


# ---------------------------------------------------------------------- serial markers
class SerialListener(threading.Thread):
    """Reads 'T<n> ...' (grating onset) and 'E<n>' (grating end), timestamps them on arrival."""

    def __init__(self, port="auto", baud=115200, stim_timeout_s=120):
        super().__init__(daemon=True)
        self.markers, self.recent = [], []
        self.recording, self.ok, self.stop_flag = False, False, False
        self.lock = threading.Lock()
        self.stim, self.last = None, None
        self.session_info, self.session_seq = {}, 0     # from 'S {json}'; seq counts arrivals
        self.run_end_seq = 0                            # counts 'X' (run finished)
        self.timeout = stim_timeout_s
        if port == "auto":
            port = "/dev/ttyAMA0" if os.path.exists("/dev/ttyAMA0") else "/dev/serial0"
        self.port, self.error = port, ""
        try:
            import serial
            self.ser = serial.Serial(port, baud, timeout=0.05)
            self.ser.reset_input_buffer()
            self.ok = True
        except Exception as e:
            self.error = str(e)

    def run(self):
        if not self.ok:
            return
        buf = b""
        while not self.stop_flag:
            try:
                data = self.ser.read(64)
            except Exception:
                break
            t_ns = now_ns()
            if not data:
                continue
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                msg = line.decode(errors="replace").strip()
                if msg:
                    self.handle(msg, t_ns)

    def handle(self, msg, t_ns):
        label = msg.split()[0]
        if label == "S":
            try:
                info = json.loads(msg[1:].strip())
            except Exception:
                info = {"raw": msg[1:].strip()}
            with self.lock:
                self.session_info, self.session_seq = info, self.session_seq + 1
                self.recent = (self.recent + [(time.strftime("%H:%M:%S"), "session: %s" % ", ".join(
                    "%s=%s" % kv for kv in info.items() if kv[0] in ("animal", "treatment", "session")))])[-50:]
            return
        if label == "X":
            with self.lock:
                self.run_end_seq += 1
                self.recent = (self.recent + [(time.strftime("%H:%M:%S"), "run finished")])[-50:]
            return
        with self.lock:
            if label.startswith("T"):
                self.stim = (label[1:], msg[len(label):].strip(), t_ns)
            elif label.startswith("E") and self.stim is not None:
                self.last = ("T%s %s" % (self.stim[0], self.stim[1]), (t_ns - self.stim[2]) / 1e9)
                self.stim = None
            if self.recording:
                self.markers.append({"message": msg, "arrival_ns": t_ns, "unix_time": time.time()})
            self.recent = (self.recent + [(time.strftime("%H:%M:%S"), msg)])[-50:]

    def state(self):
        with self.lock:
            if self.stim is not None and (now_ns() - self.stim[2]) / 1e9 > self.timeout:
                self.stim = None
            return self.stim, self.last

    def close(self):
        self.stop_flag = True
        if self.ok:
            try:
                self.ser.close()
            except Exception:
                pass


class VideoWriterThread(threading.Thread):
    """Writes frames from a queue so encoding never blocks the camera loop."""

    def __init__(self, path, fps, size):
        super().__init__(daemon=True)
        self.raw, self.path = open_video_writer(path, fps, size)
        self.q = queue.Queue(maxsize=600)
        self.dropped = 0

    def put(self, gray):
        try:
            self.q.put_nowait(gray)
        except queue.Full:
            self.dropped += 1

    def run(self):
        while True:
            g = self.q.get()
            if g is None:
                break
            self.raw.write(g)

    def finish(self):
        self.q.put(None)
        self.join()
        self.raw.release()


def match_markers_to_frames(markers, frame_ts):
    ts = np.array(frame_ts, dtype=np.int64)
    for m in markers:
        i = int(np.searchsorted(ts, m["arrival_ns"], side="left"))
        m["frame"] = i if i < len(ts) else ""
        m["frame_delay_ms"] = round((ts[i] - m["arrival_ns"]) / 1e6, 2) if i < len(ts) else ""
    return markers


def trial_per_frame(markers, frame_ts):
    trial = [""] * len(frame_ts)
    ts = np.array(frame_ts, dtype=np.int64)
    onset = {}
    for m in markers:
        lab = m["message"].split()[0]
        if lab.startswith("T"):
            onset[lab[1:]] = m["arrival_ns"]
        elif lab.startswith("E") and lab[1:] in onset:
            a = int(np.searchsorted(ts, onset.pop(lab[1:]), side="left"))
            b = int(np.searchsorted(ts, m["arrival_ns"], side="left"))
            for i in range(a, min(b, len(trial))):
                trial[i] = lab[1:]
    for num, t0 in onset.items():
        a = int(np.searchsorted(ts, t0, side="left"))
        for i in range(a, len(trial)):
            trial[i] = num
    return trial


# ---------------------------------------------------------------------- camera loop
def make_camera(width, height, fps):
    from picamera2 import Picamera2
    cam = Picamera2()
    us = int(1e6 / fps)
    cfg = cam.create_video_configuration(main={"size": (width, height), "format": "YUV420"}, buffer_count=6,
                                         controls={"FrameDurationLimits": (us, us)})
    cam.configure(cfg)
    cam.start()
    return cam


class Recorder:
    """Runs the camera in a background thread. The GUI reads `latest` for the preview and
    calls start()/stop(). stop() returns the list of files written."""

    def __init__(self, config, camera=None, listener=None):
        self.cfg = config
        self.size = (int(config["width"]), int(config["height"]))
        self.fps = float(config["fps"])
        self.cam = camera or make_camera(self.size[0], self.size[1], self.fps)
        self.has_focus = "AfMode" in getattr(self.cam, "camera_controls", {})
        self.listener = listener or SerialListener(config["serial_port"], config["baud"], config["stim_timeout_s"])
        if not self.listener.is_alive() and self.listener.ok:
            self.listener.start()
        self.lock = threading.Lock()
        self.latest, self.md = None, {}
        self.recording, self.writer, self.rows, self.base = False, None, [], None
        self.sharp = 0.0
        self.n = 0
        self.error = ""
        self.stop_flag = False
        self.set_sliders(config["sliders"])
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def set_sliders(self, v):
        self.sliders = dict(v)
        try:
            self.cam.set_controls(sliders_to_controls(self.sliders, self.has_focus))
        except Exception as e:
            self.error = "camera controls: %s" % e

    def _loop(self):
        W, H = self.size
        while not self.stop_flag:
            try:
                req = self.cam.capture_request()
                yuv = req.make_array("main")
                md = req.get_metadata()
                req.release()
            except Exception as e:
                self.error = str(e)
                time.sleep(0.2)
                continue
            gray = np.ascontiguousarray(yuv[:H, :W])
            self.n += 1
            with self.lock:
                if self.recording:
                    self.rows.append([len(self.rows), md.get("SensorTimestamp", now_ns()), time.time(),
                                      md.get("ExposureTime", ""), round(md.get("AnalogueGain", 0), 3)])
                    self.writer.put(gray)
                self.latest, self.md = gray, md
            if self.n % 3 == 0:
                h, w = gray.shape
                v = cv2.Laplacian(gray[h // 3:2 * h // 3, w // 3:2 * w // 3], cv2.CV_64F).var()
                self.sharp = v if self.sharp == 0 else 0.7 * self.sharp + 0.3 * v

    def start(self, mouse, treatment, experiment):
        os.makedirs(self.cfg["output_dir"], exist_ok=True)
        safe = lambda s: "".join(c if c.isalnum() or c in "-_." else "_" for c in (s or "none"))
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.base = os.path.join(os.path.abspath(self.cfg["output_dir"]), "%s_%s_%s_%s_%s" % (
            datetime.now().strftime("%H_%M"), safe(mouse), safe(treatment), safe(experiment), stamp))
        writer = VideoWriterThread(self.base + "_raw.mp4", self.fps, self.size)
        writer.start()
        self.meta = {"mouse": mouse, "treatment": treatment, "experiment": experiment}
        with self.lock:
            self.writer, self.rows = writer, []
            with self.listener.lock:
                self.listener.markers = []
                self.listener.recording = True
            self.recording = True
            self.t_start = time.time()
        with open(self.base + "_info.json", "w", encoding="utf-8") as f:
            json.dump({**self.meta, "size": list(self.size), "fps": self.fps, **self.sliders,
                       **sliders_to_controls(self.sliders, self.has_focus), "start_unix_time": self.t_start,
                       "serial_port": self.listener.port, "serial_ok": self.listener.ok, "app_version": __version__,
                       "session_info": dict(self.listener.session_info)},
                      f, indent=1)
        return writer.path

    def stop(self):
        if not self.recording:
            return [], {}
        with self.lock:
            self.recording = False
            self.listener.recording = False
            writer, rows = self.writer, self.rows
        writer.finish()
        ts = [r[1] for r in rows]
        markers = match_markers_to_frames(list(self.listener.markers), ts)
        for row, tr in zip(rows, trial_per_frame(markers, ts)):
            row.append(tr)
        with open(self.base + "_frames.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["frame", "sensor_timestamp_ns", "unix_time", "exposure_us", "analogue_gain", "trial"])
            w.writerows(rows)
        with open(self.base + "_markers.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["message", "frame", "frame_delay_ms", "arrival_ns", "unix_time"])
            w.writeheader()
            w.writerows(markers)
        summary = {"frames": len(rows), "gratings": sum(1 for m in markers if m["message"].startswith("T")),
                   "dropped_writes": writer.dropped}
        if len(rows) > 1:
            dt = np.diff(ts) / 1e6
            summary.update(fps=round(1000 / dt.mean(), 2), gaps=int(np.sum(dt > 1.5 * 1000 / self.fps)))
        try:                                   # session info may have arrived after the start
            with open(self.base + "_info.json", encoding="utf-8") as f:
                info = json.load(f)
            info.update(session_info=dict(self.listener.session_info), stop_unix_time=time.time(), **summary)
            with open(self.base + "_info.json", "w", encoding="utf-8") as f:
                json.dump(info, f, indent=1)
        except Exception:
            pass
        files = [writer.path, self.base + "_frames.csv", self.base + "_markers.csv", self.base + "_info.json"]
        return files, summary

    def close(self):
        if self.recording:
            self.stop()
        self.stop_flag = True
        self.thread.join(timeout=2)
        self.listener.close()
        try:
            self.cam.stop()
        except Exception:
            pass


def draw_preview(gray, md, sharp, recording, stim, last, listener_ok, hint=True):
    """Preview image (BGR) with the same overlay as the Thonny script."""
    H, W = gray.shape
    prev = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    info = "exp %.1f ms  gain %.1fx  mean %d  sharp %d" % (md.get("ExposureTime", 0) / 1000,
                                                          md.get("AnalogueGain", 0), int(gray.mean()), int(sharp))
    cv2.putText(prev, info, (15, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
    if recording:
        cv2.circle(prev, (W - 40, 40), 14, (0, 0, 255), -1)
        cv2.putText(prev, "REC", (W - 120, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
    if stim is not None:
        secs = (now_ns() - stim[2]) / 1e9
        cv2.rectangle(prev, (0, 0), (W - 1, H - 1), (0, 0, 255), 14)
        cv2.putText(prev, "STIMULUS ON  trial %s   %.1f s" % (stim[0], secs), (15, H - 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)
        if stim[1]:
            cv2.putText(prev, stim[1], (15, H - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
    elif last is not None:
        cv2.putText(prev, "last: %s  (%.1f s)" % last, (15, H - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 2)
    elif not listener_ok:
        cv2.putText(prev, "no serial port - no stimulus markers", (15, H - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                    (0, 165, 255), 2)
    return prev

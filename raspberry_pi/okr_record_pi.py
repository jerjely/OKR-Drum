"""
OKR drum - Raspberry Pi recording with trial sync, live stimulus feedback and
image adjustment (run in Thonny, or: python3 okr_record_pi.py)

Enter mouse / treatment / experiment. In the preview window:
    sliders   Auto exposure (1 = camera decides, 0 = use the sliders), Exposure (0.1 ms),
              Gain x10, Brightness (100 = normal), Contrast x10 (10 = normal),
              Focus x10 (only for cameras with motorised focus)
    R         start recording (TAB also works if the sliders don't catch it)
    ESC / Q   stop recording and quit
(Click on the camera image first so the window receives the keys.)

Live feedback: when the PsychoPy PC starts a grating, the preview gets a red frame and
shows the trial number, its parameters and how long it has been running; when the
grating ends it turns back to normal. This works even when not recording (handy for
testing the serial link).

Saved per recording (in OUTPUT_DIRECTORY):
    _raw.mp4            grayscale video at exactly FPS
    _frames.csv         every frame: timestamp, exposure, gain, trial running (if any)
    _markers.csv        every grating onset (T) and end (E), with the video frame it falls on
    _info.json          mouse / treatment / experiment and all camera settings
Slider positions are remembered for next time (camera_settings.json).

Raspberry Pi 5: the GPIO 14/15 serial port is /dev/ttyAMA0 (needs  dtparam=uart0=on
in /boot/firmware/config.txt). Older Pis: /dev/serial0. The script picks automatically.

Self-test with a simulated camera (no Pi needed):  python3 okr_record_pi.py --selftest
"""
import csv
import json
import os
import queue
import threading
import time
from datetime import datetime

import sys

import cv2
import numpy as np
# picamera2 is imported in main(), so the self-test also runs on a PC.

__version__ = "dev"         # replaced with the release tag by the GitHub build

# ------------------------------------------------------------------ settings
OUTPUT_DIRECTORY = '/home/retina/Desktop/Behaviour'
SIZE = (1280, 960)          # keep the same size as the lens calibration
FPS = 30                    # fixed camera frame rate = video file frame rate
SAVE_ENHANCED = False       # True = also save a contrast-enhanced (CLAHE) copy
SERIAL_PORT = 'auto'        # 'auto' = /dev/ttyAMA0 if present (Pi 5), else /dev/serial0
SERIAL_BAUD = 115200
PREVIEW_EVERY = 2           # show every n-th frame in the preview (saves CPU)
STIM_TIMEOUT_S = 120        # clear "stimulus on" if no end marker arrives (old PC script)
SETTINGS_FILE = os.path.join(OUTPUT_DIRECTORY, 'camera_settings.json')
# ------------------------------------------------------------------

MAX_EXPOSURE_TENTHS_MS = int(1e6 / FPS / 100)
DEFAULT_SLIDERS = {'Auto exposure': 0, 'Exposure 0.1ms': min(80, MAX_EXPOSURE_TENTHS_MS),
                   'Gain x10': 40, 'Brightness': 100, 'Contrast x10': 10, 'Focus x10': 57}
SLIDER_MAX = {'Auto exposure': 1, 'Exposure 0.1ms': MAX_EXPOSURE_TENTHS_MS, 'Gain x10': 160,
              'Brightness': 200, 'Contrast x10': 40, 'Focus x10': 150}
HAS_FOCUS = False


def now_ns():
    """Same clock as the camera's SensorTimestamp (time since boot)."""
    if hasattr(time, 'CLOCK_BOOTTIME'):
        return time.clock_gettime_ns(time.CLOCK_BOOTTIME)
    return time.monotonic_ns()      # only used by the self-test on Windows / macOS


def open_video_writer(path, fps, size):
    """Absolute path + codec fallback (mp4v -> avc1 -> MJPG .avi). Returns (writer, path)."""
    path = os.path.abspath(path)
    stem, _ = os.path.splitext(path)
    for fourcc, ext in (('mp4v', '.mp4'), ('avc1', '.mp4'), ('MJPG', '.avi')):
        w = cv2.VideoWriter(stem + ext, cv2.VideoWriter_fourcc(*fourcc), float(fps), size, isColor=False)
        if w.isOpened():
            if fourcc != 'mp4v':
                print(f"  note: video saved with the {fourcc} codec as {os.path.basename(stem + ext)}")
            return w, stem + ext
        w.release()
    raise RuntimeError(f"could not open a video writer for {path}")


# ------------------------------------------------------------------ camera settings
def sliders_to_controls(v):
    c = {'Brightness': (v['Brightness'] - 100) / 100.0, 'Contrast': max(v['Contrast x10'], 1) / 10.0}
    if v['Auto exposure']:
        c['AeEnable'] = True
    else:
        c.update({'AeEnable': False, 'ExposureTime': max(v['Exposure 0.1ms'], 1) * 100,
                  'AnalogueGain': max(v['Gain x10'], 10) / 10.0})
    if HAS_FOCUS:
        c.update({'AfMode': 0, 'LensPosition': v['Focus x10'] / 10.0})
    return c


def load_sliders():
    v = dict(DEFAULT_SLIDERS)
    try:
        with open(SETTINGS_FILE) as f:
            v.update({k: int(x) for k, x in json.load(f).items() if k in v})
    except Exception:
        pass
    return {k: min(max(x, 0), SLIDER_MAX[k]) for k, x in v.items()}


# ------------------------------------------------------------------ serial markers
class SerialListener(threading.Thread):
    """Reads 'T<n> ...' (grating onset) and 'E<n>' (grating end), timestamps them on arrival."""

    def __init__(self):
        super().__init__(daemon=True)
        self.markers = []
        self.recording = False
        self.ok = False
        self.stop_flag = False
        self.lock = threading.Lock()
        self.stim = None          # (trial label, text, onset_ns) while a grating is on
        self.last = None          # (text, duration_s) of the last finished grating
        port = SERIAL_PORT
        if port == 'auto':
            port = '/dev/ttyAMA0' if os.path.exists('/dev/ttyAMA0') else '/dev/serial0'
        self.port = port
        try:
            import serial
            self.ser = serial.Serial(port, SERIAL_BAUD, timeout=0.05)
            self.ser.reset_input_buffer()
            self.ok = True
            print(f"Listening for trial markers on {port}")
        except Exception as e:
            print(f"WARNING: serial port {port} not available ({e}) - no trial markers")

    def run(self):
        if not self.ok:
            return
        buf = b''
        while not self.stop_flag:
            try:
                data = self.ser.read(64)
            except Exception:
                break
            t_ns = now_ns()
            if not data:
                continue
            buf += data
            while b'\n' in buf:
                line, buf = buf.split(b'\n', 1)
                msg = line.decode(errors='replace').strip()
                if msg:
                    self.handle(msg, t_ns)

    def handle(self, msg, t_ns):
        label = msg.split()[0]
        with self.lock:
            if label.startswith('T'):
                self.stim = (label[1:], msg[len(label):].strip(), t_ns)
            elif label.startswith('E') and self.stim is not None:
                self.last = ('T%s %s' % (self.stim[0], self.stim[1]), (t_ns - self.stim[2]) / 1e9)
                self.stim = None
            if self.recording:
                self.markers.append({'message': msg, 'arrival_ns': t_ns, 'unix_time': time.time()})
        print(f"  marker {msg}")

    def state(self):
        with self.lock:
            if self.stim is not None and (now_ns() - self.stim[2]) / 1e9 > STIM_TIMEOUT_S:
                self.stim = None
            return self.stim, self.last

    def close(self):
        self.stop_flag = True
        if self.ok:
            self.ser.close()


# ------------------------------------------------------------------ video writing
class VideoWriterThread(threading.Thread):
    """Writes frames from a queue so encoding never blocks the camera loop."""

    def __init__(self, path_raw, path_enh):
        super().__init__(daemon=True)
        self.raw, self.path = open_video_writer(path_raw, FPS, SIZE)
        self.enh = open_video_writer(path_enh, FPS, SIZE)[0] if path_enh else None
        self.clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        self.q = queue.Queue(maxsize=600)
        self.dropped = 0

    def put(self, gray):
        try:
            self.q.put_nowait(gray)
        except queue.Full:
            self.dropped += 1

    def run(self):
        while True:
            gray = self.q.get()
            if gray is None:
                break
            self.raw.write(gray)
            if self.enh is not None:
                self.enh.write(self.clahe.apply(gray))

    def finish(self):
        self.q.put(None)
        self.join()
        self.raw.release()
        if self.enh is not None:
            self.enh.release()


def match_markers_to_frames(markers, frame_ts):
    """Each marker -> first frame whose exposure started at/after the marker arrived."""
    ts = np.array(frame_ts, dtype=np.int64)
    for m in markers:
        i = int(np.searchsorted(ts, m['arrival_ns'], side='left'))
        m['frame'] = i if i < len(ts) else ''
        m['frame_delay_ms'] = round((ts[i] - m['arrival_ns']) / 1e6, 2) if i < len(ts) else ''
    return markers


def trial_per_frame(markers, frame_ts):
    """Trial number running during each frame ('' between gratings)."""
    trial = [''] * len(frame_ts)
    ts = np.array(frame_ts, dtype=np.int64)
    onset = {}
    for m in markers:
        lab = m['message'].split()[0]
        if lab.startswith('T'):
            onset[lab[1:]] = m['arrival_ns']
        elif lab.startswith('E') and lab[1:] in onset:
            a = int(np.searchsorted(ts, onset.pop(lab[1:]), side='left'))
            b = int(np.searchsorted(ts, m['arrival_ns'], side='left'))
            for i in range(a, min(b, len(trial))):
                trial[i] = lab[1:]
    for num, t0 in onset.items():          # onset without end (recording stopped mid-trial)
        a = int(np.searchsorted(ts, t0, side='left'))
        for i in range(a, len(trial)):
            trial[i] = num
    return trial


# ------------------------------------------------------------------ main
def main():
    global HAS_FOCUS
    from picamera2 import Picamera2
    print(f"OKR Drum camera recorder  v{__version__}")
    current_time = datetime.now().strftime("%H_%M")
    mouse = input("Mouse name: ")
    treatment = input("Treatment: ")
    experiment = input("Experiment type: ")
    os.makedirs(OUTPUT_DIRECTORY, exist_ok=True)

    try:
        picam2 = Picamera2()
        frame_us = int(1e6 / FPS)
        cfg = picam2.create_video_configuration(
            main={"size": SIZE, "format": "YUV420"}, buffer_count=6,
            controls={"FrameDurationLimits": (frame_us, frame_us)})
        picam2.configure(cfg)
        picam2.start()
        HAS_FOCUS = 'AfMode' in picam2.camera_controls
        if not HAS_FOCUS:
            print("Manual-focus lens: turn the focus ring until the 'sharp' value in the preview peaks.")
    except Exception as e:
        print(f"Error initializing the camera: {e}")
        return

    listener = SerialListener()
    listener.start()

    window_name = "Preview"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    sliders = load_sliders()
    for name, val in sliders.items():
        if name == 'Focus x10' and not HAS_FOCUS:
            continue
        cv2.createTrackbar(name, window_name, val, SLIDER_MAX[name], lambda x: None)
    picam2.set_controls(sliders_to_controls(sliders))
    print("Click on the camera image, then: R = start recording, ESC or Q = stop and quit.")

    recording = False
    writer = None
    frame_rows = []
    base = None
    n = 0
    sharp = 0.0

    while True:
        try:
            new = {k: (cv2.getTrackbarPos(k, window_name) if (k != 'Focus x10' or HAS_FOCUS) else sliders[k])
                   for k in sliders}
            if new != sliders:
                sliders = new
                picam2.set_controls(sliders_to_controls(sliders))
                if recording:
                    print("  note: image settings changed during recording")

            request = picam2.capture_request()
            yuv = request.make_array("main")
            md = request.get_metadata()
            request.release()
            gray = np.ascontiguousarray(yuv[:SIZE[1], :SIZE[0]])   # Y plane = grayscale
            n += 1

            if recording:
                frame_rows.append([len(frame_rows), md.get("SensorTimestamp", now_ns()), time.time(),
                                   md.get("ExposureTime", ''), round(md.get("AnalogueGain", 0), 3)])
                writer.put(gray)

            if n % 3 == 0:   # focus aid: sharpness of the central third
                h, w = gray.shape
                v = cv2.Laplacian(gray[h // 3:2 * h // 3, w // 3:2 * w // 3], cv2.CV_64F).var()
                sharp = v if sharp == 0 else 0.7 * sharp + 0.3 * v

            if n % PREVIEW_EVERY == 0:
                prev = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
                stim, last = listener.state()
                info = "exp %.1f ms  gain %.1fx  mean %d  sharp %d" % (
                    md.get("ExposureTime", 0) / 1000, md.get("AnalogueGain", 0), int(gray.mean()), int(sharp))
                cv2.putText(prev, info, (15, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
                if recording:
                    cv2.circle(prev, (SIZE[0] - 40, 40), 14, (0, 0, 255), -1)
                    cv2.putText(prev, "REC", (SIZE[0] - 120, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
                hint = "ESC / Q = stop and quit" if recording else "R = start recording   ESC / Q = quit"
                cv2.putText(prev, hint, (15, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
                if stim is not None:
                    secs = (now_ns() - stim[2]) / 1e9
                    cv2.rectangle(prev, (0, 0), (SIZE[0] - 1, SIZE[1] - 1), (0, 0, 255), 14)
                    cv2.putText(prev, "STIMULUS ON  trial %s   %.1f s" % (stim[0], secs), (15, SIZE[1] - 60),
                                cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)
                    if stim[1]:
                        cv2.putText(prev, stim[1], (15, SIZE[1] - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
                elif last is not None:
                    cv2.putText(prev, "last: %s  (%.1f s)" % last, (15, SIZE[1] - 20),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 2)
                elif not listener.ok:
                    cv2.putText(prev, "no serial port - no stimulus markers", (15, SIZE[1] - 20),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 165, 255), 2)
                cv2.imshow(window_name, prev)
            key = cv2.waitKey(1) & 0xFF

            if key not in (255, 9, 27) and key not in (ord('r'), ord('R'), ord('q'), ord('Q')):
                print(f"  (key code {key} pressed - R starts recording, ESC/Q quits)")

            if key in (9, ord('r'), ord('R')) and not recording:     # R or TAB
                stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                base = os.path.join(OUTPUT_DIRECTORY, f"{current_time}_{mouse}_{treatment}_{experiment}_{stamp}")
                writer = VideoWriterThread(base + "_raw.mp4", base + "_enhanced.mp4" if SAVE_ENHANCED else None)
                writer.start()
                frame_rows = []
                with listener.lock:
                    listener.markers = []
                    listener.recording = True
                recording = True
                with open(base + "_info.json", "w") as f:
                    json.dump({"mouse": mouse, "treatment": treatment, "experiment": experiment,
                               "size": SIZE, "fps": FPS, **sliders, **sliders_to_controls(sliders),
                               "start_unix_time": time.time(), "serial_port": listener.port,
                               "app_version": __version__,
                               "serial_ok": listener.ok}, f, indent=1)
                print(f"Recording to: {writer.path}")

            elif key in (27, ord('q'), ord('Q')):                      # ESC or Q
                break

        except Exception as e:
            print(f"Error during main loop: {e}")
            break

    with open(SETTINGS_FILE, "w") as f:
        json.dump(sliders, f, indent=1)

    if recording:
        print("Stopping recording, finishing video file...")
        listener.recording = False
        writer.finish()
        frame_ts = [r[1] for r in frame_rows]
        markers = match_markers_to_frames(listener.markers, frame_ts)
        for row, tr in zip(frame_rows, trial_per_frame(markers, frame_ts)):
            row.append(tr)
        with open(base + "_frames.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["frame", "sensor_timestamp_ns", "unix_time", "exposure_us", "analogue_gain", "trial"])
            w.writerows(frame_rows)
        with open(base + "_markers.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["message", "frame", "frame_delay_ms", "arrival_ns", "unix_time"])
            w.writeheader()
            w.writerows(markers)
        if len(frame_rows) > 1:
            dt = np.diff(frame_ts) / 1e6
            print(f"{len(frame_rows)} frames, mean interval {dt.mean():.2f} ms "
                  f"({1000 / dt.mean():.1f} fps), {int(np.sum(dt > 1.5 * 1000 / FPS))} gaps")
        if writer.dropped:
            print(f"WARNING: {writer.dropped} frames could not be written (disk/encoder too slow)")
        print(f"{sum(1 for m in markers if m['message'].startswith('T'))} gratings recorded. Files: {base}_*")

    listener.close()
    picam2.stop()
    cv2.destroyAllWindows()


# ------------------------------------------------------------------ self-test
def selftest():
    """Runs the full recorder on a simulated camera with simulated key presses and,
    where the OS has pseudo-terminals (Linux, macOS), simulated trial markers on a
    serial line. Exit code 0 = all good."""
    import builtins
    import tempfile
    import types
    global OUTPUT_DIRECTORY, SETTINGS_FILE, SERIAL_PORT
    fails = []

    def check(cond, msg):
        print(('  ok    ' if cond else '  FAIL  ') + msg)
        if not cond:
            fails.append(msg)

    print(f"OKR Drum camera recorder self-test, version {__version__}")
    # --- pure functions
    fts = [1000 * i for i in range(10)]
    mk = [{'message': 'T1 c=1', 'arrival_ns': 2500}, {'message': 'E1', 'arrival_ns': 6000}]
    m = match_markers_to_frames([dict(x) for x in mk], fts)
    check([x['frame'] for x in m] == [3, 6], 'markers matched to the next frame')
    check(trial_per_frame(m, fts) == ['', '', '', '1', '1', '1', '', '', '', ''], 'trial column per frame')
    c = sliders_to_controls(dict(DEFAULT_SLIDERS, **{'Auto exposure': 0, 'Exposure 0.1ms': 80, 'Gain x10': 40}))
    check(c['ExposureTime'] == 8000 and c['AnalogueGain'] == 4.0 and c['AeEnable'] is False,
          'sliders -> exposure 8 ms, gain 4x')

    # --- simulated camera: dark arena with a bright "mouse" moving around the centre
    W, H = SIZE

    class Req:
        def __init__(self, i, ts):
            self.i, self.ts = i, ts

        def make_array(self, name):
            yuv = np.full((H * 3 // 2, W), 60, np.uint8)
            cx = int(W / 2 + 80 * np.cos(self.i / 10)); cy = int(H / 2 + 80 * np.sin(self.i / 10))
            cv2.ellipse(yuv[:H], (cx, cy), (60, 30), self.i * 3 % 180, 0, 360, 200, -1)
            return yuv

        def get_metadata(self):
            return {'SensorTimestamp': self.ts, 'ExposureTime': 8000, 'AnalogueGain': 4.0}

        def release(self):
            pass

    class FakeCam:
        camera_controls = {}

        def __init__(self): self.i = 0
        def create_video_configuration(self, **k): return k
        def configure(self, c): pass
        def start(self): pass
        def stop(self): pass
        def set_controls(self, c): pass

        def capture_request(self):
            time.sleep(1.0 / FPS)
            self.i += 1
            return Req(self.i, now_ns())

    sys.modules['picamera2'] = types.SimpleNamespace(Picamera2=FakeCam)
    tmp = tempfile.mkdtemp(prefix='okr_pi_selftest_')
    OUTPUT_DIRECTORY = tmp
    SETTINGS_FILE = os.path.join(tmp, 'camera_settings.json')
    use_pty = hasattr(os, 'openpty')
    master = None
    if use_pty:
        master, slave = os.openpty()
        SERIAL_PORT = os.ttyname(slave)
    else:
        SERIAL_PORT = 'COM_SELFTEST_NONE'   # listener just warns; markers tested via handle()

    # GUI calls replaced by stand-ins (headless)
    sliders = {}
    keys = {'n': 0}
    shown = []

    def waitkey(_):
        keys['n'] += 1
        return ord('r') if keys['n'] == 5 else (27 if keys['n'] == 95 else 255)

    for name, fn in (('namedWindow', lambda *a, **k: None), ('destroyAllWindows', lambda: None),
                     ('imshow', lambda n, img: shown.append(img[5, 5].tolist())),
                     ('createTrackbar', lambda n, w, v, mx, cb: sliders.__setitem__(n, v)),
                     ('getTrackbarPos', lambda n, w: sliders[n]), ('waitKey', waitkey)):
        setattr(cv2, name, fn)
    answers = iter(['SELFTEST', 'none', 'okr'])
    builtins.input = lambda prompt='': next(answers)

    def sender():
        time.sleep(1.0)
        os.write(master, b'T1 c=1 w=5.000 v=12 CW\n'); time.sleep(0.6); os.write(master, b'E1\n')
        time.sleep(0.4)
        os.write(master, b'T2 c=0.5 w=2.500 v=12 CCW\n'); time.sleep(0.5); os.write(master, b'E2\n')

    if use_pty:
        threading.Thread(target=sender, daemon=True).start()
    main()

    files = sorted(os.listdir(tmp))
    video = [f for f in files if f.endswith(('_raw.mp4', '_raw.avi'))]
    check(len(video) == 1, 'video file written (%s)' % (video[0] if video else 'none'))
    if video:
        cap = cv2.VideoCapture(os.path.join(tmp, video[0]))
        nfr = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        ok, fr = cap.read()
        cap.release()
        check(ok and nfr > 50, 'video readable, %d frames' % nfr)
    frames = [f for f in files if f.endswith('_frames.csv')]
    rows = list(csv.DictReader(open(os.path.join(tmp, frames[0])))) if frames else []
    check(len(rows) > 50, 'frame timestamps saved (%d rows)' % len(rows))
    info = [f for f in files if f.endswith('_info.json')]
    check(bool(info) and json.load(open(os.path.join(tmp, info[0])))['app_version'] == __version__,
          'info.json records the app version')
    if use_pty:
        mk = list(csv.DictReader(open(os.path.join(tmp, [f for f in files if f.endswith('_markers.csv')][0]))))
        check([x['message'].split()[0] for x in mk] == ['T1', 'E1', 'T2', 'E2'], 'markers T1 E1 T2 E2 logged')
        check(all(x['frame'] != '' for x in mk), 'every marker matched to a video frame')
        tr = [r['trial'] for r in rows]
        check(tr.count('1') > 5 and tr.count('2') > 5, 'trial column filled during both gratings')
        check(any(px == [0, 0, 255] for px in shown), 'preview showed the red STIMULUS ON frame')
    else:
        lst = SerialListener()
        lst.recording = True
        lst.handle('T1 c=1', 100); lst.handle('E1', 200)
        check(len(lst.markers) == 2 and lst.last is not None, 'marker handling (no serial on this OS)')
    print('\nSELF-TEST %s (%d problem%s)' % ('PASSED' if not fails else 'FAILED', len(fails),
                                             '' if len(fails) == 1 else 's'))
    return 0 if not fails else 1


if __name__ == "__main__":
    if '--selftest' in sys.argv:
        sys.exit(selftest())
    if '--version' in sys.argv:
        print(__version__)
        sys.exit(0)
    main()

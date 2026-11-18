"""Self-test: runs every part of OKR Drum on synthetic data. Exit code 0 = all good.

    OKR-Drum --selftest selftest.txt        (the built app)
    python okr_drum.py --selftest out.txt   (from source)

OpenGL may be missing on build machines without a GPU; the shader check is then reported as
skipped and the CPU renderer is tested instead. Everything else must pass.
"""
from __future__ import annotations

import csv
import os
import platform
import sys
import tempfile
import time
import traceback

import numpy as np

from . import __version__


class Log:
    def __init__(self, path):
        self.path = path
        self.lines, self.fails, self.notes = [], [], []
        self.f = open(path, "w", encoding="utf-8")    # written line by line: a crash still leaves a report

    def w(self, s):
        self.lines.append(s)
        try:
            self.f.write(s + "\n")
            self.f.flush()
        except Exception:
            pass
        try:
            print(s, flush=True)
        except Exception:
            pass

    def check(self, cond, msg):
        self.w(("  ok    " if cond else "  FAIL  ") + msg)
        if not cond:
            self.fails.append(msg)

    def note(self, msg):
        self.w("  note  " + msg)
        self.notes.append(msg)

    def save(self):
        try:
            self.f.close()
        except Exception:
            pass
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("\n".join(self.lines) + "\n")


def _wait(app, cond, timeout):
    t0 = time.time()
    while not cond() and time.time() - t0 < timeout:
        app.processEvents()
        time.sleep(0.005)
    return cond()


def run(out_path="selftest.txt", gui=True):
    log = Log(os.path.abspath(out_path))
    log.w("OKR Drum self-test  version %s  python %s  %s %s" % (__version__, platform.python_version(),
                                                              platform.system(), platform.machine()))
    tmp = tempfile.mkdtemp(prefix="okr_selftest_")
    try:
        from PySide6 import QtCore, QtWidgets
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
        log.w("Qt platform: %s" % app.platformName())
        _geometry(log)
        _protocol(log)
        _renderer(log)
        _runner(log, app, tmp)
        s = _analysis(log, tmp)
        _calibration(log)
        _project(log, tmp, s)
        if gui:
            _gui(log, app, tmp)
    except Exception:
        log.check(False, "unexpected error:\n" + traceback.format_exc())
    log.w("")
    log.w("SELF-TEST %s (%d problem%s%s)" % ("PASSED" if not log.fails else "FAILED", len(log.fails),
                                            "" if len(log.fails) == 1 else "s",
                                            ", %d note(s)" % len(log.notes) if log.notes else ""))
    log.save()
    return 0 if not log.fails else 1


# ---------------------------------------------------------------------- parts
def _geometry(log):
    from .geometry import Rig, cycles_per_screen, ray_to_wall, wall_point_azimuth
    log.w("[geometry]")
    r = Rig()
    a0, a1 = r.span()
    log.check(abs(a0 + 42.68) < 0.05 and abs(a1 - 44.89) < 0.05, "screen spans %.2f to %.2f deg" % (a0, a1))
    log.check(abs(r.side_mismatch()) < 0.3, "default geometry closes the square")
    for w, n in ((5, 9), (2.5, 18), (1.25, 36)):
        log.check(cycles_per_screen(w) == (n, 45.0 / n), "bar %g deg -> %d cycles per screen" % (w, n))
    wall, s, t = ray_to_wall([0, 0, 0, 0], [0, 0, 0, 0], [0, 1, 0, -1], [1, 0, -1, 0], 21.35)
    az = wall_point_azimuth(wall, s, 21.35)
    log.check(list(wall) == [0, 1, 2, 3] and np.allclose(az, [0, 90, 180, 270]),
              "gaze straight at the four walls -> 0/90/180/270 deg")
    wall, s, t = ray_to_wall([0], [0], [np.sin(np.radians(30))], [np.cos(np.radians(30))], 21.35)
    log.check(abs(wall_point_azimuth(wall, s, 21.35)[0] - 30) < 1e-6, "gaze 30 deg clockwise -> azimuth 30 deg")


def _protocol(log):
    from . import protocol as P
    log.w("[protocol]")
    p = {"contrast": {"range": True, "start": 0.25, "end": 1, "step": 0.25},
         "speed": {"range": True, "start": 6, "end": 12, "step": 6}, "repeats": 2}
    tr = P.build_trials(p)
    log.check(len(tr) == 4 * 2 * 2 * 2, "ranges x directions x repeats = %d trials" % len(tr))
    log.check([t["contrast"] for t in tr[:4]] == [0.25] * 4, "ranges stepped in order")
    run = P.StaircaseRun({"mode": "staircase", "sc_reversals": 6, "sc_start": 0.05, "sc_step": 0.05}, seed=2)
    true_thr = {1: 0.42, -1: 0.30}
    n = 0
    while True:
        t = run.next_trial()
        if t is None:
            break
        run.respond(t["spatial_freq_cpd"] < true_thr[t["dir_sign"]])
        n += 1
    res = run.results()
    log.check(abs(res["CW"]["threshold"] - 0.42) < 0.05 and abs(res["CCW"]["threshold"] - 0.30) < 0.05,
              "staircase finds 0.42 / 0.30 c/deg: %.3f / %.3f (%d trials)" % (res["CW"]["threshold"],
                                                                             res["CCW"]["threshold"], n))


def _renderer(log):
    from .geometry import Rig
    from .protocol import build_trials
    from .renderer import StimState
    log.w("[renderer]")
    st = StimState(Rig())
    st.start_grating(build_trials({"bar_width": {"value": 2.5}})[0], t0=10.0)
    row = st.cpu_row(1024, now=11.0)
    log.check(row.min() == 0 and row.max() == 1, "CPU renderer draws a full-contrast grating")
    from .glprobe import probe
    res = probe()
    if not res.get("checks"):
        log.note("OpenGL not usable on this machine (%s): shader not checked; the app uses the CPU renderer "
                 "here" % res.get("reason"))
        return
    log.w("  OpenGL renderer: %s (tested in a separate process)" % res.get("name"))
    for ok, msg in res["checks"]:
        log.check(ok, msg)


def _runner(log, app, tmp):
    from .geometry import Rig
    from .runner import Runner
    from .sync import MarkerPort
    log.w("[run: two gratings with markers]")
    r = Runner()
    port = MarkerPort(None)
    done = []
    r.finished.connect(done.append)
    from PySide6 import QtCore
    t = QtCore.QTimer()
    t.timeout.connect(lambda: r.key("space"))
    t.start(100)
    r.start({"duration": 0.5, "iti": 0.1, "speed": {"range": True, "start": 6, "end": 12, "step": 6},
             "direction": "CW only"}, Rig(fullscreen=False, res_w=480, res_h=360), {"animal": "selftest"},
            os.path.join(tmp, "stim"), port=port)
    ok = _wait(app, lambda: bool(done), 30)
    t.stop()
    log.check(ok, "run finished")
    if not ok:
        r.stop("timeout")
        return
    rows = list(csv.DictReader(open(done[0], encoding="utf-8")))
    log.check(len(rows) == 2, "2 trials logged")
    log.check(all(float(x["shown_s"]) >= 0.45 and int(x["frames"]) >= 5 for x in rows),
              "each grating ran its duration (%s frames)" % ", ".join(x["frames"] for x in rows))
    labels = [m.split()[0] for m in port.sent]
    log.check(labels == ["S", "T1", "E1", "T2", "E2", "X"], "session info, markers T1 E1 T2 E2, run end sent")
    import json as _json
    info = _json.loads(port.sent[0][2:])
    log.check(info.get("animal") == "selftest" and info.get("stim_log", "").endswith(".csv"),
              "session info carries the animal and the stimulus log name")
    log.w("  renderer used: %s" % getattr(r.win, "renderer_name", "?"))


def _analysis(log, tmp):
    from .analysis import report, synthetic
    from .analysis.session import Session
    log.w("[analysis on a synthetic session]")
    syn = synthetic.make(os.path.join(tmp, "session"), video=True)
    s = Session(video=syn["video"], stim_csv=syn["stim_csv"], frames_csv=syn["frames_csv"],
                markers_csv=syn["markers_csv"], dlc_file=syn["dlc_file"], calibration=syn["calibration"]).run_all()
    log.check(set(s.mapping) == {"nose", "left_ear", "right_ear", "neck"}, "DLC bodyparts mapped automatically")
    sync = s.sync_report()
    log.check(all(lv != "problem" for lv, _ in sync), "sync check clean")
    truth = syn["truth"]["responded"]
    agree = sum(bool(r.tracked) == bool(truth[int(r.trial)]) for r in s.trials.itertuples())
    log.check(agree >= len(truth) - 1, "tracking detected correctly in %d/%d trials" % (agree, len(truth)))
    g = s.trials[s.trials["tracked"]]["slow_gain"].mean()
    log.check(0.45 < g < 0.9, "slow-phase gain of tracked trials %.2f (simulated 0.7)" % g)
    thr = s.thresholds
    log.check(0.3 <= thr.get("left_spatial_freq_cpd", 0) <= 0.55 and 0.25 <= thr.get("right_spatial_freq_cpd", 0) <= 0.5,
              "acuity thresholds %s" % {k: round(v, 3) for k, v in thr.items()})
    base = s.save()
    log.check(os.path.exists(base + "_trials.csv"), "results saved")
    import cv2
    out = s.overlay(os.path.join(tmp, "overlay.mp4"), 0, 120)
    cap = cv2.VideoCapture(out)
    nfr = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    ok, _ = cap.read()
    cap.release()
    log.check(ok and nfr >= 100, "overlay video written and readable (%s, %d frames)" % (os.path.basename(out), nfr))
    pdf = report.pdf_report(s, os.path.join(tmp, "report.pdf"), {"animal": "demo"}, sync)
    log.check(os.path.getsize(pdf) > 20000, "PDF report written")
    from .analysis import dlc_runner
    cmd = dlc_runner.command("python", "config.yaml", ["v.mp4"])
    log.check("analyze_videos" in cmd[3] and isinstance(dlc_runner.candidate_pythons(), list),
              "DeepLabCut command prepared")
    return s


def _calibration(log):
    import cv2
    from .analysis import calibration as cal
    log.w("[camera calibration on a synthetic wide-angle lens]")
    W, H = 800, 600
    K = np.array([[330, 0, 400], [0, 330, 300], [0, 0, 1.]])
    D = np.array([-0.30, 0.08, 0, 0, -0.01])
    cols, rows, sq = 9, 6, 10.0
    u, v = np.meshgrid(np.arange(W), np.arange(H))
    rays = cv2.undistortPoints(np.stack([u.ravel(), v.ravel()], 1).astype(float).reshape(-1, 1, 2), K, D)
    rays = np.c_[rays.reshape(-1, 2), np.ones(W * H)]

    def render(rvec, tvec):
        R, _ = cv2.Rodrigues(np.asarray(rvec, float))
        t = np.asarray(tvec, float)
        sc = (R[:, 2] @ t) / (rays @ R[:, 2])
        P = (rays * sc[:, None] - t) @ R
        X, Y = P[:, 0], P[:, 1]
        i, j = np.floor(X / sq), np.floor(Y / sq)
        board = (X >= 0) & (X < (cols + 1) * sq) & (Y >= 0) & (Y < (rows + 1) * sq)
        margin = (X >= -sq) & (X < (cols + 2) * sq) & (Y >= -sq) & (Y < (rows + 2) * sq)
        img = np.full(X.shape, 150, np.uint8)
        img[margin] = 255
        img[board] = np.where(((i + j) % 2 == 0)[board], 0, 255)
        return img.reshape(H, W)

    rng = np.random.default_rng(1)
    imgs = [render(rng.normal(0, 0.3, 3), [rng.uniform(-110, 10), rng.uniform(-70, 0), rng.uniform(130, 230)])
            for _ in range(16)]
    Kf, Df, rms, n, size = cal.calibrate_lens(imgs, cols, rows, sq)
    log.check(rms < 1.5 and n >= 12, "lens fitted from %d images, error %.2f px" % (n, rms))
    tv = np.array([-50., -35., 175.])
    Hm, err = cal.plane_from_board(render(np.zeros(3), tv), cols, rows, sq, Kf, Df)

    def proj(x, y):
        return cv2.projectPoints(np.array([[x, y, 0.]]), np.zeros(3), tv, K, D)[0].ravel()
    c = cal.new_calibration(size)
    c.update(K=Kf.tolist(), D=Df.tolist(), H=Hm.tolist(), centre_px=list(proj(50, 35)))
    pts = np.array([proj(50, 35), proj(70, 35), proj(50, 20), proj(80, 60)])
    cm = cal.to_cm(pts, c)
    exp = np.array([[0, 0], [2.0, 0], [0, 1.5], [3.0, -2.5]])
    e = float(np.max(np.hypot(*(cm - exp).T)))
    log.check(e < 0.05, "image points -> cm, worst error %.2f mm" % (10 * e))
    back = cal.from_cm(cm, c)
    log.check(float(np.max(np.hypot(*(back - pts).T))) < 0.5, "cm -> image points round trip")
    c2 = cal.new_calibration((640, 480))
    c2["px_per_cm"] = 20.0
    c2["rotation"] = cal.rotation_from_wall((100, 100), (300, 120))
    pts = cal.from_cm(np.array([[-5, 3], [5, 3]]), c2)
    log.check(abs(np.degrees(np.arctan2(-(pts[1, 1] - pts[0, 1]), pts[1, 0] - pts[0, 0])) -
                  np.degrees(np.arctan2(-20, 200))) < 0.01, "wall direction sets the rotation")
    ctr, ppc = cal.scale_from_circle([(320 + 50 * np.cos(a), 240 + 50 * np.sin(a)) for a in np.linspace(0, 6, 7)], 5.0)
    log.check(abs(ppc - 20) < 1e-6 and np.allclose(ctr, [320, 240]), "pedestal rim -> 20 px/cm and its centre")


def _project(log, tmp, s):
    from .luminance import fit_gamma
    from .project import Project
    log.w("[project database, luminance]")
    p = Project(os.path.join(tmp, "okr_project.json"))
    rec = p.add_session(animal="M1", treatment="saline", video=s.video, stim_csv=s.stim_csv)
    p.store_results(rec["id"], s, s.save())
    p.save()
    p2 = Project(os.path.join(tmp, "okr_project.json"))
    log.check(len(p2.sessions_table()) == 1 and len(p2.all_trials()) == len(s.trials),
              "project saved, reloaded, %d trials exported" % len(s.trials))
    v = np.array([0, .125, .25, .375, .5, .625, .75, .875, 1])
    r = fit_gamma(v, 0.4 + 110 * v ** 2.3)
    log.check(abs(r["gamma"] - 2.3) < 0.01, "gamma fitted from photometer readings (%.2f)" % r["gamma"])
    from .inbox import pair_sessions
    pairs = pair_sessions(os.path.dirname(s.stim_csv))
    log.check(len(pairs) == 1 and pairs[0]["stim_csv"] == s.stim_csv,
              "inbox pairs the Pi video with its stimulus log by time")


def _gui(log, app, tmp):
    log.w("[app window]")
    from .gui import widgets
    widgets.SETTINGS_DIR = os.path.join(tmp, "settings")
    widgets.SETTINGS_FILE = os.path.join(widgets.SETTINGS_DIR, "settings.json")
    from .gui import theme
    theme.apply_theme(app)
    from .gui.main import MainWindow
    w = MainWindow()
    w.resize(1300, 850)
    w.show()
    app.processEvents()
    for i in range(w.tabs.count()):
        w.tabs.setCurrentIndex(i)
        app.processEvents()
    log.check(w.tabs.count() == 5, "window with Stimulus, Rig, Analyze, Results, Project")
    w.stim_tab.pw["bar_width"]["chk"].setChecked(True)
    log.check("trials" in w.stim_tab.preview.text(), "protocol preview updates")
    a = w.analyze_tab
    syn_dir = os.path.join(tmp, "session")
    a.set_files(video=os.path.join(syn_dir, "rec_raw.mp4"), stim_csv=os.path.join(syn_dir, "stim.csv"),
                frames_csv=os.path.join(syn_dir, "rec_frames.csv"), markers_csv=os.path.join(syn_dir, "rec_markers.csv"),
                dlc_file=[os.path.join(syn_dir, f) for f in os.listdir(syn_dir) if "DLC" in f and f.endswith(".csv")][0],
                calibration=os.path.join(syn_dir, "calibration.json"))
    from PySide6 import QtWidgets
    orig = QtWidgets.QMessageBox.warning
    msgs = []
    QtWidgets.QMessageBox.warning = staticmethod(lambda *x, **k: msgs.append(x[2]))
    a.run()
    QtWidgets.QMessageBox.warning = orig
    log.check(a.s is not None and a.trials.rowCount() == 12, "analysis from the app: 12 trials%s" %
              (" (" + "; ".join(msgs) + ")" if msgs else ""))
    a.view.slider.setValue(200)
    app.processEvents()
    for k in range(w.results_tab.what.count() - 2):
        w.results_tab.what.setCurrentIndex(k)
        app.processEvents()
    log.check(len(w.results_tab.canvas.fig.axes) > 0, "response graphs drawn")
    w.project_tab.add_from_session(a.s)
    log.check(len(w.project_tab.project.data["sessions"]) == 1, "session added to the project")
    w.results_tab.what.setCurrentIndex(3)
    app.processEvents()
    w.open_calibration(os.path.join(syn_dir, "rec_raw.mp4"))
    app.processEvents()
    log.check(w._calib.frame is not None, "calibration tool opens the video")
    w._calib.close()
    w.close()
    app.processEvents()

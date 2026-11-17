"""Analyze tab: session files, DeepLabCut (in its own environment), head direction and gaze,
per-trial responses, overlay video, report."""
from __future__ import annotations

import os

import cv2
import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from ..analysis import calibration as calmod
from ..analysis import dlc_runner, okr, report, tracking
from ..analysis.session import Session
from . import theme
from .widgets import FileRow, LogView, MplCanvas, combo, form_spin, level_item, show_in_folder, table_from_df

ROLES = [("nose", "Nose"), ("left_ear", "Left ear"), ("right_ear", "Right ear"), ("neck", "Neck")]


class VideoView(QtWidgets.QWidget):
    """Video with keypoints and the gaze line drawn on top, frame slider and play."""
    frame_changed = QtCore.Signal(int)

    def __init__(self):
        super().__init__()
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.glw = pg.GraphicsLayoutWidget()
        self.glw.setBackground("#0b1224")
        self.vb = self.glw.addViewBox()
        self.vb.setAspectLocked(True)
        self.vb.invertY(True)
        self.img = pg.ImageItem(axisOrder="row-major")
        self.vb.addItem(self.img)
        self.pts = pg.ScatterPlotItem(size=11, pen=pg.mkPen("k", width=1))
        self.vb.addItem(self.pts)
        self.line = pg.PlotCurveItem(pen=pg.mkPen((255, 200, 40), width=3))
        self.vb.addItem(self.line)
        self.label = pg.TextItem("", color=(230, 236, 246), anchor=(0, 0))
        self.vb.addItem(self.label)
        v.addWidget(self.glw, 1)
        h = QtWidgets.QHBoxLayout()
        self.play = QtWidgets.QToolButton()
        self.play.setText("▶")
        self.play.clicked.connect(self.toggle)
        h.addWidget(self.play)
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.valueChanged.connect(self.seek)
        h.addWidget(self.slider, 1)
        self.tlab = QtWidgets.QLabel("–")
        self.tlab.setMinimumWidth(150)
        h.addWidget(self.tlab)
        v.addLayout(h)
        self.cap = None
        self.n = 0
        self.fps = 30.0
        self.session = None
        self.pos = -1
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(lambda: self.slider.setValue((self.slider.value() + 1) % max(self.n, 1)))

    def open(self, path):
        if self.cap:
            self.cap.release()
        self.cap = cv2.VideoCapture(path) if path and os.path.exists(path) else None
        if not self.cap or not self.cap.isOpened():
            self.cap, self.n = None, 0
            self.img.clear()
            return False
        self.n = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.slider.setRange(0, max(self.n - 1, 0))
        self.pos = -1
        self.seek(0)
        self.vb.autoRange()
        return True

    def toggle(self):
        if self.timer.isActive():
            self.timer.stop()
            self.play.setText("▶")
        elif self.cap:
            self.timer.start(int(1000 / self.fps))
            self.play.setText("⏸")

    def seek(self, i):
        if not self.cap:
            return
        if i != self.pos + 1:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, fr = self.cap.read()
        if not ok:
            return
        self.pos = i
        self.img.setImage(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB), autoLevels=False, levels=(0, 255))
        self.tlab.setText("%.2f s  ·  frame %d/%d" % (i / self.fps, i, self.n - 1))
        self._overlay(i)
        self.frame_changed.emit(i)

    def _overlay(self, i):
        s = self.session
        if s is None or not hasattr(s, "kin") or i >= len(s.kin):
            self.pts.setData([], [])
            self.line.setData([], [])
            self.label.setText("")
            return
        xs, ys, br = [], [], []
        cols = {"nose": (60, 220, 255), "left_ear": (80, 255, 120), "right_ear": (255, 140, 80), "neck": (220, 120, 255)}
        for role, xy in s.kp_px.items():
            if i < len(xy) and np.isfinite(xy[i]).all():
                xs.append(xy[i, 0])
                ys.append(xy[i, 1])
                br.append(pg.mkBrush(*cols.get(role, (255, 255, 255))))
        self.pts.setData(xs, ys, brush=br)
        k = s.kin.iloc[i]
        if np.isfinite(k["head_x"]) and np.isfinite(k["gaze_dist_cm"]):
            p0 = np.array([[k["head_x"], k["head_y"]]])
            p1 = p0 + k["gaze_dist_cm"] * np.array([[k["dir_x"], k["dir_y"]]])
            ab = calmod.from_cm(np.vstack([p0, p1]), s.cal)
            self.line.setData(ab[:, 0], ab[:, 1])
        else:
            self.line.setData([], [])
        txt = "head %.0f°  %+.1f°/s   gaze %.0f°" % (k["yaw_deg"] % 360 if np.isfinite(k["yaw_deg"]) else np.nan,
                                                     k["yaw_vel"], k["gaze_az"] % 360 if np.isfinite(k["gaze_az"]) else np.nan)
        pf = getattr(s, "per_frame", None)
        if pf is not None and i < len(pf) and np.isfinite(pf["trial"].iloc[i]):
            txt = "TRIAL %d  stimulus %+g°/s   " % (pf["trial"].iloc[i], pf["stim_speed_signed"].iloc[i]) + txt
        self.label.setText(txt)


class AnalyzeTab(QtWidgets.QWidget):
    analysed = QtCore.Signal(object)

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.s = None
        self.proc = None
        self._build()
        st = main.settings
        self.dlc_python.setEditText(st.get("dlc_python", ""))
        self.dlc_config.set(st.get("dlc_config", ""))

    # ------------------------------------------------------------------ UI
    def _build(self):
        split = QtWidgets.QSplitter()
        lay = QtWidgets.QHBoxLayout(self)
        lay.addWidget(split)
        leftw = QtWidgets.QWidget()
        left = QtWidgets.QVBoxLayout(leftw)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(leftw)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        split.addWidget(scroll)

        g = QtWidgets.QGroupBox("1  Session files")
        f = QtWidgets.QFormLayout(g)
        self.video = FileRow("Video (*.mp4 *.avi *.mov *.mkv);;All files (*)", placeholder="Pi recording *_raw.mp4")
        self.video.changed.connect(self._video_chosen)
        self.stim = FileRow("Stimulus log (*.csv)", placeholder="OKR Drum stimulus log (.csv)")
        self.frames = FileRow("Frame times (*_frames.csv);;CSV (*.csv)")
        self.markers = FileRow("Markers (*_markers.csv);;CSV (*.csv)")
        self.dlc = FileRow("DeepLabCut (*.h5 *.csv)")
        self.dlc.changed.connect(self._dlc_chosen)
        self.cal = FileRow("Calibration (*.json)")
        ch = QtWidgets.QHBoxLayout()
        ch.addWidget(self.cal, 1)
        ch.addWidget(theme.button("Calibrate…", slot=self._calibrate))
        f.addRow("Video", self.video)
        f.addRow("Stimulus log", self.stim)
        f.addRow("Frame times", self.frames)
        f.addRow("Markers", self.markers)
        f.addRow("DLC result", self.dlc)
        f.addRow("Calibration", ch)
        self.align = combo(["markers (from the Pi)", "clock (unix time)"])
        self.offset = form_spin(-3600, 3600, 0, 3, 0.01, "s")
        ah = QtWidgets.QHBoxLayout()
        ah.addWidget(self.align, 1)
        ah.addWidget(QtWidgets.QLabel("offset"))
        ah.addWidget(self.offset)
        f.addRow("Align trials by", ah)
        left.addWidget(g)

        g = QtWidgets.QGroupBox("2  DeepLabCut (runs in your DLC environment)")
        f = QtWidgets.QFormLayout(g)
        self.dlc_python = QtWidgets.QComboBox()
        self.dlc_python.setEditable(True)
        self.dlc_python.lineEdit().setPlaceholderText("python of the DeepLabCut conda env")
        ph = QtWidgets.QHBoxLayout()
        ph.addWidget(self.dlc_python, 1)
        ph.addWidget(theme.button("Find", slot=self._find_envs))
        ph.addWidget(theme.button("…", slot=self._browse_python))
        ph.addWidget(theme.button("Check", slot=self._check_env))
        self.dlc_config = FileRow("DLC project (config.yaml);;YAML (*.yaml)")
        self.dlc_filter = QtWidgets.QCheckBox("filter predictions")
        self.dlc_filter.setChecked(True)
        self.dlc_labeled = QtWidgets.QCheckBox("DLC labeled video too")
        oh = QtWidgets.QHBoxLayout()
        oh.addWidget(self.dlc_filter)
        oh.addWidget(self.dlc_labeled)
        oh.addStretch(1)
        f.addRow("Environment", ph)
        f.addRow("config.yaml", self.dlc_config)
        f.addRow("", oh)
        self.dlc_btn = theme.button("Analyze the video with DeepLabCut", "primary", self._run_dlc)
        f.addRow(self.dlc_btn)
        self.dlc_log = LogView()
        self.dlc_log.setMaximumHeight(130)
        f.addRow(self.dlc_log)
        left.addWidget(g)

        g = QtWidgets.QGroupBox("3  Keypoints and analysis settings")
        f = QtWidgets.QFormLayout(g)
        self.map = {}
        for role, lab in ROLES:
            c = QtWidgets.QComboBox()
            self.map[role] = c
            f.addRow(lab, c)
        self.lik = form_spin(0, 1, 0.6, 2, 0.05)
        self.crit = form_spin(0, 1, 0.3, 2, 0.05)
        self.lo = form_spin(0.05, 1, 0.25, 2, 0.05, "× speed")
        self.minep = form_spin(0.05, 5, 0.3, 2, 0.05, "s")
        self.win = form_spin(0.05, 1, 0.2, 2, 0.05, "s")
        f.addRow("Likelihood cut-off", self.lik)
        f.addRow("Velocity smoothing", self.win)
        f.addRow("'With stimulus' above", self.lo)
        f.addRow("Shortest tracking episode", self.minep)
        f.addRow("OKR index criterion", self.crit)
        left.addWidget(g)

        g = QtWidgets.QGroupBox("4  Analyse and export")
        gl = QtWidgets.QGridLayout(g)
        self.run_btn = theme.button("Run analysis", "primary", self.run)
        gl.addWidget(self.run_btn, 0, 0, 1, 2)
        gl.addWidget(theme.button("Sync check", slot=self.sync_check), 1, 0)
        gl.addWidget(theme.button("Overlay video…", slot=self.overlay), 1, 1)
        gl.addWidget(theme.button("Save results (CSV)", slot=self.save), 2, 0)
        gl.addWidget(theme.button("PDF report…", slot=self.pdf), 2, 1)
        gl.addWidget(theme.button("Add to project", "good", self.add_to_project), 3, 0)
        gl.addWidget(theme.button("Load demo session", slot=self.demo), 3, 1)
        self.prog = QtWidgets.QProgressBar()
        self.prog.setVisible(False)
        gl.addWidget(self.prog, 4, 0, 1, 2)
        left.addWidget(g)
        left.addStretch(1)

        self.right = QtWidgets.QTabWidget()
        self.view = VideoView()
        self.view.frame_changed.connect(self._frame_changed)
        vw = QtWidgets.QWidget()
        vv = QtWidgets.QVBoxLayout(vw)
        vv.addWidget(self.view, 3)
        self.mini = MplCanvas((8, 2))
        self.mini.toolbar.setVisible(False)
        vv.addWidget(self.mini, 1)
        self.right.addTab(vw, "Video")
        tw = QtWidgets.QWidget()
        tv = QtWidgets.QVBoxLayout(tw)
        self.trials = QtWidgets.QTableWidget()
        self.trials.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.trials.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.trials.itemSelectionChanged.connect(self._trial_selected)
        tv.addWidget(self.trials, 2)
        self.trial_plot = MplCanvas((8, 4.5))
        tv.addWidget(self.trial_plot, 3)
        self.right.addTab(tw, "Trials")
        self.sync_list = QtWidgets.QListWidget()
        self.right.addTab(self.sync_list, "Sync check")
        split.addWidget(self.right)
        split.setSizes([460, 900])

    # ------------------------------------------------------------------ files
    def _video_chosen(self, p):
        comp = okr.guess_companions(p)
        if comp["frames"]:
            self.frames.set(comp["frames"])
        if comp["markers"]:
            self.markers.set(comp["markers"])
        d = tracking.find_dlc_output(p)
        if d:
            self.dlc.set(d, emit=True)
        folder = os.path.dirname(p)
        if not self.cal.path():
            for c in ("calibration.json", "okr_calibration.json"):
                if os.path.exists(os.path.join(folder, c)):
                    self.cal.set(os.path.join(folder, c))
        if not self.cal.path() and self.main.settings.get("last_calibration"):
            self.cal.set(self.main.settings["last_calibration"])
        self.view.open(p)

    def _dlc_chosen(self, p):
        try:
            parts = tracking.bodyparts(tracking.read_dlc(p))
        except Exception as e:
            self.main.status("Cannot read %s: %s" % (os.path.basename(p), e))
            return
        auto = tracking.auto_map(parts)
        for role, c in self.map.items():
            c.clear()
            c.addItem("(none)", "")
            for bp in parts:
                c.addItem(bp, bp)
            i = c.findData(auto.get(role, ""))
            c.setCurrentIndex(max(i, 0))

    def set_files(self, **kw):
        for key, w in (("video", self.video), ("stim_csv", self.stim), ("frames_csv", self.frames),
                       ("markers_csv", self.markers), ("dlc_file", self.dlc), ("calibration", self.cal)):
            if kw.get(key):
                w.set(kw[key], emit=key in ("dlc_file",))
        if kw.get("video"):
            self.view.open(kw["video"])

    def _calibrate(self):
        self.main.open_calibration(self.video.path(), target=self.cal)

    # ------------------------------------------------------------------ DeepLabCut
    def _find_envs(self):
        cands = dlc_runner.candidate_pythons()
        cur = self.dlc_python.currentText()
        self.dlc_python.clear()
        self.dlc_python.addItems(cands)
        if cur:
            self.dlc_python.setEditText(cur)
        self.dlc_log.log("Found %d conda environment(s)%s" % (len(cands), ": " + ", ".join(
            os.path.basename(os.path.dirname(os.path.dirname(c)) if c.endswith("python") else os.path.dirname(c))
            for c in cands) if cands else ". Use … to pick the env's python by hand."))

    def _browse_python(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Python of the DeepLabCut environment",
                                                     os.path.expanduser("~"), "python*")
        if p:
            self.dlc_python.setEditText(p)

    def _check_env(self):
        py = self.dlc_python.currentText().strip()
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        ok, msg = dlc_runner.has_deeplabcut(py)
        QtWidgets.QApplication.restoreOverrideCursor()
        self.dlc_log.log(("✔ DeepLabCut %s found in %s" % (msg, py)) if ok else ("✖ No DeepLabCut in %s\n%s" % (py, msg)))

    def _run_dlc(self):
        py, cfg, vid = self.dlc_python.currentText().strip(), self.dlc_config.path(), self.video.path()
        if not (py and os.path.exists(py) and cfg and os.path.exists(cfg) and vid and os.path.exists(vid)):
            QtWidgets.QMessageBox.information(self, "DeepLabCut", "Choose the video, the DLC environment's python "
                                              "and the trained project's config.yaml first.")
            return
        self.main.settings.update(dlc_python=py, dlc_config=cfg)
        self.main.save_all()
        cmd = dlc_runner.command(py, cfg, [vid], os.path.dirname(vid), self.dlc_labeled.isChecked(),
                                 self.dlc_filter.isChecked())
        self.proc = QtCore.QProcess(self)
        self.proc.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(
            lambda: self.dlc_log.log(bytes(self.proc.readAllStandardOutput()).decode(errors="replace")))
        self.proc.finished.connect(self._dlc_done)
        self.dlc_btn.setEnabled(False)
        self.dlc_log.log("Running DeepLabCut on %s … (GPU recommended; this can take a while)" % os.path.basename(vid))
        self.proc.start(cmd[0], cmd[1:])

    def _dlc_done(self, code, status):
        self.dlc_btn.setEnabled(True)
        if code == 0:
            d = tracking.find_dlc_output(self.video.path())
            self.dlc_log.log("✔ DeepLabCut finished%s" % (": " + os.path.basename(d) if d else ""))
            if d:
                self.dlc.set(d, emit=True)
        else:
            self.dlc_log.log("✖ DeepLabCut stopped with exit code %d" % code)

    # ------------------------------------------------------------------ analysis
    def params(self):
        return {"likelihood": self.lik.value(), "index_criterion": self.crit.value(), "lo_frac": self.lo.value(),
                "min_episode_s": self.minep.value(), "deriv_window_s": self.win.value()}

    def build_session(self):
        mapping = {r: c.currentData() for r, c in self.map.items() if c.currentData()}
        s = Session(video=self.video.path() or None, stim_csv=self.stim.path(), frames_csv=self.frames.path() or None,
                    markers_csv=self.markers.path() or None, dlc_file=self.dlc.path(),
                    calibration=self.cal.path() or None, rig=self.main.rig(), params=self.params(), mapping=mapping,
                    align="markers" if self.align.currentIndex() == 0 else "clock", offset_s=self.offset.value())
        return s

    def run(self):
        if not self.stim.path() or not self.dlc.path():
            QtWidgets.QMessageBox.information(self, "Analysis", "Choose at least the stimulus log and the "
                                              "DeepLabCut result (and a calibration).")
            return
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            s = self.build_session().load()
            self._show_sync(s.sync_report())
            s.track().analyse()
        except Exception as e:
            QtWidgets.QApplication.restoreOverrideCursor()
            QtWidgets.QMessageBox.warning(self, "Analysis", str(e))
            return
        QtWidgets.QApplication.restoreOverrideCursor()
        self.s = s
        self.view.session = s
        if self.video.path():
            self.view.seek(self.view.slider.value())
        cols = ["trial", "spatial_freq_cpd", "contrast", "speed_deg_s", "direction", "okr_index", "slow_gain",
                "episodes", "episode_s", "tracked", "base_index", "head_offset_cm", "operator_response", "note"]
        table_from_df(self.trials, s.trials[[c for c in cols if c in s.trials]])
        self.mini.draw(self._mini_plot)
        th = ", ".join("%s %.3f" % (k.replace("_", " "), v) for k, v in s.thresholds.items() if np.isfinite(v))
        self.main.status("Analysed %d trials, tracking in %d. %s" % (len(s.trials), int(s.trials["tracked"].sum()),
                                                                    ("Thresholds: " + th) if th else ""))
        if len(s.trials):
            self.trials.selectRow(0)
        self.analysed.emit(s)

    def _mini_plot(self, fig):
        s = self.s
        ax = fig.add_subplot(111)
        pf = s.per_frame
        ax.plot(pf["t_s"], pf["yaw_vel"], color=theme.NAVY, lw=0.6)
        ax.plot(pf["t_s"], pf["stim_speed_signed"], color=theme.GOLD, lw=1.2)
        ax.set_ylim(-60, 60)
        ax.set_ylabel("deg/s", fontsize=8)
        ax.tick_params(labelsize=7)
        ax.spines[["top", "right"]].set_visible(False)
        self._cursor = ax.axvline(0, color=theme.BAD, lw=1)
        fig.tight_layout()

    def _frame_changed(self, i):
        if self.s is not None and hasattr(self, "_cursor") and i < len(self.s.per_frame):
            self._cursor.set_xdata([self.s.per_frame["t_s"].iloc[i]] * 2)
            self.mini.canvas.draw_idle()

    def _trial_selected(self):
        r = self.trials.currentRow()
        if self.s is None or r < 0:
            return
        t = int(float(self.trials.item(r, 0).text()))
        self.trial_plot.draw(report.trial_figure, self.s, t)
        w = next((w for w in self.s.windows if w[0] == t), None)
        if w and self.view.cap:
            self.view.slider.setValue(w[1])

    def _show_sync(self, res):
        self.sync_list.clear()
        for lv, msg in res:
            self.sync_list.addItem(level_item(lv, msg))

    def sync_check(self):
        try:
            s = self.build_session().load()
            self._show_sync(s.sync_report())
            self.right.setCurrentIndex(2)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Sync check", str(e))

    def _need(self):
        if self.s is None:
            QtWidgets.QMessageBox.information(self, "OKR Drum", "Run the analysis first.")
            return False
        return True

    def save(self):
        if self._need():
            base = self.s.save()
            self.main.status("Saved %s_trials.csv, _summary.csv, _frames.csv" % base)
            show_in_folder(base + "_trials.csv")

    def pdf(self):
        if not self._need():
            return
        default = os.path.splitext(self.s.video or self.s.stim_csv)[0].replace("_raw", "") + "_okr_report.pdf"
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self, "PDF report", default, "PDF (*.pdf)")
        if p:
            report.pdf_report(self.s, p, self.main.current_meta(), self.s.sync_report())
            show_in_folder(p)

    def overlay(self):
        if not self._need() or not self.s.video:
            return
        default = os.path.splitext(self.s.video)[0].replace("_raw", "") + "_okr_overlay.mp4"
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Overlay video", default, "Video (*.mp4 *.avi)")
        if not p:
            return
        self.prog.setVisible(True)

        def prog(i, n):
            self.prog.setMaximum(n)
            self.prog.setValue(i)
            QtWidgets.QApplication.processEvents()
        try:
            out = self.s.overlay(p, progress=prog)
            self.main.status("Wrote %s" % out)
            show_in_folder(out)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Overlay video", str(e))
        self.prog.setVisible(False)

    def add_to_project(self):
        if not self._need():
            return
        self.main.project_tab.add_from_session(self.s)

    def demo(self):
        """A synthetic session (known answer) to try the analysis without a rig."""
        import tempfile
        from ..analysis import synthetic
        d = os.path.join(tempfile.gettempdir(), "okr_drum_demo")
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        syn = synthetic.make(d, video=True)
        QtWidgets.QApplication.restoreOverrideCursor()
        self.set_files(video=syn["video"], stim_csv=syn["stim_csv"], frames_csv=syn["frames_csv"],
                       markers_csv=syn["markers_csv"], dlc_file=syn["dlc_file"], calibration=syn["calibration"])
        self.run()

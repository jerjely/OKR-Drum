"""OKR Drum recorder window (Raspberry Pi)."""
from __future__ import annotations

import os
import sys
import time

import numpy as np

from . import __version__
from .core import Recorder, draw_preview, load_config, now_ns, save_config, slider_max
from .qt import API, QtCore, QtGui, QtWidgets
from .uploader import Uploader, list_remotes, rclone_path

NAVY, ACCENT, BAD, OK = "#101d3d", "#1f9fd6", "#c8463f", "#2e9e6a"
STYLE = """
QMainWindow, QWidget#root { background: #eef2f7; }
QGroupBox { background: white; border: 1px solid #d8dfe9; border-radius: 8px; margin-top: 14px;
            padding: 10px 8px 8px 8px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #24386a; }
QPushButton { background: white; border: 1px solid #c9d3e0; border-radius: 6px; padding: 6px 12px; }
QPushButton:hover { border-color: #1f9fd6; }
QLineEdit { background: white; border: 1px solid #c9d3e0; border-radius: 5px; padding: 3px 6px; }
QFrame#header { background: #101d3d; }
QFrame#header QLabel { color: #e8eef6; }
QStatusBar { background: white; border-top: 1px solid #d8dfe9; }
"""


def E(cls, scope, name):
    """Enum member that works in PyQt5 (unscoped) and PyQt6 / PySide6 (scoped)."""
    sc = getattr(cls, scope, None)
    if sc is not None and hasattr(sc, name):
        return getattr(sc, name)
    return getattr(cls, name)


def resource(name):
    for d in (os.path.dirname(os.path.abspath(__file__)), "/usr/share/okr-recorder",
              os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "assets", "icon")):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


def qimage_from_bgr(img):
    h, w = img.shape[:2]
    rgb = np.ascontiguousarray(img[:, :, ::-1])
    fmt = E(QtGui.QImage, "Format", "Format_RGB888") if hasattr(QtGui.QImage, "Format") else QtGui.QImage.Format_RGB888
    return QtGui.QImage(rgb.data, w, h, 3 * w, fmt).copy()


class RecorderWindow(QtWidgets.QMainWindow):
    def __init__(self, recorder=None, config=None):
        super().__init__()
        self.cfg = config or load_config()
        self.setWindowTitle("OKR Drum recorder %s" % __version__)
        avail = QtWidgets.QApplication.primaryScreen().availableGeometry() \
            if QtWidgets.QApplication.primaryScreen() else QtCore.QRect(0, 0, 1280, 800)
        self.resize(min(1280, avail.width()), min(800, avail.height()))
        self.setMinimumSize(640, 400)
        icon = resource("okr_drum_256.png") or resource("okr-recorder.png")
        if icon:
            self.setWindowIcon(QtGui.QIcon(icon))
        self.rec = recorder or Recorder(self.cfg)
        self.uploader = None
        self._build()
        self._start_uploader()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(66)

    # ------------------------------------------------------------------ UI
    def _build(self):
        root = QtWidgets.QWidget()
        root.setObjectName("root")
        v = QtWidgets.QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        head = QtWidgets.QFrame()
        head.setObjectName("header")
        head.setFixedHeight(50)
        hh = QtWidgets.QHBoxLayout(head)
        logo = QtWidgets.QLabel()
        icon = resource("okr_drum_256.png") or resource("okr-recorder.png")
        if icon:
            logo.setPixmap(QtGui.QPixmap(icon).scaled(34, 34, E(QtCore.Qt, "AspectRatioMode", "KeepAspectRatio"),
                                                     E(QtCore.Qt, "TransformationMode", "SmoothTransformation")))
        hh.addWidget(logo)
        hh.addWidget(QtWidgets.QLabel("<b style='font-size:16px'>OKR Drum recorder</b>"))
        self.head_info = QtWidgets.QLabel("")
        self.head_info.setStyleSheet("color:#9fb3cc")
        hh.addWidget(self.head_info, 1)
        v.addWidget(head)
        body = QtWidgets.QHBoxLayout()
        body.setContentsMargins(10, 8, 10, 8)
        v.addLayout(body, 1)
        self.preview = QtWidgets.QLabel("starting camera…")
        self.preview.setAlignment(E(QtCore.Qt, "AlignmentFlag", "AlignCenter"))
        self.preview.setMinimumSize(200, 150)
        self.preview.setStyleSheet("background:#0b1224; color:#9fb3cc; border-radius:8px")
        self.preview.setSizePolicy(E(QtWidgets.QSizePolicy, "Policy", "Ignored"), E(QtWidgets.QSizePolicy, "Policy", "Ignored"))
        body.addWidget(self.preview, 3)
        # side panel scrolls, so the window fits small Pi screens (e.g. 1024 x 600)
        side_w = QtWidgets.QWidget()
        side_w.setObjectName("root")
        side = QtWidgets.QVBoxLayout(side_w)
        side.setContentsMargins(0, 0, 6, 0)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidget(side_w)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(E(QtWidgets.QFrame, "Shape", "NoFrame"))
        scroll.setHorizontalScrollBarPolicy(E(QtCore.Qt, "ScrollBarPolicy", "ScrollBarAlwaysOff"))
        scroll.setMinimumWidth(300)
        scroll.setMaximumWidth(400)
        body.addWidget(scroll, 1)

        g = QtWidgets.QGroupBox("Session")
        f = QtWidgets.QFormLayout(g)
        self.mouse = QtWidgets.QLineEdit(self.cfg.get("last_mouse", ""))
        self.treat = QtWidgets.QLineEdit(self.cfg.get("last_treatment", ""))
        self.exp = QtWidgets.QLineEdit(self.cfg.get("last_experiment", "okr"))
        f.addRow("Mouse", self.mouse)
        f.addRow("Treatment", self.treat)
        f.addRow("Experiment", self.exp)
        oh = QtWidgets.QHBoxLayout()
        self.out = QtWidgets.QLineEdit(self.cfg["output_dir"])
        b = QtWidgets.QPushButton("…")
        b.clicked.connect(self._choose_out)
        oh.addWidget(self.out, 1)
        oh.addWidget(b)
        f.addRow("Save in", oh)
        self.auto = QtWidgets.QCheckBox("record with the lab PC's run")
        self.auto.setChecked(bool(self.cfg.get("auto_record")))
        self.auto.toggled.connect(lambda on: (self.cfg.update(auto_record=on), save_config(self.cfg)))
        f.addRow(self.auto)
        side.addWidget(g)
        self._seen_session = self.rec.listener.session_seq
        self._seen_end = self.rec.listener.run_end_seq

        self.rec_btn = QtWidgets.QPushButton("●  Start recording  (R)")
        self.rec_btn.setMinimumHeight(48)
        self.rec_btn.clicked.connect(self.toggle)
        self._style_rec(False)
        side.addWidget(self.rec_btn)

        g = QtWidgets.QGroupBox("Stimulus from the lab PC")
        gv = QtWidgets.QVBoxLayout(g)
        self.stim_lbl = QtWidgets.QLabel("waiting for markers")
        self.stim_lbl.setWordWrap(True)
        self.stim_lbl.setMinimumHeight(48)
        gv.addWidget(self.stim_lbl)
        self.marker_list = QtWidgets.QListWidget()
        self.marker_list.setMaximumHeight(90)
        gv.addWidget(self.marker_list)
        side.addWidget(g)

        g = QtWidgets.QGroupBox("Image")
        f = QtWidgets.QFormLayout(g)
        self.sl = {}
        mx = slider_max(self.rec.fps)
        for name, val in self.rec.sliders.items():
            if name == "Focus x10" and not self.rec.has_focus:
                continue
            s = QtWidgets.QSlider(E(QtCore.Qt, "Orientation", "Horizontal"))
            s.setRange(0, mx[name])
            s.setValue(min(int(val), mx[name]))
            lab = QtWidgets.QLabel(str(s.value()))
            lab.setMinimumWidth(30)
            s.valueChanged.connect(lambda val, l=lab: (l.setText(str(val)), self._sliders()))
            row = QtWidgets.QHBoxLayout()
            row.addWidget(s, 1)
            row.addWidget(lab)
            f.addRow(name, row)
            self.sl[name] = s
        side.addWidget(g)

        g = QtWidgets.QGroupBox("Upload to the cloud (rclone)")
        f = QtWidgets.QFormLayout(g)
        self.up_on = QtWidgets.QCheckBox("upload when recording stops")
        self.up_on.setChecked(bool(self.cfg["upload"]))
        self.up_on.toggled.connect(self._upload_settings)
        self.remote = QtWidgets.QComboBox()
        self.remote.setEditable(True)
        self.remote.addItems([r + "OKR Drum/recordings" for r in list_remotes()])
        self.remote.setEditText(self.cfg["rclone_remote"])
        self.remote.lineEdit().editingFinished.connect(self._upload_settings)
        self.up_del = QtWidgets.QCheckBox("delete Pi copy after upload")
        self.up_del.setChecked(bool(self.cfg["upload_delete_local"]))
        self.up_del.toggled.connect(self._upload_settings)
        self.up_lbl = QtWidgets.QLabel("")
        self.up_lbl.setWordWrap(True)
        f.addRow(self.up_on)
        f.addRow("Destination", self.remote)
        f.addRow(self.up_del)
        f.addRow(self.up_lbl)
        side.addWidget(g)
        side.addStretch(1)
        self.setCentralWidget(root)
        self.statusBar().showMessage("Qt %s · serial %s" % (
            API, ("listening on %s" % self.rec.listener.port) if self.rec.listener.ok
            else "not available (%s)" % self.rec.listener.error))
        for key, fn in (("R", self.toggle), ("Esc", self._esc), ("Q", self.close)):
            sc = QtWidgets.QShortcut(QtGui.QKeySequence(key), self) if hasattr(QtWidgets, "QShortcut") else \
                QtGui.QShortcut(QtGui.QKeySequence(key), self)
            sc.activated.connect(fn)

    def _style_rec(self, on):
        col = BAD if on else OK
        self.rec_btn.setText("■  Stop recording  (R)" if on else "●  Start recording  (R)")
        self.rec_btn.setStyleSheet("QPushButton { background:%s; color:white; font-size:16px; font-weight:700;"
                                   " border:none; border-radius:8px }" % col)

    def _choose_out(self):
        p = QtWidgets.QFileDialog.getExistingDirectory(self, "Save recordings in", self.out.text())
        if p:
            self.out.setText(p)

    def _sliders(self):
        v = dict(self.rec.sliders)
        v.update({k: s.value() for k, s in self.sl.items()})
        self.rec.set_sliders(v)
        self.cfg["sliders"] = v
        if self.rec.recording:
            self.statusBar().showMessage("note: image settings changed during the recording", 8000)

    # ------------------------------------------------------------------ upload
    def _upload_settings(self, *_):
        self.cfg.update(upload=self.up_on.isChecked(), rclone_remote=self.remote.currentText().strip(),
                        upload_delete_local=self.up_del.isChecked())
        save_config(self.cfg)
        self._start_uploader()

    def _start_uploader(self):
        if self.uploader:
            self.uploader.close()
            self.uploader = None
        if not self.cfg["upload"]:
            self.up_lbl.setText("off")
            return
        if not rclone_path():
            self.up_lbl.setText("<span style='color:%s'>rclone is not installed: sudo apt install rclone, then "
                                "rclone config (remote name gdrive, type drive)</span>" % BAD)
            return
        self.uploader = Uploader(self.cfg["rclone_remote"], self.cfg["upload_delete_local"])
        self.uploader.start()

    # ------------------------------------------------------------------ recording
    def toggle(self):
        if self.rec.recording:
            files, summ = self.rec.stop()
            self._style_rec(False)
            msg = "Saved %d frames (%s fps, %s gaps), %d gratings" % (
                summ.get("frames", 0), summ.get("fps", "?"), summ.get("gaps", "?"), summ.get("gratings", 0))
            if self.uploader:
                self.uploader.add(files)
                msg += " - queued for upload"
            self.statusBar().showMessage(msg, 20000)
        else:
            self.cfg.update(output_dir=self.out.text().strip(), last_mouse=self.mouse.text().strip(),
                            last_treatment=self.treat.text().strip(), last_experiment=self.exp.text().strip())
            self.rec.cfg["output_dir"] = self.cfg["output_dir"]
            save_config(self.cfg)
            try:
                path = self.rec.start(self.mouse.text().strip(), self.treat.text().strip(), self.exp.text().strip())
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Recording", str(e))
                return
            self._style_rec(True)
            self.statusBar().showMessage("Recording to %s" % path)

    def _esc(self):
        if self.rec.recording:
            self.toggle()

    def _session_messages(self):
        L = self.rec.listener
        if L.session_seq != self._seen_session:
            self._seen_session = L.session_seq
            info = dict(L.session_info)
            if not self.rec.recording:
                if info.get("animal"):
                    self.mouse.setText(str(info["animal"]))
                self.treat.setText(str(info.get("treatment", "")))
                if info.get("session"):
                    self.exp.setText("okr_s%s" % info["session"])
            self.statusBar().showMessage("Session info from the lab PC: %s" % ", ".join(
                "%s %s" % (k, v) for k, v in info.items() if k in ("animal", "treatment", "session", "date")), 15000)
            # auto-record only when a run starts; "Send session info" just fills in the fields
            # (older PC versions: a run start is the message that names a stimulus log)
            run_start = info.get("run_start", bool(info.get("stim_log")))
            if run_start and self.auto.isChecked() and not self.rec.recording:
                self.toggle()
        if L.run_end_seq != self._seen_end:
            self._seen_end = L.run_end_seq
            if self.auto.isChecked() and self.rec.recording:
                QtCore.QTimer.singleShot(1500, lambda: self.rec.recording and self.toggle())

    def _tick(self):
        self._session_messages()
        with self.rec.lock:
            g, md = self.rec.latest, dict(self.rec.md)
        stim, last = self.rec.listener.state()
        if g is not None:
            img = draw_preview(g, md, self.rec.sharp, self.rec.recording, stim, last, self.rec.listener.ok)
            pix = QtGui.QPixmap.fromImage(qimage_from_bgr(img))
            self.preview.setPixmap(pix.scaled(self.preview.size(), E(QtCore.Qt, "AspectRatioMode", "KeepAspectRatio"),
                                              E(QtCore.Qt, "TransformationMode", "SmoothTransformation")))
        if stim is not None:
            self.stim_lbl.setText("<span style='color:%s; font-size:15px; font-weight:700'>● STIMULUS ON</span> "
                                  "trial %s - %.1f s<br>%s" % (BAD, stim[0], (now_ns() - stim[2]) / 1e9, stim[1]))
        elif last is not None:
            self.stim_lbl.setText("grey · last: %s (%.1f s)" % last)
        rec = self.rec.listener.recent
        if self.marker_list.count() != len(rec):
            self.marker_list.clear()
            for t, m in reversed(rec):
                self.marker_list.addItem("%s  %s" % (t, m))
        dur = time.time() - self.rec.t_start if self.rec.recording else 0
        self.head_info.setText("%s   %s" % (
            ("● REC %d:%02d" % (dur // 60, dur % 60)) if self.rec.recording else "ready",
            ("camera error: " + self.rec.error) if self.rec.error else ""))
        if self.uploader:
            n = self.uploader.pending()
            self.up_lbl.setText("%s · %d file(s) waiting · %d uploaded" % (self.uploader.status, n,
                                                                          len(self.uploader.done)))

    def closeEvent(self, ev):
        if self.rec.recording:
            if QtWidgets.QMessageBox.question(self, "Quit", "Stop the recording and quit?") != \
                    E(QtWidgets.QMessageBox, "StandardButton", "Yes"):
                ev.ignore()
                return
            self.toggle()
        save_config(self.cfg)
        self.timer.stop()
        self.rec.close()
        if self.uploader:
            self.uploader.close()
        super().closeEvent(ev)


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    if "--version" in argv:
        print(__version__)
        return 0
    if "--selftest" in argv:
        from .selftest import run
        return run()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    try:
        w = RecorderWindow()
    except Exception as e:
        QtWidgets.QMessageBox.critical(None, "OKR Drum recorder", "Cannot start the camera:\n%s" % e)
        return 1
    w.showMaximized()
    return app.exec() if hasattr(app, "exec") else app.exec_()

"""Camera calibration tool: lens distortion, scale at pedestal height, centre and orientation.

Workflow (on a frame of the Pi video, or a photo taken with the same camera settings):
  A. optional - lens: 20-30 checkerboard photos (or a video moving the board) -> distortion
  B. scale + centre: click >= 3 points on the pedestal rim (known diameter, 5 cm),
     or use a checkerboard lying on the pedestal for a full perspective correction
  C. orientation: click 2 points along one arena wall / screen edge -> the walls become axis-aligned
  Check: the arena square and a 1 cm grid are drawn back onto the image.
"""
from __future__ import annotations

import os

import cv2
import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from ..analysis import calibration as calmod
from . import theme
from .widgets import form_spin

IMG_EXT = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp")


class CalibrationTool(QtWidgets.QDialog):
    def __init__(self, main, video=None, target=None):
        super().__init__(main)
        self.main, self.target = main, target
        self.setWindowTitle("OKR Drum - camera calibration")
        self.resize(1400, 860)
        self.cap, self.frame, self.n = None, None, 1
        self.cal = None
        self.points = {"rim": [], "wall": []}
        self.rig = main.rig()
        self._build()
        if video:
            self.open_source(video)

    # ------------------------------------------------------------------ UI
    def _build(self):
        h = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QVBoxLayout()
        self.glw = pg.GraphicsLayoutWidget()
        self.glw.setBackground("#0b1224")
        self.vb = self.glw.addViewBox()
        self.vb.setAspectLocked(True)
        self.vb.invertY(True)
        self.vb.setMenuEnabled(False)
        self.img = pg.ImageItem(axisOrder="row-major")
        self.vb.addItem(self.img)
        self.rim_items = pg.ScatterPlotItem(symbol="+", size=14, pen=pg.mkPen((255, 80, 80), width=2))
        self.wall_items = pg.ScatterPlotItem(symbol="x", size=14, pen=pg.mkPen((80, 220, 255), width=2))
        self.circle = QtWidgets.QGraphicsEllipseItem()
        self.circle.setPen(pg.mkPen((0, 255, 0), width=2, cosmetic=True))
        self.circle.setVisible(False)
        self.arena = pg.PlotCurveItem(pen=pg.mkPen((255, 200, 40), width=2))
        self.grid = pg.PlotCurveItem(pen=pg.mkPen((255, 255, 255, 70), width=1), connect="pairs")
        for it in (self.grid, self.arena, self.circle, self.rim_items, self.wall_items):
            self.vb.addItem(it)
        self.glw.scene().sigMouseClicked.connect(self._clicked)
        self.glw.scene().sigMouseMoved.connect(self._moved)
        left.addWidget(self.glw, 1)
        th = QtWidgets.QHBoxLayout()
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.valueChanged.connect(self._seek)
        th.addWidget(self.slider, 1)
        self.pos_lbl = QtWidgets.QLabel("–")
        self.pos_lbl.setMinimumWidth(260)
        th.addWidget(self.pos_lbl)
        left.addLayout(th)
        h.addLayout(left, 3)

        right = QtWidgets.QVBoxLayout()
        right.addWidget(theme.button("Open video / photo…", slot=self._choose))
        self.src_lbl = QtWidgets.QLabel("no image")
        self.src_lbl.setProperty("muted", True)
        right.addWidget(self.src_lbl)

        g = QtWidgets.QGroupBox("A  Lens distortion (optional, recommended for wide lenses)")
        f = QtWidgets.QFormLayout(g)
        self.cols = form_spin(3, 30, 9, 0)
        self.rows = form_spin(3, 30, 6, 0)
        self.sq = form_spin(1, 200, 10, 1, 0.5, "mm")
        bh = QtWidgets.QHBoxLayout()
        bh.addWidget(self.cols)
        bh.addWidget(QtWidgets.QLabel("×"))
        bh.addWidget(self.rows)
        f.addRow("Inner corners", bh)
        f.addRow("Square size", self.sq)
        lh = QtWidgets.QHBoxLayout()
        lh.addWidget(theme.button("From photos…", slot=lambda: self._lens(False)))
        lh.addWidget(theme.button("From a video…", slot=lambda: self._lens(True)))
        f.addRow(lh)
        self.lens_lbl = QtWidgets.QLabel("no lens correction")
        self.lens_lbl.setWordWrap(True)
        f.addRow(self.lens_lbl)
        right.addWidget(g)

        g = QtWidgets.QGroupBox("B  Scale and centre at pedestal height")
        f = QtWidgets.QFormLayout(g)
        self.mode_rim = QtWidgets.QRadioButton("click the pedestal rim (≥ 3 points)")
        self.mode_wall = QtWidgets.QRadioButton("click 2 points along an arena wall (C)")
        self.mode_rim.setChecked(True)
        self.diam = form_spin(0.5, 50, 5.0, 2, 0.1, "cm")
        f.addRow(self.mode_rim)
        f.addRow("Pedestal diameter", self.diam)
        f.addRow(theme.button("…or use a checkerboard lying on the pedestal (this frame)", slot=self._plane))
        self.scale_lbl = QtWidgets.QLabel("")
        self.scale_lbl.setWordWrap(True)
        f.addRow(self.scale_lbl)
        right.addWidget(g)

        g = QtWidgets.QGroupBox("C  Orientation")
        f = QtWidgets.QFormLayout(g)
        f.addRow(self.mode_wall)
        self.rot = form_spin(-180, 180, 0, 2, 0.5, "deg")
        self.rot.valueChanged.connect(self._apply)
        self.mirror = QtWidgets.QCheckBox("image is mirrored")
        self.mirror.toggled.connect(self._apply)
        f.addRow("Rotation", self.rot)
        f.addRow("", self.mirror)
        right.addWidget(g)

        h2 = QtWidgets.QHBoxLayout()
        h2.addWidget(theme.button("Undo point", slot=self._undo))
        h2.addWidget(theme.button("Clear points", slot=self._clear))
        right.addLayout(h2)
        self.check_lbl = QtWidgets.QLabel("Yellow square = the drum walls, white grid = 1 cm at pedestal height.")
        self.check_lbl.setWordWrap(True)
        self.check_lbl.setProperty("muted", True)
        right.addWidget(self.check_lbl)
        right.addStretch(1)
        h3 = QtWidgets.QHBoxLayout()
        h3.addWidget(theme.button("Load…", slot=self._load))
        self.save_btn = theme.button("Save calibration", "primary", self._save)
        h3.addWidget(self.save_btn)
        h3.addWidget(theme.button("Close", slot=self.accept))
        right.addLayout(h3)
        w = QtWidgets.QWidget()
        w.setLayout(right)
        w.setMaximumWidth(460)
        h.addWidget(w, 1)
        QtGui.QShortcut(QtGui.QKeySequence("Backspace"), self, self._undo)

    # ------------------------------------------------------------------ source
    def _choose(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Video or photo from the drum camera", "",
                                                     "Video / image (*.mp4 *.avi *.mov *.jpg *.jpeg *.png *.tif);;All (*)")
        if p:
            self.open_source(p)

    def open_source(self, p):
        self.path = p
        if self.cap:
            self.cap.release()
            self.cap = None
        if p.lower().endswith(IMG_EXT):
            self.frame = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)
            self.n = 1
        else:
            self.cap = cv2.VideoCapture(p)
            self.n = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
            ok, self.frame = self.cap.read()
        if self.frame is None:
            QtWidgets.QMessageBox.warning(self, "Calibration", "Cannot read %s" % p)
            return
        h, w = self.frame.shape[:2]
        self.src_lbl.setText("%s  -  %d×%d, %d frame(s)" % (os.path.basename(p), w, h, self.n))
        self.slider.setRange(0, self.n - 1)
        if self.cal is None or tuple(self.cal["size"]) != (w, h):
            self.cal = calmod.new_calibration((w, h))
            existing = os.path.join(os.path.dirname(p), "calibration.json")
            if os.path.exists(existing):
                try:
                    c = calmod.load(existing)
                    if tuple(c["size"]) == (w, h):
                        self.cal = c
                        self.scale_lbl.setText("Loaded %s" % existing)
                except Exception:
                    pass
        self._show()
        self.vb.autoRange()
        self._apply()

    def _seek(self, i):
        if self.cap:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ok, fr = self.cap.read()
            if ok:
                self.frame = fr
                self._show()

    def _show(self):
        self.img.setImage(cv2.cvtColor(self.frame, cv2.COLOR_BGR2RGB), autoLevels=False, levels=(0, 255))

    # ------------------------------------------------------------------ steps
    def _lens(self, video):
        if video:
            p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Video of the checkerboard moving around", "",
                                                         "Video (*.mp4 *.avi *.mov)")
            if not p:
                return
            imgs = calmod.frames_from_video(p, 40)
        else:
            ps, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Checkerboard photos (20-30)", "",
                                                           "Images (*.jpg *.jpeg *.png *.tif *.bmp)")
            if not ps:
                return
            imgs = [cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR) for p in ps]
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            K, D, rms, n, size = calmod.calibrate_lens(imgs, self.cols.value(), self.rows.value(), self.sq.value())
        except Exception as e:
            QtWidgets.QApplication.restoreOverrideCursor()
            QtWidgets.QMessageBox.warning(self, "Lens calibration", str(e))
            return
        QtWidgets.QApplication.restoreOverrideCursor()
        if self.cal is None:
            self.cal = calmod.new_calibration(size)
        self.cal.update(K=K.tolist(), D=D.tolist(), rms=rms)
        self.lens_lbl.setText("<span style='color:%s'>Lens corrected from %d images, reprojection error %.2f px%s"
                              "</span>" % (theme.OK if rms < 1 else theme.WARN, n, rms,
                                           "" if rms < 1 else " (high - take sharper photos covering the corners)"))
        self._apply()

    def _plane(self):
        if self.frame is None:
            return
        try:
            H, err = calmod.plane_from_board(self.frame, self.cols.value(), self.rows.value(), self.sq.value(),
                                             self.cal.get("K"), self.cal.get("D"))
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Checkerboard", str(e))
            return
        self.cal["H"] = H.tolist()
        self.scale_lbl.setText("Perspective from the checkerboard (fit error %.2f mm). Now click the pedestal rim "
                               "for the centre (or keep the image centre)." % err)
        self._apply()

    def _clicked(self, ev):
        if ev.button() != QtCore.Qt.LeftButton or self.frame is None:
            return
        p = self.vb.mapSceneToView(ev.scenePos())
        key = "rim" if self.mode_rim.isChecked() else "wall"
        if key == "wall" and len(self.points["wall"]) >= 2:
            self.points["wall"] = []
        self.points[key].append((p.x(), p.y()))
        self._apply()

    def _undo(self):
        key = "rim" if self.mode_rim.isChecked() else "wall"
        if self.points[key]:
            self.points[key].pop()
            self._apply()

    def _clear(self):
        self.points = {"rim": [], "wall": []}
        self._apply()

    def _apply(self, *_):
        if self.cal is None:
            return
        rim = self.points["rim"]
        self.rim_items.setData([p[0] for p in rim], [p[1] for p in rim])
        self.wall_items.setData([p[0] for p in self.points["wall"]], [p[1] for p in self.points["wall"]])
        self.circle.setVisible(False)
        if len(rim) >= 3:
            und = calmod.undistort_px(rim, self.cal.get("K"), self.cal.get("D"))
            c_und, ppc = calmod.scale_from_circle(und, self.diam.value())
            c_raw, ppc_raw = calmod.scale_from_circle(rim, self.diam.value())
            self.cal["centre_px"] = c_raw
            if self.cal.get("H") is None:
                self.cal["px_per_cm"] = ppc
            r = ppc_raw * self.diam.value() / 2
            self.circle.setRect(c_raw[0] - r, c_raw[1] - r, 2 * r, 2 * r)
            self.circle.setVisible(True)
            if self.cal.get("H") is None:
                self.scale_lbl.setText("Pedestal fit: %.2f px/cm, centre (%.0f, %.0f)" % (ppc, c_raw[0], c_raw[1]))
        if len(self.points["wall"]) == 2:
            u = calmod.undistort_px(self.points["wall"], self.cal.get("K"), self.cal.get("D"))
            self.rot.blockSignals(True)
            self.rot.setValue(calmod.rotation_from_wall(u[0], u[1]) * (-1 if self.mirror.isChecked() else 1))
            self.rot.blockSignals(False)
        self.cal["rotation"] = self.rot.value()
        self.cal["mirror"] = self.mirror.isChecked()
        self._draw_check()

    def ready(self):
        return self.cal is not None and (self.cal.get("px_per_cm") or self.cal.get("H") is not None)

    def _draw_check(self):
        if not self.ready():
            self.arena.setData([], [])
            self.grid.setData([], [])
            return
        d = self.rig.dist
        t = np.linspace(-d, d, 60)
        sq = np.r_[np.c_[t, np.full(60, d)], np.c_[np.full(60, d), -t], np.c_[-t, np.full(60, -d)],
                   np.c_[np.full(60, -d), t]]
        a = calmod.from_cm(sq, self.cal)
        self.arena.setData(a[:, 0], a[:, 1])
        segs = []
        for k in range(-5, 6):
            segs += [(k, -5), (k, 5), (-5, k), (5, k)]
        g = calmod.from_cm(np.array(segs, float), self.cal)
        self.grid.setData(g[:, 0], g[:, 1])

    def _moved(self, pos):
        if self.frame is None or not self.ready():
            return
        p = self.vb.mapSceneToView(pos)
        cm = calmod.to_cm([[p.x(), p.y()]], self.cal)[0]
        self.pos_lbl.setText("pixel (%.0f, %.0f)  →  %.2f, %.2f cm" % (p.x(), p.y(), cm[0], cm[1]))

    # ------------------------------------------------------------------ save / load
    def _save(self):
        if not self.ready():
            QtWidgets.QMessageBox.information(self, "Calibration", "Set the scale first (pedestal rim or checkerboard).")
            return
        default = os.path.join(os.path.dirname(getattr(self, "path", "") or os.path.expanduser("~")),
                               "calibration.json")
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save calibration", default, "Calibration (*.json)")
        if not p:
            return
        calmod.save(self.cal, p)
        self.main.settings["last_calibration"] = p
        if self.target is not None:
            self.target.set(p)
        self.main.status("Calibration saved: %s" % p)

    def _load(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Load calibration", "", "Calibration (*.json)")
        if p:
            self.cal = calmod.load(p)
            self.rot.setValue(self.cal.get("rotation") or 0)
            self.mirror.setChecked(bool(self.cal.get("mirror")))
            self.lens_lbl.setText("lens correction loaded" if self.cal.get("K") else "no lens correction")
            self._apply()

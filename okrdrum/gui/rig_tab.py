"""Rig tab: drum geometry, which display shows the stimulus, alignment patterns and the
luminance / gamma tool."""
from __future__ import annotations

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from ..geometry import Rig, cycles_per_screen
from ..luminance import LEVELS, fit_gamma
from ..renderer import StimState, make_stim_window, place_on_screen
from . import theme
from .widgets import combo, form_spin


class RigTab(QtWidgets.QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.win = None
        self._build()
        self.set_rig(Rig.from_dict(main.settings.get("rig", {})))

    def _build(self):
        outer = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QVBoxLayout()
        right = QtWidgets.QVBoxLayout()
        outer.addLayout(left, 2)
        outer.addLayout(right, 3)
        g = QtWidgets.QGroupBox("Stimulus display")
        f = QtWidgets.QFormLayout(g)
        self.screen = QtWidgets.QComboBox()
        self.res_w = form_spin(320, 8192, 1024, 0)
        self.res_h = form_spin(240, 8192, 768, 0)
        rh = QtWidgets.QHBoxLayout()
        rh.addWidget(self.res_w)
        rh.addWidget(QtWidgets.QLabel("×"))
        rh.addWidget(self.res_h)
        self.full = QtWidgets.QCheckBox("full screen")
        f.addRow("Display", self.screen)
        f.addRow("Window size (px)", rh)
        f.addRow("", self.full)
        left.addWidget(g)
        self._screens()

        g = QtWidgets.QGroupBox("Drum geometry (one screen, seen from the pedestal)")
        f = QtWidgets.QFormLayout(g)
        self.vis_w = form_spin(1, 500, 40.98, 2, 0.1, "cm")
        self.vis_h = form_spin(1, 500, 23.0, 2, 0.1, "cm")
        self.dist = form_spin(1, 500, 21.35, 2, 0.1, "cm")
        self.seam = form_spin(0, 50, 1.65, 2, 0.05, "cm")
        self.seam_side = combo(["left", "right"])
        self.gamma = form_spin(0.5, 4.0, 1.0, 3, 0.05)
        f.addRow("Visible screen width", self.vis_w)
        f.addRow("Visible screen height", self.vis_h)
        f.addRow("Distance centre → screen", self.dist)
        f.addRow("Bezel at the seam", self.seam)
        f.addRow("Seam side", self.seam_side)
        f.addRow("Monitor gamma", self.gamma)
        self.check = QtWidgets.QLabel()
        self.check.setWordWrap(True)
        f.addRow(self.check)
        left.addWidget(g)
        for w in (self.vis_w, self.vis_h, self.dist, self.seam, self.gamma, self.res_w):
            w.valueChanged.connect(self._update)
        self.seam_side.currentIndexChanged.connect(self._update)

        g = QtWidgets.QGroupBox("Check the drum")
        v = QtWidgets.QVBoxLayout(g)
        for txt, mode, tip in (
                ("Alignment lines", 3, "Thin lines every 15°, bright lines at 0° and ±45° (screen ends), and a "
                                       "horizontal line at mid-height: they must line up across the corners."),
                ("Test grating (5°, still)", 1, "Stripes must continue across every corner seam."),
                ("Mean grey", 0, "Check that all four monitors look equally bright."),
                ("White", 2, "Full white for the photometer / brightness matching.")):
            b = theme.button(txt, slot=lambda _=False, m=mode: self.show_pattern(m), tip=tip)
            v.addWidget(b)
        h = QtWidgets.QHBoxLayout()
        h.addWidget(theme.button("Luminance && gamma…", "primary", self.luminance))
        h.addWidget(theme.button("Close pattern", slot=self.close_pattern))
        v.addLayout(h)
        left.addWidget(g)
        left.addStretch(1)

        g = QtWidgets.QGroupBox("Preview of one screen (as drawn)")
        v = QtWidgets.QVBoxLayout(g)
        self.prev = QtWidgets.QLabel()
        self.prev.setMinimumHeight(260)
        self.prev.setAlignment(QtCore.Qt.AlignCenter)
        self.prev.setStyleSheet("background:#0b1224; border-radius:6px")
        v.addWidget(self.prev, 1)
        h = QtWidgets.QHBoxLayout()
        self.prev_bar = form_spin(0.2, 45, 5, 2, 0.25, "deg")
        self.prev_mode = combo(["grating", "alignment lines"])
        h.addWidget(QtWidgets.QLabel("Bar width"))
        h.addWidget(self.prev_bar)
        h.addWidget(self.prev_mode)
        h.addStretch(1)
        v.addLayout(h)
        self.prev_bar.valueChanged.connect(self._update)
        self.prev_mode.currentIndexChanged.connect(self._update)
        self.info = QtWidgets.QLabel()
        self.info.setWordWrap(True)
        v.addWidget(self.info)
        right.addWidget(g, 1)

    def _screens(self):
        self.screen.clear()
        for i, s in enumerate(QtGui.QGuiApplication.screens()):
            g = s.geometry()
            self.screen.addItem("%d: %s  %d×%d" % (i + 1, s.name(), g.width(), g.height()), i + 1)

    def rig(self):
        return Rig(vis_w=self.vis_w.value(), vis_h=self.vis_h.value(), dist=self.dist.value(),
                   seam=self.seam.value(), seam_side=self.seam_side.currentText(), gamma=self.gamma.value(),
                   screen=int(self.screen.currentData() or 1), res_w=self.res_w.value(), res_h=self.res_h.value(),
                   fullscreen=self.full.isChecked())

    def set_rig(self, r: Rig):
        for w, v in ((self.vis_w, r.vis_w), (self.vis_h, r.vis_h), (self.dist, r.dist), (self.seam, r.seam),
                     (self.gamma, r.gamma), (self.res_w, r.res_w), (self.res_h, r.res_h)):
            w.setValue(v)
        self.seam_side.setCurrentText(r.seam_side)
        self.full.setChecked(r.fullscreen)
        i = self.screen.findData(r.screen)
        self.screen.setCurrentIndex(max(i, 0))
        self._update()

    def _update(self, *_):
        r = self.rig()
        mm = r.side_mismatch()
        a0, a1 = r.span()
        col = theme.OK if abs(mm) <= 0.3 else theme.BAD
        self.check.setText("<span style='color:%s'>Visible width + bezel = %.2f cm, 2 × distance = %.2f cm%s</span>"
                           % (col, r.vis_w + r.seam, 2 * r.dist, "" if abs(mm) <= 0.3 else
                              " - stripes will not meet at the corners"))
        self.info.setText("Each screen covers azimuth %.1f° to %.1f° (the bezel seam hides %.1f°), elevation ±%.1f° "
                          "at its centre, %.1f px/deg at the centre and %.1f px/deg at the corners."
                          % (a0, a1, 90 - (a1 - a0), r.elevation(), r.px_per_deg_centre(r.res_w),
                             r.res_w / r.vis_w * r.dist * np.pi / 180 * 2))
        st = StimState(r)
        n, w = cycles_per_screen(self.prev_bar.value())
        if self.prev_mode.currentIndex() == 0:
            st.start_grating({"contrast": 1, "bar_width_used_deg": w, "speed_deg_s": 0, "dir_sign": 1,
                              "edge": "square"}, t0=0)
        else:
            st.mode = 3
        W, H = 640, 360
        row = (st.cpu_row(W, now=0) * 255).astype(np.uint8)
        img = np.repeat(row[None, :], H, 0)
        if st.mode == 3:
            img[H // 2 - 1:H // 2 + 1] = 150
        qi = QtGui.QImage(img.tobytes(), W, H, W, QtGui.QImage.Format_Grayscale8)
        self._pix = QtGui.QPixmap.fromImage(qi.copy())
        self._fit_preview()

    def _fit_preview(self):
        if getattr(self, "_pix", None) is not None:
            sz = self.prev.size() - QtCore.QSize(16, 16)
            self.prev.setPixmap(self._pix.scaled(max(sz.width(), 100), max(sz.height(), 60),
                                                 QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fit_preview()

    def showEvent(self, ev):
        super().showEvent(ev)
        QtCore.QTimer.singleShot(0, self._fit_preview)

    # ------------------------------------------------------------------ patterns on the drum
    def show_pattern(self, mode, level=1.0):
        r = self.rig()
        if self.win is None:
            self.state = StimState(r)
            self.win = make_stim_window(self.state)
            self.win.key_handler = lambda ev: self.close_pattern() if ev.key() == QtCore.Qt.Key_Escape else None
            place_on_screen(self.win, r)
        self.state.rig = r
        if mode == 1:
            self.state.start_grating({"contrast": 1, "bar_width_used_deg": 5.0, "speed_deg_s": 0, "dir_sign": 1,
                                      "edge": "square"})
        else:
            self.state.mode = mode
        self.state.level = level
        self.main.status("Showing a pattern on display %d (ESC on the drum or 'Close pattern' to close)" % r.screen)

    def close_pattern(self):
        if self.win is not None:
            self.win.close()
            self.win = None

    def luminance(self):
        LuminanceDialog(self).exec()


class LuminanceDialog(QtWidgets.QDialog):
    """Steps the drum through grey levels; enter the photometer reading for each; fit gamma."""

    def __init__(self, rig_tab: RigTab):
        super().__init__(rig_tab)
        self.rt = rig_tab
        self.setWindowTitle("Luminance & gamma")
        self.resize(560, 560)
        v = QtWidgets.QVBoxLayout(self)
        t = QtWidgets.QLabel(
            "1. Point the photometer at the centre of one screen from the pedestal position.<br>"
            "2. Click a level to show it on the drum, read the photometer (cd/m²) and type the value.<br>"
            "3. <b>Fit gamma</b>, then <b>Use this gamma</b> so contrasts are linear.<br>"
            "Measure each monitor at 50 % and adjust its brightness buttons until all four match.")
        t.setWordWrap(True)
        v.addWidget(t)
        self.table = QtWidgets.QTableWidget(len(LEVELS), 2)
        self.table.setHorizontalHeaderLabels(["Level (0-1)", "Reading (cd/m²)"])
        self.table.verticalHeader().setVisible(False)
        for i, lv in enumerate(LEVELS):
            it = QtWidgets.QTableWidgetItem("%.3f" % lv)
            it.setFlags(it.flags() & ~QtCore.Qt.ItemIsEditable)
            self.table.setItem(i, 0, it)
            self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(""))
        self.table.cellClicked.connect(self._show)
        v.addWidget(self.table, 1)
        self.raw = QtWidgets.QCheckBox("show levels without gamma correction (needed for the fit)")
        self.raw.setChecked(True)
        v.addWidget(self.raw)
        self.res = QtWidgets.QLabel("")
        self.res.setWordWrap(True)
        v.addWidget(self.res)
        h = QtWidgets.QHBoxLayout()
        h.addWidget(theme.button("Fit gamma", "primary", self.fit))
        self.use = theme.button("Use this gamma", slot=self.apply)
        self.use.setEnabled(False)
        h.addWidget(self.use)
        h.addStretch(1)
        h.addWidget(theme.button("Close", slot=self.accept))
        v.addLayout(h)
        self.g = None

    def _show(self, row, col):
        lv = LEVELS[row]
        rig = self.rt.rig()
        if self.raw.isChecked():
            rig.gamma = 1.0
        self.rt.show_pattern(2, lv)
        self.rt.state.rig = rig

    def fit(self):
        vals = []
        for i in range(len(LEVELS)):
            try:
                vals.append(float(self.table.item(i, 1).text().replace(",", ".")))
            except Exception:
                vals.append(np.nan)
        try:
            r = fit_gamma(LEVELS, vals)
        except Exception as e:
            self.res.setText("<span style='color:%s'>%s</span>" % (theme.BAD, e))
            return
        self.g = r["gamma"]
        self.res.setText("Gamma <b>%.2f</b> (fit error %.2f cd/m²). Black %.2f, white %.1f cd/m², mean grey %.1f "
                         "cd/m², best possible Michelson contrast %.3f." % (r["gamma"], r["rms"], r["Lmin"], r["Lmax"],
                                                                           r["mean_lum"], r["michelson_max"]))
        self.use.setEnabled(True)

    def apply(self):
        if self.g:
            self.rt.gamma.setValue(self.g)
            self.rt.main.save_all()

    def done(self, r):
        self.rt.close_pattern()
        super().done(r)

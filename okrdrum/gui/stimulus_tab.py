"""Stimulus tab: protocol (fixed trial list or staircase), session details, sync port, run."""
from __future__ import annotations

import os

from PySide6 import QtCore, QtGui, QtWidgets

from .. import protocol as proto
from ..runner import Runner
from ..sync import MarkerPort, list_ports
from . import theme
from .widgets import FileRow, combo, form_spin, show_in_folder


class StimulusTab(QtWidgets.QWidget):
    run_finished = QtCore.Signal(str)

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.runner = Runner(self)
        self.runner.status.connect(self._status)
        self.runner.trial_started.connect(self._started)
        self.runner.trial_done.connect(self._done)
        self.runner.need_response.connect(self._need_response)
        self.runner.finished.connect(self._finished)
        self._build()
        self.load(main.settings.get("protocol", {}), main.settings.get("meta", {}))

    # ------------------------------------------------------------------ UI
    def _build(self):
        outer = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QVBoxLayout()
        right = QtWidgets.QVBoxLayout()
        outer.addLayout(left, 3)
        outer.addLayout(right, 2)

        g = QtWidgets.QGroupBox("Session")
        f = QtWidgets.QFormLayout(g)
        self.animal = QtWidgets.QLineEdit()
        self.session = QtWidgets.QLineEdit("1")
        self.treatment = QtWidgets.QLineEdit()
        self.outdir = FileRow(folder=True, placeholder="folder for the stimulus logs")
        f.addRow("Animal ID", self.animal)
        f.addRow("Session", self.session)
        f.addRow("Treatment / group", self.treatment)
        f.addRow("Save logs in", self.outdir)
        left.addWidget(g)

        g = QtWidgets.QGroupBox("Protocol")
        v = QtWidgets.QVBoxLayout(g)
        h = QtWidgets.QHBoxLayout()
        self.mode = combo(["Fixed list (values or ranges)", "Staircase (find the threshold)"])
        self.edge = combo(["square bars", "sine"])
        h.addWidget(QtWidgets.QLabel("Mode"))
        h.addWidget(self.mode, 1)
        h.addWidget(QtWidgets.QLabel("Edge"))
        h.addWidget(self.edge)
        v.addLayout(h)
        grid = QtWidgets.QGridLayout()
        for c, t in enumerate(["", "range", "value", "start", "end", "interval"]):
            if t:
                lab = QtWidgets.QLabel("<b>%s</b>" % t)
                grid.addWidget(lab, 0, c)
        self.pw = {}
        for r, (key, label, unit, lo, hi, dec, step) in enumerate(proto.PARAMS, start=1):
            w = {"chk": QtWidgets.QCheckBox()}
            for fld in ("value", "start", "end", "step"):
                sb = form_spin(lo if fld != "step" else 10 ** -dec, hi, 1, dec, step, unit)
                sb.valueChanged.connect(self._preview)
                w[fld] = sb
            w["chk"].toggled.connect(self._enable)
            grid.addWidget(QtWidgets.QLabel(label), r, 0)
            grid.addWidget(w["chk"], r, 1)
            for c, fld in enumerate(("value", "start", "end", "step"), start=2):
                grid.addWidget(w[fld], r, c)
            self.pw[key] = w
        v.addLayout(grid)
        f = QtWidgets.QFormLayout()
        self.direction = combo(list(proto.DIRECTIONS))
        self.duration = form_spin(0.2, 3600, 10, 1, 1, "s")
        self.iti = form_spin(0, 600, 5, 1, 1, "s")
        self.wait = QtWidgets.QCheckBox("start every trial with SPACE")
        self.repeats = form_spin(1, 1000, 1, 0)
        self.order = combo(["sequential", "random"])
        f.addRow("Direction", self.direction)
        f.addRow("Grating duration", self.duration)
        f.addRow("Grey before each trial", self.iti)
        f.addRow("", self.wait)
        f.addRow("Repeats", self.repeats)
        f.addRow("Order", self.order)
        v.addLayout(f)
        self.sc_box = QtWidgets.QGroupBox("Staircase")
        sf = QtWidgets.QFormLayout(self.sc_box)
        self.sc_var = combo(["spatial frequency", "contrast"])
        self.sc_start = form_spin(0.001, 5, 0.1, 3, 0.01)
        self.sc_step = form_spin(0.001, 2, 0.05, 4, 0.005)
        self.sc_min = form_spin(0.0005, 1, 0.0125, 4, 0.0025)
        self.sc_rev = form_spin(2, 40, 6, 0)
        self.sc_max = form_spin(4, 500, 60, 0)
        sf.addRow("Vary", self.sc_var)
        sf.addRow("Start (c/deg or contrast)", self.sc_start)
        sf.addRow("First step", self.sc_step)
        sf.addRow("Smallest step", self.sc_min)
        sf.addRow("Stop after reversals", self.sc_rev)
        sf.addRow("Max trials", self.sc_max)
        note = QtWidgets.QLabel("After each grating press <b>Y</b> if the mouse tracked, <b>N</b> if not. "
                                "CW and CCW (left and right eye) run as two interleaved staircases.")
        note.setWordWrap(True)
        note.setProperty("muted", True)
        sf.addRow(note)
        v.addWidget(self.sc_box)
        self.preview = QtWidgets.QLabel()
        self.preview.setWordWrap(True)
        v.addWidget(self.preview)
        h = QtWidgets.QHBoxLayout()
        h.addWidget(theme.button("Load protocol…", slot=self._load_file))
        h.addWidget(theme.button("Save protocol…", slot=self._save_file))
        h.addStretch(1)
        v.addLayout(h)
        left.addWidget(g)
        for wdg in (self.mode, self.direction, self.order, self.sc_var):
            wdg.currentIndexChanged.connect(self._enable)
        for wdg in (self.duration, self.repeats, self.sc_start, self.sc_step, self.sc_rev, self.sc_max):
            wdg.valueChanged.connect(self._preview)
        left.addStretch(1)

        g = QtWidgets.QGroupBox("Sync to the Raspberry Pi")
        h = QtWidgets.QHBoxLayout(g)
        self.port = QtWidgets.QComboBox()
        h.addWidget(self.port, 1)
        h.addWidget(theme.button("Refresh", slot=self._ports))
        h.addWidget(theme.button("Send test marker", slot=self._test_marker,
                                 tip="Sends 'T0 test' and 'E0' - the Pi recorder shows them live"))
        h.addWidget(theme.button("Send session info", slot=self._send_info,
                                 tip="Animal, session, treatment and date to the Pi recorder (also sent at every run start)"))
        right.addWidget(g)
        self._ports()

        g = QtWidgets.QGroupBox("Run")
        v = QtWidgets.QVBoxLayout(g)
        h = QtWidgets.QHBoxLayout()
        self.start_btn = theme.button("Start run", "primary", self.start)
        self.next_btn = theme.button("Start trial  (SPACE)", slot=lambda: self.runner.key("space"))
        self.stop_btn = theme.button("Stop  (ESC)", "danger", lambda: self.runner.key("escape"))
        for b in (self.start_btn, self.next_btn, self.stop_btn):
            h.addWidget(b)
        v.addLayout(h)
        h = QtWidgets.QHBoxLayout()
        self.yes_btn = theme.button("Tracked  (Y)", "good", lambda: self._key("y"))
        self.no_btn = theme.button("Not tracked  (N)", slot=lambda: self._key("n"))
        h.addWidget(self.yes_btn)
        h.addWidget(self.no_btn)
        v.addLayout(h)
        self.state_lbl = QtWidgets.QLabel("Not running")
        self.state_lbl.setProperty("h2", True)
        self.state_lbl.setWordWrap(True)
        v.addWidget(self.state_lbl)
        self.table = QtWidgets.QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["#", "c/deg", "contrast", "deg/s", "dir", "dropped", "answer"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        v.addWidget(self.table, 1)
        self.result_lbl = QtWidgets.QLabel("")
        self.result_lbl.setWordWrap(True)
        v.addWidget(self.result_lbl)
        h = QtWidgets.QHBoxLayout()
        self.open_btn = theme.button("Show log in folder", slot=lambda: show_in_folder(self.last_csv))
        self.open_btn.setEnabled(False)
        h.addWidget(self.open_btn)
        h.addStretch(1)
        v.addLayout(h)
        right.addWidget(g, 1)
        self.last_csv = None
        self._keys = _RunKeys(self._key)      # SPACE / ESC / Y / N work in every window while a run is on
        self._set_running(False)

    # ------------------------------------------------------------------ protocol <-> widgets
    def protocol(self):
        p = {"mode": "staircase" if self.mode.currentIndex() == 1 else "fixed",
             "edge": "square" if self.edge.currentIndex() == 0 else "sine",
             "direction": self.direction.currentText(), "duration": self.duration.value(),
             "iti": self.iti.value(), "wait_for_key": self.wait.isChecked(), "repeats": self.repeats.value(),
             "order": self.order.currentText(), "sc_variable": self.sc_var.currentText(),
             "sc_start": self.sc_start.value(), "sc_step": self.sc_step.value(), "sc_min_step": self.sc_min.value(),
             "sc_reversals": self.sc_rev.value(), "sc_max_trials": self.sc_max.value()}
        for key, w in self.pw.items():
            p[key] = {"range": w["chk"].isChecked(), "value": w["value"].value(), "start": w["start"].value(),
                      "end": w["end"].value(), "step": w["step"].value()}
        return p

    def meta(self):
        return {"animal": self.animal.text().strip(), "session": self.session.text().strip() or "1",
                "treatment": self.treatment.text().strip(), "out_dir": self.outdir.path()}

    def load(self, p, meta=None):
        p = proto.merged(p)
        self.mode.setCurrentIndex(1 if p["mode"] == "staircase" else 0)
        self.edge.setCurrentIndex(0 if p["edge"] == "square" else 1)
        self.direction.setCurrentText(p["direction"])
        self.duration.setValue(p["duration"])
        self.iti.setValue(p["iti"])
        self.wait.setChecked(bool(p["wait_for_key"]))
        self.repeats.setValue(int(p["repeats"]))
        self.order.setCurrentText(p["order"])
        self.sc_var.setCurrentText(p["sc_variable"])
        self.sc_start.setValue(p["sc_start"])
        self.sc_step.setValue(p["sc_step"])
        self.sc_min.setValue(p["sc_min_step"])
        self.sc_rev.setValue(int(p["sc_reversals"]))
        self.sc_max.setValue(int(p["sc_max_trials"]))
        for key, w in self.pw.items():
            for fld in ("value", "start", "end", "step"):
                w[fld].setValue(p[key][fld])
            w["chk"].setChecked(bool(p[key]["range"]))
        meta = meta or {}
        self.animal.setText(meta.get("animal", ""))
        self.session.setText(meta.get("session", "1"))
        self.treatment.setText(meta.get("treatment", ""))
        self.outdir.set(meta.get("out_dir") or os.path.join(os.path.expanduser("~"), "OKR Drum data"))
        self._enable()

    def _enable(self, *_):
        stair = self.mode.currentIndex() == 1
        self.sc_box.setVisible(stair)
        for key, w in self.pw.items():
            on = w["chk"].isChecked() and not stair
            w["chk"].setEnabled(not stair)
            w["value"].setEnabled(not on)
            for fld in ("start", "end", "step"):
                w[fld].setEnabled(on)
        if stair:
            self.pw["contrast" if self.sc_var.currentText() == "contrast" else "bar_width"]["value"].setEnabled(False)
        for wdg in (self.repeats, self.order):
            wdg.setEnabled(not stair)
        self._preview()

    def _preview(self, *_):
        try:
            p = self.protocol()
            txt = proto.summary(p)
            if p["mode"] == "fixed":
                parts = []
                for key, label, unit, *_r in proto.PARAMS:
                    vals = proto.param_values(p[key])
                    parts.append("%s: %s %s" % (label, ", ".join("%g" % x for x in vals[:8])
                                                + (" … (%d)" % len(vals) if len(vals) > 8 else ""), unit))
                trials = proto.build_trials(p, seed=0)
                rounded = sorted({(t["bar_width_requested_deg"], t["bar_width_used_deg"]) for t in trials
                                  if abs(t["bar_width_used_deg"] - t["bar_width_requested_deg"]) > 1e-3})
                txt = "<b>%s</b><br>%s" % (txt, "<br>".join(parts))
                if rounded:
                    txt += ("<br><i>Bar widths rounded to whole cycles per screen: %s</i>"
                            % ", ".join("%g→%.3f" % r for r in rounded[:6]))
            else:
                txt = "<b>%s</b>" % txt
            self.preview.setText(txt)
        except Exception as e:
            self.preview.setText("<span style='color:%s'>%s</span>" % (theme.BAD, e))

    def _load_file(self):
        import json
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Load protocol", "", "Protocol (*.json)")
        if p:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            self.load(d.get("protocol", d), self.meta())

    def _save_file(self):
        import json
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save protocol", "okr_protocol.json", "Protocol (*.json)")
        if p:
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"protocol": self.protocol()}, f, indent=1)

    # ------------------------------------------------------------------ sync
    def _ports(self):
        cur = self.port.currentData() or self.main.settings.get("serial_port", "none")
        self.port.clear()
        self.port.addItem("none (no sync)", "none")
        for dev, desc in list_ports():
            self.port.addItem(desc, dev)
        i = self.port.findData(cur)
        self.port.setCurrentIndex(max(i, 0))

    def _test_marker(self):
        dev = self.port.currentData()
        if dev in (None, "none"):
            self.main.status("Choose the USB-serial adapter first")
            return
        p = MarkerPort(dev)
        if not p.ok:
            QtWidgets.QMessageBox.warning(self, "Serial port", "Cannot open %s:\n%s" % (dev, p.error))
            return
        p.send("T0 test marker")
        QtCore.QTimer.singleShot(1000, lambda: (p.send("E0"), p.close()))
        self.main.status("Sent a test marker on %s - the Pi recorder should show it" % dev)

    def _send_info(self):
        from ..runner import session_info
        dev = self.port.currentData()
        if dev in (None, "none"):
            self.main.status("Choose the USB-serial adapter first")
            return
        p = MarkerPort(dev)
        if not p.ok:
            QtWidgets.QMessageBox.warning(self, "Serial port", "Cannot open %s:\n%s" % (dev, p.error))
            return
        p.session(session_info(self.meta(), self.protocol()))
        p.close()
        self.main.status("Session info sent to the Pi on %s" % dev)

    # ------------------------------------------------------------------ run
    def start(self):
        if self.runner.running:
            return
        p = self.protocol()
        try:
            if p["mode"] == "fixed" and not proto.build_trials(p):
                raise ValueError("no trials")
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Protocol", str(e))
            return
        rig = self.main.rig()
        if abs(rig.side_mismatch()) > 0.3:
            ans = QtWidgets.QMessageBox.question(
                self, "Geometry check", "Visible width + bezel = %.2f cm but 2 × distance = %.2f cm, so the "
                "stripes will not meet at the corners.\n\nRun anyway?" % (rig.vis_w + rig.seam, 2 * rig.dist))
            if ans != QtWidgets.QMessageBox.Yes:
                return
        self.main.save_all()
        self.table.setRowCount(0)
        self.result_lbl.setText("")
        meta = self.meta()
        try:
            self.runner.start(p, rig, meta, meta["out_dir"], port=self.port.currentData())
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Cannot start", str(e))
            return
        self._set_running(True)

    def _set_running(self, on):
        stair = self.mode.currentIndex() == 1
        app = QtWidgets.QApplication.instance()
        if on:
            app.installEventFilter(self._keys)
            fw = app.focusWidget()
            if fw is not None:
                fw.clearFocus()             # so SPACE can't land in a text box
        else:
            app.removeEventFilter(self._keys)
        self.start_btn.setEnabled(not on)
        for b in (self.next_btn, self.stop_btn):
            b.setEnabled(on)
        for b in (self.yes_btn, self.no_btn):
            b.setEnabled(on and stair)
            b.setVisible(stair)

    def _status(self, s):
        self.state_lbl.setText(s)
        self.main.status(s)

    def _started(self, t):
        self.state_lbl.setText("<span style='color:%s'>● Grating on</span> - trial %d, %.3f c/deg, %g deg/s %s"
                               % (theme.BAD, t["trial"], t["spatial_freq_cpd"], t["speed_deg_s"], t["direction"]))

    def _done(self, t):
        r = self.table.rowCount()
        self.table.insertRow(r)
        for c, v in enumerate([t["trial"], "%.3f" % t["spatial_freq_cpd"], "%g" % t["contrast"],
                               "%g" % t["speed_deg_s"], t["direction"], t.get("dropped_frames", ""), ""]):
            self.table.setItem(r, c, QtWidgets.QTableWidgetItem(str(v)))
        self.table.scrollToBottom()

    def _key(self, name):
        if name in ("y", "n") and self.runner.running and self.runner.phase == "respond" and self.table.rowCount():
            self.table.setItem(self.table.rowCount() - 1, 6, QtWidgets.QTableWidgetItem("yes" if name == "y" else "no"))
        self.runner.key(name)

    def _need_response(self, t):
        self.yes_btn.setFocus()

    def _finished(self, path):
        self.last_csv = path
        self.open_btn.setEnabled(True)
        self._set_running(False)
        if self.runner.stair:
            res = self.runner.stair.results()
            self.result_lbl.setText("<b>Staircase thresholds</b><br>" + "<br>".join(
                "%s (%s eye): %.3f%s after %d trials" % (k, "left" if k == "CW" else "right", v["threshold"],
                                                       "" if v["done"] else " (not finished)", v["trials"])
                for k, v in res.items()))
        self.run_finished.emit(path)


class _RunKeys(QtCore.QObject):
    """Application-wide key catcher used only while a run is going: the run keys then work whether
    the main window, the stimulus window or any field has the focus (a focused button or spin box
    would otherwise take SPACE)."""
    KEYS = {QtCore.Qt.Key_Space: "space", QtCore.Qt.Key_Escape: "escape", QtCore.Qt.Key_Y: "y",
            QtCore.Qt.Key_N: "n"}

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t in (QtCore.QEvent.KeyPress, QtCore.QEvent.ShortcutOverride) and ev.key() in self.KEYS \
                and not (ev.modifiers() & (QtCore.Qt.ControlModifier | QtCore.Qt.AltModifier | QtCore.Qt.MetaModifier)):
            if QtWidgets.QApplication.activeModalWidget() is not None or QtWidgets.QApplication.activePopupWidget():
                return False
            if t == QtCore.QEvent.ShortcutOverride:
                ev.accept()                 # keep menus/buttons from treating it as a shortcut
                return True
            if not ev.isAutoRepeat():
                self.callback(self.KEYS[ev.key()])
            return True
        return False

"""Small reusable widgets."""
from __future__ import annotations

import json
import os
import subprocess
import sys

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from . import theme

SETTINGS_DIR = os.path.join(os.path.expanduser("~"), ".okrdrum")
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")


def load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(d):
    try:
        os.makedirs(SETTINGS_DIR, exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1, default=str)
    except Exception:
        pass


def show_in_folder(path):
    if not path:
        return
    p = path if os.path.isdir(path) else os.path.dirname(path)
    try:
        if sys.platform.startswith("win"):
            if os.path.isfile(path):
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            else:
                os.startfile(p)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path] if os.path.isfile(path) else ["open", p])
        else:
            subprocess.Popen(["xdg-open", p])
    except Exception:
        pass


class FileRow(QtWidgets.QWidget):
    changed = QtCore.Signal(str)

    def __init__(self, filt="All files (*)", save=False, folder=False, placeholder=""):
        super().__init__()
        self.filt, self.save, self.folder = filt, save, folder
        h = QtWidgets.QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        self.edit = QtWidgets.QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.editingFinished.connect(lambda: self.changed.emit(self.path()))
        h.addWidget(self.edit, 1)
        b = QtWidgets.QToolButton()
        b.setText("…")
        b.clicked.connect(self.browse)
        h.addWidget(b)

    def path(self):
        return self.edit.text().strip()

    def set(self, p, emit=False):
        self.edit.setText(p or "")
        if emit:
            self.changed.emit(self.path())

    def browse(self):
        start = self.path() or os.path.expanduser("~")
        if self.folder:
            p = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose folder", start)
        elif self.save:
            p, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save as", start, self.filt)
        else:
            p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open", start, self.filt)
        if p:
            self.set(p, emit=True)


class MplCanvas(QtWidgets.QWidget):
    """A matplotlib figure that can be replaced (figure-producing functions take fig=...)."""

    def __init__(self, figsize=(8, 4)):
        super().__init__()
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
        from matplotlib.figure import Figure
        self.fig = Figure(figsize=figsize, dpi=100)
        self.fig.set_facecolor("white")
        self.canvas = FigureCanvasQTAgg(self.fig)
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        v.addWidget(self.toolbar)
        v.addWidget(self.canvas, 1)

    def draw(self, fn, *a, **k):
        self.fig.clear()
        try:
            fn(*a, fig=self.fig, **k)
        except Exception as e:      # show the problem in the plot instead of failing
            self.fig.clear()
            self.fig.text(0.02, 0.5, "Cannot draw: %s" % e, color=theme.BAD)
        self.canvas.draw_idle()


class LogView(QtWidgets.QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setMaximumBlockCount(5000)
        f = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        f.setPointSize(9)
        self.setFont(f)

    def log(self, text):
        self.appendPlainText(text.rstrip())
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())


def level_item(level, text):
    it = QtWidgets.QListWidgetItem(("✔  " if level == "ok" else "⚠  " if level == "warning" else "✖  ") + text)
    it.setForeground(QtGui.QColor({"ok": theme.OK, "warning": theme.WARN}.get(level, theme.BAD)))
    return it


def table_from_df(table, df, float_fmt="{:.3g}", max_rows=5000):
    table.setSortingEnabled(False)
    table.clear()
    table.setColumnCount(len(df.columns))
    table.setRowCount(min(len(df), max_rows))
    table.setHorizontalHeaderLabels([str(c) for c in df.columns])
    for i, row in enumerate(df.itertuples(index=False)):
        if i >= max_rows:
            break
        for j, v in enumerate(row):
            if isinstance(v, (float, np.floating)):
                s = "" if not np.isfinite(v) else float_fmt.format(v)
            else:
                s = str(v)
            it = QtWidgets.QTableWidgetItem(s)
            if isinstance(v, (int, float, np.number)) and not isinstance(v, bool):
                it.setData(QtCore.Qt.UserRole, float(v) if np.isfinite(v) else -1e300)
            table.setItem(i, j, it)
    table.resizeColumnsToContents()
    table.setSortingEnabled(True)


def form_spin(lo, hi, val, dec=2, step=None, suffix=""):
    if dec == 0:
        w = QtWidgets.QSpinBox()
        w.setRange(int(lo), int(hi))
        w.setValue(int(val))
    else:
        w = QtWidgets.QDoubleSpinBox()
        w.setDecimals(dec)
        w.setRange(lo, hi)
        w.setValue(float(val))
        if step:
            w.setSingleStep(step)
    if suffix:
        w.setSuffix(" " + suffix)
    w.setKeyboardTracking(False)
    w.setMinimumWidth(72)          # don't let the range text force wide boxes on small screens
    return w


def combo(items, current=None):
    c = QtWidgets.QComboBox()
    c.addItems(items)
    if current in items:
        c.setCurrentText(current)
    return c

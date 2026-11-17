"""Look and feel shared with SURF / ChATlas: light Fusion palette, navy menu bar and header,
cyan accents (from the OKR Drum logo), rounded cards, and a start-up splash."""
from __future__ import annotations

import os
import sys
import time

from PySide6 import QtCore, QtGui, QtWidgets

NAVY = "#101d3d"
NAVY_2 = "#16264d"
NAVY_3 = "#24386a"
BG = "#eef2f7"
CARD = "#ffffff"
TEXT = "#14233b"
MUTED = "#5d6b80"
LINE = "#d8dfe9"
ACCENT = "#1f9fd6"        # cyan of the drum stripes
ACCENT_SOFT = "#e2f3fb"
GOLD = "#f2b632"          # rotation arrow
OK, WARN, BAD = "#2e9e6a", "#d08a12", "#c8463f"


def resource(*parts):
    """Bundled files: next to the package when frozen (PyInstaller), else in the repository."""
    base = getattr(sys, "_MEIPASS", None)
    cands = []
    if base:
        cands.append(os.path.join(base, *parts))
    here = os.path.dirname(os.path.abspath(__file__))
    cands.append(os.path.join(here, "..", "..", *parts))
    cands.append(os.path.join(here, "..", *parts))
    for c in cands:
        if os.path.exists(c):
            return os.path.normpath(c)
    return cands[-1]


def icon_path(size=256):
    return resource("assets", "icon", "okr_drum_%d.png" % size)


def apply_theme(app):
    if getattr(app, "_okr_themed", False):
        return
    app._okr_themed = True
    app.setStyle("Fusion")
    pal = QtGui.QPalette()
    c = QtGui.QColor
    P = QtGui.QPalette
    for role, col in ((P.Window, BG), (P.WindowText, TEXT), (P.Base, CARD), (P.AlternateBase, "#f6f8fb"),
                      (P.Text, TEXT), (P.Button, "#ffffff"), (P.ButtonText, TEXT), (P.ToolTipBase, NAVY),
                      (P.ToolTipText, "white"), (P.Highlight, ACCENT), (P.HighlightedText, "white"),
                      (P.Link, "#1769aa"), (P.PlaceholderText, "#94a1b2")):
        pal.setColor(role, c(col))
    for role in (P.WindowText, P.Text, P.ButtonText):
        pal.setColor(P.Disabled, role, c("#9aa6b5"))
    app.setPalette(pal)
    app.setStyleSheet(_with_arrows(STYLE))
    if os.path.exists(icon_path()):
        app.setWindowIcon(QtGui.QIcon(icon_path()))


STYLE = f"""
QMainWindow::separator {{ background: {BG}; width: 6px; height: 6px; }}
QToolTip {{ background: {NAVY}; color: white; border: none; padding: 6px 8px; border-radius: 4px; }}
QMenuBar {{ background: {NAVY}; color: #e8eef6; padding: 2px 4px; }}
QMenuBar::item {{ background: transparent; padding: 5px 10px; border-radius: 4px; }}
QMenuBar::item:selected {{ background: {NAVY_3}; }}
QMenu {{ background: white; border: 1px solid {LINE}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 14px; border-radius: 4px; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 8px; }}
QTabWidget::pane {{ border: 1px solid {LINE}; border-radius: 8px; background: {CARD}; top: -1px; }}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 9px 18px; margin-right: 2px;
               border: none; border-bottom: 3px solid transparent; font-weight: 600; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 3px solid {ACCENT}; }}
QTabBar::tab:hover {{ color: {TEXT}; }}
QGroupBox {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 8px; margin-top: 14px;
            padding: 10px 8px 8px 8px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {NAVY_3}; }}
QPushButton {{ background: white; border: 1px solid #c9d3e0; border-radius: 6px; padding: 6px 12px; }}
QPushButton:hover {{ border-color: {ACCENT}; background: #f7fbfe; }}
QPushButton:pressed {{ background: {ACCENT_SOFT}; }}
QPushButton:disabled {{ color: #9aa6b5; background: #f3f5f8; }}
QPushButton[primary="true"] {{ background: {ACCENT}; color: white; border: 1px solid {ACCENT}; font-weight: 600; }}
QPushButton[primary="true"]:hover {{ background: #1890c4; }}
QPushButton[danger="true"] {{ background: {BAD}; color: white; border: 1px solid {BAD}; font-weight: 600; }}
QPushButton[good="true"] {{ background: {OK}; color: white; border: 1px solid {OK}; font-weight: 600; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: white; border: 1px solid #c9d3e0; border-radius: 5px; padding: 3px 6px; }}
QAbstractSpinBox {{ padding-right: 18px; }}
QAbstractSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; width: 16px;
    border-left: 1px solid {LINE}; border-top-right-radius: 5px; background: #f6f8fb; }}
QAbstractSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; width: 16px;
    border-left: 1px solid {LINE}; border-bottom-right-radius: 5px; background: #f6f8fb; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: {ACCENT_SOFT}; }}
QAbstractSpinBox::up-arrow {{ image: url(@UP@); width: 8px; height: 5px; }}
QAbstractSpinBox::down-arrow {{ image: url(@DOWN@); width: 8px; height: 5px; }}
QAbstractSpinBox::up-arrow:disabled {{ image: url(@UPD@); }}
QAbstractSpinBox::down-arrow:disabled {{ image: url(@DOWND@); }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url(@DOWN@); width: 8px; height: 5px; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QTableWidget, QTableView, QListWidget, QTreeWidget {{ background: white; border: 1px solid {LINE};
    border-radius: 6px; gridline-color: #edf1f6; selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT}; }}
QHeaderView::section {{ background: #f3f6fa; color: {MUTED}; border: none; border-bottom: 1px solid {LINE};
    padding: 5px 6px; font-weight: 600; }}
QProgressBar {{ border: 1px solid {LINE}; border-radius: 5px; background: white; text-align: center; height: 14px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #c3cddb; border-radius: 4px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #c3cddb; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QStatusBar {{ background: {CARD}; border-top: 1px solid {LINE}; color: {MUTED}; }}
QLabel[muted="true"] {{ color: {MUTED}; }}
QLabel[h2="true"] {{ font-size: 15px; font-weight: 700; color: {TEXT}; }}
QFrame#header {{ background: {NAVY}; }}
QFrame#header QLabel {{ color: #e8eef6; }}
QFrame#card {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 8px; }}
QSplitter::handle {{ background: {BG}; }}
"""


def _with_arrows(style):
    """Small arrow images for spin boxes / combo boxes (drawn once into a temp folder)."""
    import tempfile
    d = os.path.join(tempfile.gettempdir(), "okrdrum_ui")
    os.makedirs(d, exist_ok=True)
    paths = {}
    for name, up, col in (("UP", True, MUTED), ("DOWN", False, MUTED), ("UPD", True, "#c3cddb"),
                          ("DOWND", False, "#c3cddb")):
        p = os.path.join(d, "arrow_%s.png" % name.lower())
        img = QtGui.QImage(16, 10, QtGui.QImage.Format_ARGB32)
        img.fill(QtCore.Qt.transparent)
        q = QtGui.QPainter(img)
        q.setRenderHint(QtGui.QPainter.Antialiasing)
        q.setPen(QtCore.Qt.NoPen)
        q.setBrush(QtGui.QColor(col))
        pts = [QtCore.QPointF(1, 9), QtCore.QPointF(15, 9), QtCore.QPointF(8, 1)] if up else \
              [QtCore.QPointF(1, 1), QtCore.QPointF(15, 1), QtCore.QPointF(8, 9)]
        q.drawPolygon(QtGui.QPolygonF(pts))
        q.end()
        img.save(p)
        paths[name] = p.replace("\\", "/")
    for k in ("UPD", "DOWND", "UP", "DOWN"):
        style = style.replace("@%s@" % k, paths[k])
    return style


def button(text, kind=None, slot=None, tip=None):
    b = QtWidgets.QPushButton(text)
    if kind:
        b.setProperty(kind, True)
    if slot:
        b.clicked.connect(slot)
    if tip:
        b.setToolTip(tip)
    return b


def header(title, subtitle=""):
    """Slim navy strip with the logo, app name and a subtitle label (returned for updating)."""
    f = QtWidgets.QFrame()
    f.setObjectName("header")
    f.setFixedHeight(54)
    h = QtWidgets.QHBoxLayout(f)
    h.setContentsMargins(14, 6, 14, 6)
    logo = QtWidgets.QLabel()
    if os.path.exists(icon_path()):
        logo.setPixmap(QtGui.QPixmap(icon_path()).scaled(38, 38, QtCore.Qt.KeepAspectRatio,
                                                          QtCore.Qt.SmoothTransformation))
    h.addWidget(logo)
    t = QtWidgets.QLabel("<span style='font-size:17px; font-weight:700'>%s</span>" % title)
    h.addWidget(t)
    sub = QtWidgets.QLabel(subtitle)
    sub.setStyleSheet("color:#9fb3cc")
    h.addSpacing(12)
    h.addWidget(sub, 1)
    return f, sub


class Splash(QtWidgets.QWidget):
    """Logo, name, version and a progress bar while the app loads."""

    def __init__(self, version, long_name):
        super().__init__(None, QtCore.Qt.SplashScreen | QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setFixedSize(460, 300)
        self.msg, self.frac = "Starting…", 0.0
        self.pix = QtGui.QPixmap(icon_path(256)) if os.path.exists(icon_path(256)) else None
        self.t0 = time.perf_counter()
        self.version, self.long = version, long_name
        scr = QtGui.QGuiApplication.primaryScreen().availableGeometry()
        self.move(scr.center() - self.rect().center())

    def step(self, msg, frac):
        self.msg, self.frac = msg, frac
        self.repaint()
        QtWidgets.QApplication.processEvents()

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = self.rect().adjusted(2, 2, -2, -2)
        grad = QtGui.QLinearGradient(0, 0, 0, r.height())
        grad.setColorAt(0, QtGui.QColor("#101d3d"))
        grad.setColorAt(1, QtGui.QColor("#060b1a"))
        p.setBrush(grad)
        p.setPen(QtCore.Qt.NoPen)
        p.drawRoundedRect(r, 18, 18)
        if self.pix:
            p.drawPixmap(28, 40, self.pix.scaled(120, 120, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        p.setPen(QtGui.QColor("white"))
        f = p.font()
        f.setPointSize(24)
        f.setBold(True)
        p.setFont(f)
        p.drawText(170, 92, "OKR Drum")
        f.setPointSize(10)
        f.setBold(False)
        p.setFont(f)
        p.setPen(QtGui.QColor("#9fd9f2"))
        p.drawText(QtCore.QRect(170, 104, 270, 44), QtCore.Qt.TextWordWrap, self.long)
        p.setPen(QtGui.QColor("#9fb3cc"))
        p.drawText(170, 166, "version %s" % self.version)
        p.drawText(28, 236, self.msg)
        p.setBrush(QtGui.QColor("#24386a"))
        p.drawRoundedRect(28, 250, r.width() - 56, 8, 4, 4)
        p.setBrush(QtGui.QColor(ACCENT))
        p.drawRoundedRect(28, 250, int((r.width() - 56) * max(0.02, min(1, self.frac))), 8, 4, 4)
        p.end()


def card(layout=None):
    f = QtWidgets.QFrame()
    f.setObjectName("card")
    if layout is not None:
        f.setLayout(layout)
    return f

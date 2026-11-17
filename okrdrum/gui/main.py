"""OKR Drum main window."""
from __future__ import annotations

import os
import sys

from PySide6 import QtCore, QtGui, QtWidgets

from .. import APP_LONG, APP_NAME, __version__
from . import theme
from .widgets import SETTINGS_DIR, load_settings, save_settings, show_in_folder


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.setWindowTitle("%s  %s" % (APP_NAME, __version__))
        self.resize(1440, 900)
        from .analyze_tab import AnalyzeTab
        from .project_tab import ProjectTab
        from .results_tab import ResultsTab
        from .rig_tab import RigTab
        from .stimulus_tab import StimulusTab
        cw = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(cw)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        head, self.head_sub = theme.header(APP_NAME, APP_LONG)
        v.addWidget(head)
        body = QtWidgets.QWidget()
        bl = QtWidgets.QVBoxLayout(body)
        bl.setContentsMargins(10, 8, 10, 6)
        self.tabs = QtWidgets.QTabWidget()
        bl.addWidget(self.tabs)
        v.addWidget(body, 1)
        self.setCentralWidget(cw)
        self.rig_tab = RigTab(self)          # first: the others read the rig
        self.stim_tab = StimulusTab(self)
        self.analyze_tab = AnalyzeTab(self)
        self.results_tab = ResultsTab(self)
        self.project_tab = ProjectTab(self)
        for w, name in ((self.stim_tab, "Stimulus"), (self.rig_tab, "Rig"), (self.analyze_tab, "Analyze"),
                        (self.results_tab, "Results"), (self.project_tab, "Project")):
            self.tabs.addTab(w, name)
        self.analyze_tab.analysed.connect(self.results_tab.set_session)
        self.project_tab.changed.connect(self._project_changed)
        self.stim_tab.run_finished.connect(lambda p: self.analyze_tab.stim.set(p))
        self._menus()
        self.statusBar().showMessage("Ready")
        self._project_changed()

    def _menus(self):
        mb = self.menuBar()
        m = mb.addMenu("File")
        m.addAction("New project…", self.project_tab.new)
        m.addAction("Open project…", self.project_tab.open)
        m.addAction("Save project", self.project_tab.save, QtGui.QKeySequence.Save)
        m.addSeparator()
        m.addAction("Quit", self.close, QtGui.QKeySequence.Quit)
        m = mb.addMenu("Tools")
        m.addAction("Camera calibration…", lambda: self.open_calibration(self.analyze_tab.video.path(),
                                                                        target=self.analyze_tab.cal))
        m.addAction("Luminance && gamma…", self.rig_tab.luminance)
        m.addAction("Show alignment lines on the drum", lambda: self.rig_tab.show_pattern(3))
        m.addAction("Close drum pattern", self.rig_tab.close_pattern)
        m.addSeparator()
        m.addAction("Sync check of the current session", self._sync)
        m.addAction("Find DeepLabCut environments", lambda: (self.tabs.setCurrentWidget(self.analyze_tab),
                                                             self.analyze_tab._find_envs()))
        m.addAction("Load demo session (synthetic)", lambda: (self.tabs.setCurrentWidget(self.analyze_tab),
                                                              self.analyze_tab.demo()))
        m = mb.addMenu("Help")
        m.addAction("About OKR Drum", self.about)
        m.addAction("Run self-test…", self.run_selftest)
        m.addAction("Open settings folder", lambda: show_in_folder(SETTINGS_DIR))

    def _sync(self):
        self.tabs.setCurrentWidget(self.analyze_tab)
        self.analyze_tab.sync_check()

    def _project_changed(self):
        p = self.project_tab.project
        n = len(p.data["sessions"])
        self.head_sub.setText("%s  ·  project: %s (%d session%s)" % (
            APP_LONG, os.path.basename(p.path) if p.path else "unsaved", n, "" if n == 1 else "s"))

    # ------------------------------------------------------------------ shared helpers
    def rig(self):
        return self.rig_tab.rig()

    def status(self, msg):
        self.statusBar().showMessage(msg, 15000)

    def current_meta(self):
        return self.stim_tab.meta()

    def save_all(self):
        self.settings.update(rig=self.rig().to_dict(), protocol=self.stim_tab.protocol(), meta=self.stim_tab.meta(),
                             serial_port=self.stim_tab.port.currentData() or "none")
        save_settings(self.settings)

    def open_calibration(self, video=None, target=None):
        from .calibration_tool import CalibrationTool
        self._calib = CalibrationTool(self, video if video and os.path.exists(video) else None, target)
        self._calib.show()

    def about(self):
        QtWidgets.QMessageBox.about(
            self, "About OKR Drum",
            "<h3>OKR Drum %s</h3><p>%s</p><p>Four-monitor optokinetic drum: warped drifting gratings drawn with "
            "OpenGL, trial markers to the Raspberry Pi camera recorder, DeepLabCut-based head tracking, "
            "gaze-on-screen and optokinetic response analysis.</p><p>Gergely Szarka, University of Pécs - "
            "MIT licence<br><a href='https://github.com/jerjely/OKR-Drum'>github.com/jerjely/OKR-Drum</a></p>"
            % (__version__, APP_LONG))

    def run_selftest(self):
        from .. import selftest
        import tempfile
        out = os.path.join(tempfile.gettempdir(), "okr_drum_selftest.txt")
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        code = selftest.run(out, gui=False)
        QtWidgets.QApplication.restoreOverrideCursor()
        with open(out, encoding="utf-8") as f:
            txt = f.read()
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Self-test %s" % ("passed" if code == 0 else "FAILED"))
        box.setText("Self-test %s. Details:" % ("passed" if code == 0 else "found problems"))
        box.setDetailedText(txt)
        box.exec()

    def closeEvent(self, ev):
        if self.stim_tab.runner.running:
            if QtWidgets.QMessageBox.question(self, "Quit", "A run is in progress. Stop it and quit?") != \
                    QtWidgets.QMessageBox.Yes:
                ev.ignore()
                return
            self.stim_tab.runner.stop("stopped (app closed)")
        self.rig_tab.close_pattern()
        self.save_all()
        super().closeEvent(ev)


def set_windows_app_id():
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("io.github.jerjely.okrdrum")
        except Exception:
            pass


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    if sys.stdout is None:          # windowed build on Windows has no console
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    if "--version" in argv:
        print(__version__)
        return 0
    if "--selftest" in argv:
        from .. import selftest
        i = argv.index("--selftest")
        out = argv[i + 1] if len(argv) > i + 1 and not argv[i + 1].startswith("--") else "selftest.txt"
        return selftest.run(out, gui=True)
    set_windows_app_id()
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_ShareOpenGLContexts)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    theme.apply_theme(app)
    splash = None
    if "--no-splash" not in argv:
        splash = theme.Splash(__version__, APP_LONG)
        splash.show()
        for msg, frac, mod in (("Loading NumPy and SciPy…", 0.15, "scipy.signal"), ("Loading pandas…", 0.35, "pandas"),
                               ("Loading OpenCV…", 0.5, "cv2"), ("Loading plots…", 0.7, "matplotlib.figure"),
                               ("Loading pyqtgraph…", 0.85, "pyqtgraph")):
            splash.step(msg, frac)
            __import__(mod)
        splash.step("Opening the window…", 0.95)
    w = MainWindow()
    w.show()
    if splash:
        splash.close()
    return app.exec()

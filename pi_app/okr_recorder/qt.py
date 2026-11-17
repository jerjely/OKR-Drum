"""Qt binding: PyQt5 on Raspberry Pi OS (python3-pyqt5); PySide6 / PyQt6 elsewhere (tests)."""
try:
    from PyQt5 import QtCore, QtGui, QtWidgets          # noqa: F401
    Signal = QtCore.pyqtSignal
    API = "PyQt5"
except ImportError:
    try:
        from PySide6 import QtCore, QtGui, QtWidgets    # noqa: F401
        Signal = QtCore.Signal
        API = "PySide6"
    except ImportError:
        from PyQt6 import QtCore, QtGui, QtWidgets      # noqa: F401
        Signal = QtCore.pyqtSignal
        API = "PyQt6"

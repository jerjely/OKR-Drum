# PyInstaller spec for OKR Drum (Windows folder build / macOS .app / Linux test build).
# Build from the repository root:   pyinstaller install/okr_drum.spec --noconfirm
import os
import re
import sys

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
sys.path.insert(0, ROOT)
with open(os.path.join(ROOT, "okrdrum", "version.py")) as f:
    VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', f.read()).group(1)
# macOS wants a dotted number
PLIST_VERSION = ".".join((re.findall(r"\d+", VERSION) + ["0", "0", "0"])[:3])

datas = [
    (os.path.join(ROOT, "assets", "icon", "okr_drum_256.png"), os.path.join("assets", "icon")),
    (os.path.join(ROOT, "assets", "icon", "okr_drum_512.png"), os.path.join("assets", "icon")),
    (os.path.join(ROOT, "assets", "icon", "okr_drum.ico"), os.path.join("assets", "icon")),
    (os.path.join(ROOT, "README.md"), "."),
    (os.path.join(ROOT, "LICENSE"), "."),
]

hidden = collect_submodules("okrdrum") + [
    "matplotlib.backends.backend_qtagg", "matplotlib.backends.backend_pdf", "matplotlib.backends.backend_agg",
    "scipy.signal", "scipy.interpolate", "tables", "serial", "serial.tools.list_ports",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
] + collect_submodules("pyqtgraph", filter=lambda n: "Template" in n or n.endswith("exporters"))

if sys.platform == "win32":
    icon = os.path.join(ROOT, "assets", "icon", "okr_drum.ico")
elif sys.platform == "darwin":
    icon = os.path.join(ROOT, "assets", "icon", "okr_drum.icns")
else:
    icon = None

a = Analysis(
    [os.path.join(ROOT, "okr_drum.py")],
    pathex=[ROOT],
    datas=datas,
    hiddenimports=hidden,
    excludes=["tkinter", "PyQt5", "PyQt6", "IPython", "jupyter", "notebook", "deeplabcut", "tensorflow",
              "torch", "psychopy", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
              "PySide6.QtQuick3D", "PySide6.QtMultimedia"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="OKR-Drum",
    console=False,
    icon=icon,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="OKR-Drum", upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="OKR-Drum.app",
        icon=icon,
        bundle_identifier="io.github.jerjely.okrdrum",
        info_plist={
            "CFBundleName": "OKR Drum",
            "CFBundleDisplayName": "OKR Drum",
            "CFBundleShortVersionString": PLIST_VERSION,
            "CFBundleVersion": PLIST_VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "NSHumanReadableCopyright": "MIT licence, Gergely Szarka",
        },
    )

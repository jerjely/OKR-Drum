"""
Builds the release downloads, one zip per part:

    <App>-<version>-Stimulus.zip     lab PC: PsychoPy grating experiment + install/run scripts
    <App>-<version>-RaspberryPi.zip  camera recorder for the Raspberry Pi
    <App>-<version>-Analysis.zip     lens calibration + DeepLabCut -> cm conversion
    <App>-<version>-Hardware.zip     build drawing and wiring notes

The version is written into every script (__version__ = "...").

    python tools/make_release_zips.py --version 1.0.0 [--app OKR-Drum] [--out dist]
"""
import argparse
import os
import re
import stat
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICON = 'assets/icon/'

# part name -> list of (source path in repo, name inside the zip)
PARTS = {
    'Stimulus': [
        ('stimulus/okr_gui_experiment.py', 'okr_gui_experiment.py'),
        ('stimulus/run_okr.bat', 'run_okr.bat'),
        ('stimulus/install_windows.bat', 'install_windows.bat'),
        ('stimulus/install_mac.command', 'install_mac.command'),
        ('stimulus/run_okr.command', 'run_okr.command'),
        ('stimulus/requirements.txt', 'requirements.txt'),
        ('stimulus/README.md', 'README.md'),
        (ICON + 'okr_drum_256.png', 'okr_drum.png'),
        (ICON + 'okr_drum.ico', 'okr_drum.ico'),
        (ICON + 'okr_drum.icns', 'okr_drum.icns'),
        ('LICENSE', 'LICENSE.txt'),
    ],
    'RaspberryPi': [
        ('raspberry_pi/okr_record_pi.py', 'okr_record_pi.py'),
        ('raspberry_pi/install_pi.sh', 'install_pi.sh'),
        ('raspberry_pi/README.md', 'README.md'),
        (ICON + 'okr_drum_256.png', 'okr_drum.png'),
        ('LICENSE', 'LICENSE.txt'),
    ],
    'Analysis': [
        ('analysis/okr_camera_calibration.py', 'okr_camera_calibration.py'),
        ('analysis/requirements.txt', 'requirements.txt'),
        ('analysis/README.md', 'README.md'),
        ('LICENSE', 'LICENSE.txt'),
    ],
    'Hardware': [
        ('hardware/okr_drum_blueprint.pdf', 'okr_drum_blueprint.pdf'),
        ('hardware/README.md', 'README.md'),
        ('LICENSE', 'LICENSE.txt'),
    ],
}
EXECUTABLE = ('.command', '.sh')
VERSION_RE = re.compile(r'^__version__ = "[^"]*"', re.M)


def file_bytes(src, version):
    data = open(os.path.join(ROOT, src), 'rb').read()
    if src.endswith('.py'):
        text = data.decode('utf-8')
        new, n = VERSION_RE.subn('__version__ = "%s"' % version, text)
        if n != 1:
            sys.exit('%s: expected exactly one __version__ line, found %d' % (src, n))
        data = new.encode('utf-8')
    if src.endswith('.bat'):          # Windows batch files need CRLF line endings
        data = data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
    elif src.endswith(EXECUTABLE):    # shell scripts must have LF
        data = data.replace(b'\r\n', b'\n')
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--version', required=True)
    ap.add_argument('--app', default='OKR-Drum')
    ap.add_argument('--out', default='dist')
    a = ap.parse_args()
    if not re.fullmatch(r'\d+\.\d+\.\d+([.+-][0-9A-Za-z.+-]+)?', a.version):
        sys.exit('version must look like 1.0.0 (got %r)' % a.version)
    os.makedirs(a.out, exist_ok=True)
    for part, files in PARTS.items():
        folder = '%s-%s' % (a.app, part)
        path = os.path.join(a.out, '%s-%s-%s.zip' % (a.app, a.version, part))
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
            for src, name in files:
                info = zipfile.ZipInfo('%s/%s' % (folder, name), date_time=(2026, 1, 1, 0, 0, 0))
                mode = 0o755 if name.endswith(EXECUTABLE) else 0o644
                info.external_attr = (stat.S_IFREG | mode) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, file_bytes(src, a.version))
            info = zipfile.ZipInfo('%s/VERSION.txt' % folder, date_time=(2026, 1, 1, 0, 0, 0))
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            z.writestr(info, '%s %s (%s)\n' % (a.app, a.version, part))
        print('wrote', path, '(%d files)' % (len(files) + 1))


if __name__ == '__main__':
    main()

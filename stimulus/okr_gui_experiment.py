"""
OKR drum - grating experiment with a settings window (run with plain Python)

    conda activate okr
    python okr_gui_experiment.py

Settings window
- Contrast, bar width and speed: tick "range" to enter start / end / interval;
  untick for a single value. Every combination of the values is run, stepping
  through the ranges in order (or shuffled within each repeat, if chosen).
- Serial port: pick from the ports found on this PC ("Refresh" rescans).
- Monitor / rig: screen, resolution and arena geometry.

During a run: SPACE starts each trial, ESC stops the run (data so far is saved)
and returns to the settings window. Close / Cancel the window to quit.

Self-test (no rig needed):  python okr_gui_experiment.py --selftest
                   with PsychoPy drawing too:  ... --selftest --render
"""
import csv
import itertools
import json
import math
import os
import random
import sys
import time

import numpy as np
# PsychoPy is imported only when a run starts (see run()), so the settings window,
# the self-test and the analysis of trial lists work without it.

try:
    from PyQt6 import QtCore, QtGui, QtWidgets
    QT6 = True
except ImportError:
    from PyQt5 import QtCore, QtGui, QtWidgets
    QT6 = False

__version__ = "dev"         # replaced with the release tag by the GitHub build
APP_NAME = "OKR Drum"
HERE = os.path.dirname(os.path.abspath(__file__))
MEAN_GREY = 0.0             # -1 black, 0 mid-grey, 1 white
SETTINGS_FILE = 'okr_last_settings.json'

DEFAULTS = {
    'animal_id': '', 'session': '1',
    'edge': 'straight (square bars)',
    'contrast': {'range': False, 'value': 1.0, 'start': 0.1, 'end': 1.0, 'step': 0.1},
    'bar_width': {'range': False, 'value': 5.0, 'start': 1.25, 'end': 5.0, 'step': 1.25},
    'speed': {'range': False, 'value': 12.0, 'start': 4.0, 'end': 20.0, 'step': 4.0},
    'direction': 'both (CW and CCW)',
    'duration': 10.0, 'repeats': 1, 'order': 'sequential',
    'serial_port': 'none',
    'screen': 1, 'res_w': 1024, 'res_h': 768, 'fullscreen': True,
    'vis_w': 40.98, 'vis_h': 23.0, 'dist': 21.35, 'seam': 1.65, 'seam_side': 'left',
}
PARAMS = [  # key, label, unit, min, max, decimals, spin step
    ('contrast', 'Contrast', '', 0.0, 1.0, 3, 0.05),
    ('bar_width', 'Bar width', 'deg', 0.1, 45.0, 3, 0.25),
    ('speed', 'Speed', 'deg/s', 0.0, 500.0, 2, 1.0),
]
DIRECTIONS = {'both (CW and CCW)': [1, -1], 'CW only': [1], 'CCW only': [-1]}


# ------------------------------------------------------------------ helpers
if QT6:
    BTN_OK = QtWidgets.QDialogButtonBox.StandardButton.Ok
    BTN_CANCEL = QtWidgets.QDialogButtonBox.StandardButton.Cancel
    MB_YES = QtWidgets.QMessageBox.StandardButton.Yes
    MB_NO = QtWidgets.QMessageBox.StandardButton.No
else:
    BTN_OK, BTN_CANCEL = QtWidgets.QDialogButtonBox.Ok, QtWidgets.QDialogButtonBox.Cancel
    MB_YES, MB_NO = QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.No


def range_values(start, end, step):
    if step <= 0:
        raise ValueError('interval must be > 0')
    if end < start:
        raise ValueError('end must be >= start')
    n = int(math.floor((end - start) / step + 1e-9)) + 1
    return [round(start + i * step, 6) for i in range(n)]


def param_values(p):
    return range_values(p['start'], p['end'], p['step']) if p['range'] else [p['value']]


def cycles_per_screen(bar_width_deg):
    n = max(1, int(round(90.0 / (2.0 * bar_width_deg))))
    return n, 45.0 / n


def build_trials(s):
    contrasts = param_values(s['contrast'])
    widths = param_values(s['bar_width'])
    speeds = param_values(s['speed'])
    dirs = DIRECTIONS[s['direction']]
    combos = list(itertools.product(contrasts, widths, speeds, dirs))
    trials = []
    for rep in range(int(s['repeats'])):
        block = list(combos)
        if s['order'] == 'random':
            random.shuffle(block)
        for c, w, v, d in block:
            trials.append({'repeat': rep + 1, 'contrast': c, 'bar_width_requested_deg': w,
                           'speed_deg_s': v, 'direction': 'CW' if d > 0 else 'CCW', 'dir_sign': d})
    return trials


def list_serial_ports():
    try:
        from serial.tools import list_ports
        return [(p.device, '%s  -  %s' % (p.device, p.description)) for p in list_ports.comports()]
    except Exception:
        return []


def load_settings():
    s = json.loads(json.dumps(DEFAULTS))
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE) as f:
                old = json.load(f)
            for k, v in old.items():
                if k in s and type(v) == type(s[k]):
                    if isinstance(v, dict):
                        s[k].update({kk: vv for kk, vv in v.items() if kk in s[k]})
                    else:
                        s[k] = v
        except Exception:
            pass
    return s


# ------------------------------------------------------------------ settings window
def icon_path():
    for p in (os.path.join(HERE, 'okr_drum.png'),
              os.path.join(HERE, '..', 'assets', 'icon', 'okr_drum_256.png')):
        if os.path.exists(p):
            return p
    return None


def set_windows_taskbar_id():
    """So Windows shows the OKR Drum icon in the taskbar instead of Python's."""
    if sys.platform.startswith('win'):
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('jerjely.OKRDrum.Stimulus')
        except Exception:
            pass


class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, s):
        super().__init__()
        self.setWindowTitle('%s - grating experiment  (v%s)' % (APP_NAME, __version__))
        if icon_path():
            self.setWindowIcon(QtGui.QIcon(icon_path()))
        self.s = s
        outer = QtWidgets.QVBoxLayout(self)
        content = QtWidgets.QWidget()
        cols = QtWidgets.QHBoxLayout(content)
        cols.setContentsMargins(0, 0, 0, 0)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame if QT6 else QtWidgets.QFrame.NoFrame)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        self._content = content
        lay = QtWidgets.QVBoxLayout()          # left column: session, stimulus, preview
        right = QtWidgets.QVBoxLayout()        # right column: sync, monitor / rig
        cols.addLayout(lay, 3)
        cols.addLayout(right, 2)

        # session
        box = QtWidgets.QGroupBox('Session')
        f = QtWidgets.QFormLayout(box)
        self.animal = QtWidgets.QLineEdit(s['animal_id'])
        self.session = QtWidgets.QLineEdit(s['session'])
        f.addRow('Animal ID', self.animal)
        f.addRow('Session', self.session)
        lay.addWidget(box)

        # stimulus
        box = QtWidgets.QGroupBox('Stimulus')
        g = QtWidgets.QGridLayout(box)
        self.edge = self._combo(['straight (square bars)', 'sine'], s['edge'])
        g.addWidget(QtWidgets.QLabel('Edge'), 0, 0)
        g.addWidget(self.edge, 0, 1, 1, 3)
        for col, txt in enumerate(['', 'range', 'value', 'start', 'end', 'interval'], start=0):
            if txt:
                g.addWidget(QtWidgets.QLabel('<b>%s</b>' % txt), 1, col)
        self.pw = {}
        for row, (key, label, unit, lo, hi, dec, step) in enumerate(PARAMS, start=2):
            p = s[key]
            w = {'chk': QtWidgets.QCheckBox()}
            w['chk'].setChecked(p['range'])
            for fld in ('value', 'start', 'end', 'step'):
                sb = QtWidgets.QDoubleSpinBox()
                sb.setDecimals(dec)
                sb.setRange(lo if fld != 'step' else 10 ** -dec, hi)
                sb.setSingleStep(step)
                sb.setValue(p[fld])
                if unit:
                    sb.setSuffix(' ' + unit)
                sb.valueChanged.connect(self.update_preview)
                w[fld] = sb
            w['chk'].toggled.connect(self.update_enabled)
            g.addWidget(QtWidgets.QLabel(label), row, 0)
            g.addWidget(w['chk'], row, 1)
            for col, fld in enumerate(('value', 'start', 'end', 'step'), start=2):
                g.addWidget(w[fld], row, col)
            self.pw[key] = w
        r = len(PARAMS) + 2
        self.direction = self._combo(list(DIRECTIONS), s['direction'])
        self.duration = self._dspin(0.1, 3600, 1, s['duration'], ' s')
        self.repeats = QtWidgets.QSpinBox()
        self.repeats.setRange(1, 1000)
        self.repeats.setValue(int(s['repeats']))
        self.order = self._combo(['sequential', 'random'], s['order'])
        for i, (lab, wid) in enumerate([('Direction', self.direction), ('Grating duration', self.duration),
                                        ('Repeats', self.repeats), ('Order', self.order)]):
            g.addWidget(QtWidgets.QLabel(lab), r + i, 0)
            g.addWidget(wid, r + i, 1, 1, 3)
        for wid in (self.direction, self.order):
            wid.currentIndexChanged.connect(self.update_preview)
        self.repeats.valueChanged.connect(self.update_preview)
        self.duration.valueChanged.connect(self.update_preview)
        lay.addWidget(box)

        # preview (shown in the right column, below the rig settings)
        self.preview = QtWidgets.QLabel()
        self.preview.setWordWrap(True)

        # sync
        box = QtWidgets.QGroupBox('Sync')
        h = QtWidgets.QHBoxLayout(box)
        self.port = QtWidgets.QComboBox()
        btn = QtWidgets.QPushButton('Refresh')
        btn.clicked.connect(self.fill_ports)
        h.addWidget(QtWidgets.QLabel('Serial port'))
        h.addWidget(self.port, 1)
        h.addWidget(btn)
        self.fill_ports()
        right.addWidget(box)

        # rig
        box = QtWidgets.QGroupBox('Monitor / rig')
        f = QtWidgets.QFormLayout(box)
        self.screen = QtWidgets.QSpinBox()
        self.screen.setRange(1, 8)
        self.screen.setValue(int(s['screen']))
        self.res_w = QtWidgets.QSpinBox()
        self.res_w.setRange(320, 8192)
        self.res_w.setValue(int(s['res_w']))
        self.res_h = QtWidgets.QSpinBox()
        self.res_h.setRange(240, 8192)
        self.res_h.setValue(int(s['res_h']))
        res = QtWidgets.QHBoxLayout()
        res.addWidget(self.res_w)
        res.addWidget(QtWidgets.QLabel('x'))
        res.addWidget(self.res_h)
        self.fullscr = QtWidgets.QCheckBox()
        self.fullscr.setChecked(bool(s['fullscreen']))
        self.vis_w = self._dspin(1, 500, 2, s['vis_w'], ' cm')
        self.vis_h = self._dspin(1, 500, 2, s['vis_h'], ' cm')
        self.dist = self._dspin(1, 500, 2, s['dist'], ' cm')
        self.seam = self._dspin(0, 50, 2, s['seam'], ' cm')
        self.seam_side = self._combo(['left', 'right'], s['seam_side'])
        f.addRow('Screen (1 = main)', self.screen)
        f.addRow('Resolution (px)', res)
        f.addRow('Fullscreen', self.fullscr)
        f.addRow('Visible screen width', self.vis_w)
        f.addRow('Visible screen height', self.vis_h)
        f.addRow('Distance centre to screen', self.dist)
        f.addRow('Bezel at seam', self.seam)
        f.addRow('Seam side (from pedestal)', self.seam_side)
        right.addWidget(box)
        right.addWidget(self.preview)
        right.addStretch(1)
        lay.addStretch(1)

        bb = QtWidgets.QDialogButtonBox(BTN_OK | BTN_CANCEL)
        bb.button(BTN_OK).setText('Start run')
        bb.button(BTN_CANCEL).setText('Quit')
        bb.accepted.connect(self.try_accept)
        bb.rejected.connect(self.reject)
        about = bb.addButton('About', QtWidgets.QDialogButtonBox.ButtonRole.HelpRole if QT6
                             else QtWidgets.QDialogButtonBox.HelpRole)
        about.clicked.connect(self.show_about)
        outer.addWidget(bb)          # outside the scroll area: always visible
        self.update_enabled()
        self.fit_to_screen()

    def fit_to_screen(self):
        """Size and place the window inside the screen area not covered by the taskbar."""
        try:
            scr = QtWidgets.QWidget.screen(self) or QtWidgets.QApplication.primaryScreen()
        except AttributeError:   # very old Qt
            scr = QtWidgets.QApplication.primaryScreen()
        avail = scr.availableGeometry()
        hint = self._content.sizeHint()
        w = min(hint.width() + 40, avail.width() - 20)
        h = min(hint.height() + 90, avail.height() - 50)   # room for title bar and buttons
        self.resize(w, h)
        self.move(avail.x() + (avail.width() - w) // 2, avail.y() + 5)

    def show_about(self):
        QtWidgets.QMessageBox.about(
            self, 'About %s' % APP_NAME,
            '<b>%s</b> &nbsp; version %s<br><br>'
            'Four-monitor optokinetic drum: warped drifting gratings, '
            'trial markers to the Raspberry Pi camera.<br><br>'
            'Gergely Szarka, University of Pecs - MIT licence<br>'
            '<a href="https://github.com/jerjely/OKR-Drum">github.com/jerjely/OKR-Drum</a>'
            % (APP_NAME, __version__))

    def _combo(self, items, current):
        c = QtWidgets.QComboBox()
        c.addItems(items)
        if current in items:
            c.setCurrentIndex(items.index(current))
        return c

    def _dspin(self, lo, hi, dec, val, suffix=''):
        sb = QtWidgets.QDoubleSpinBox()
        sb.setRange(lo, hi)
        sb.setDecimals(dec)
        sb.setValue(float(val))
        sb.setSuffix(suffix)
        return sb

    def fill_ports(self):
        cur = self.port.currentData() if self.port.count() else self.s['serial_port']
        self.port.clear()
        self.port.addItem('none (no sync)', 'none')
        for dev, desc in list_serial_ports():
            self.port.addItem(desc, dev)
        idx = self.port.findData(cur)
        self.port.setCurrentIndex(idx if idx >= 0 else 0)

    def update_enabled(self):
        for w in self.pw.values():
            on = w['chk'].isChecked()
            w['value'].setEnabled(not on)
            for fld in ('start', 'end', 'step'):
                w[fld].setEnabled(on)
        self.update_preview()

    def collect(self):
        s = {'animal_id': self.animal.text().strip(), 'session': self.session.text().strip() or '1',
             'edge': self.edge.currentText(), 'direction': self.direction.currentText(),
             'duration': self.duration.value(), 'repeats': self.repeats.value(),
             'order': self.order.currentText(), 'serial_port': self.port.currentData() or 'none',
             'screen': self.screen.value(), 'res_w': self.res_w.value(), 'res_h': self.res_h.value(),
             'fullscreen': self.fullscr.isChecked(), 'vis_w': self.vis_w.value(), 'vis_h': self.vis_h.value(),
             'dist': self.dist.value(), 'seam': self.seam.value(), 'seam_side': self.seam_side.currentText()}
        for key, w in self.pw.items():
            s[key] = {'range': w['chk'].isChecked(), 'value': w['value'].value(),
                      'start': w['start'].value(), 'end': w['end'].value(), 'step': w['step'].value()}
        return s

    def update_preview(self, *_):
        try:
            s = self.collect()
            parts = []
            for key, label, unit, *_r in PARAMS:
                vals = param_values(s[key])
                txt = ', '.join('%g' % v for v in vals[:8]) + (' ... (%d values)' % len(vals) if len(vals) > 8 else '')
                parts.append('%s: %s %s' % (label, txt, unit))
            widths = param_values(s['bar_width'])
            rounded = ['%g->%.3f' % (w, cycles_per_screen(w)[1]) for w in widths
                       if abs(cycles_per_screen(w)[1] - w) > 1e-3]
            n = len(build_trials(s))
            msg = '<b>%d trials</b> (%.1f min of grating)<br>%s' % (n, n * s['duration'] / 60, '<br>'.join(parts))
            if rounded:
                msg += '<br><i>Bar widths rounded to fit whole cycles per screen: %s</i>' % ', '.join(rounded[:6])
            self.preview.setText(msg)
        except Exception as e:
            self.preview.setText('<span style="color:#c00">%s</span>' % e)

    def try_accept(self):
        s = self.collect()
        try:
            if not build_trials(s):
                raise ValueError('No trials')
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, 'Check the settings', str(e))
            return
        mismatch = s['vis_w'] + s['seam'] - 2 * s['dist']
        if abs(mismatch) > 0.3:
            yes, no = MB_YES, MB_NO
            ans = QtWidgets.QMessageBox.question(
                self, 'Geometry check',
                'Visible width + bezel = %.2f cm, but 2 x distance = %.2f cm.\n'
                'Stripes will not line up at the corners.\n\nRun anyway?'
                % (s['vis_w'] + s['seam'], 2 * s['dist']), yes | no)
            if ans != yes:
                return
        self.s = s
        self.accept()


def get_settings(app):
    s = load_settings()
    dlg = SettingsDialog(s)
    ok = (dlg.exec() if hasattr(dlg, 'exec') else dlg.exec_())
    if not ok:
        return None, None
    s = dlg.s
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(s, f, indent=1)
    return s, build_trials(s)


# ------------------------------------------------------------------ experiment
def screen_azimuths(width_px, s):
    x_left = -s['dist'] + (s['seam'] if s['seam_side'] == 'left' else 0.0)
    x = x_left + (np.arange(width_px) + 0.5) * s['vis_w'] / width_px
    return np.degrees(np.arctan(x / s['dist']))


def run(s, trials):
    from psychopy import core, logging, visual
    from psychopy.hardware import keyboard
    duration = float(s['duration'])
    square = s['edge'].startswith('straight')
    os.makedirs('data', exist_ok=True)
    stamp = time.strftime('%Y-%m-%d_%H%M%S')
    base = os.path.join('data', '%s_s%s_%s' % (s['animal_id'] or 'noID', s['session'], stamp))
    logfile = logging.LogFile(base + '.log', level=logging.INFO)
    with open(base + '_settings.json', 'w') as f:
        json.dump(dict(s, app_version=__version__), f, indent=1)

    ser = None
    if s['serial_port'] != 'none':
        import serial
        try:
            ser = serial.Serial(s['serial_port'], 115200)
        except Exception as e:
            print('WARNING: could not open %s (%s) - running without sync' % (s['serial_port'], e))

    win = visual.Window(size=(s['res_w'], s['res_h']), fullscr=s['fullscreen'], screen=s['screen'] - 1,
                        units='pix', color=MEAN_GREY, colorSpace='rgb', allowGUI=False, waitBlanking=True)
    win.mouseVisible = False
    win.recordFrameIntervals = True
    W, H = [int(v) for v in win.size]
    fr = win.getActualFrameRate(nIdentical=20, nMaxFrames=200) or 60.0
    if fr > 150:
        fr = 60.0
    if (W, H) != (s['res_w'], s['res_h']):
        print('NOTE: requested %dx%d but the screen is %dx%d - using the actual size.'
              % (s['res_w'], s['res_h'], W, H))
    theta = screen_azimuths(W, s)
    half_v = math.degrees(math.atan(s['vis_h'] / 2.0 / s['dist']))
    print('Each screen: azimuth %.1f to %.1f deg, elevation +/-%.1f deg, %.1f px/deg at centre'
          % (theta[0], theta[-1], half_v, W / s['vis_w'] * s['dist'] * math.pi / 180))
    img = np.full((2, W), MEAN_GREY, dtype=float)
    stim = visual.ImageStim(win, image=img, size=(W, H), units='pix', interpolate=False, colorSpace='rgb')
    kb = keyboard.Keyboard()
    clock = core.Clock()

    fields = ['trial', 'repeat', 'edge', 'contrast', 'bar_width_requested_deg', 'bar_width_used_deg',
              'cycles_per_screen', 'spatial_freq_cpd', 'speed_deg_s', 'temporal_freq_hz', 'direction',
              'duration_s', 'shown_s', 'onset_unix_time', 'frames', 'dropped_frames']
    fcsv = open(base + '.csv', 'w', newline='')
    writer = csv.DictWriter(fcsv, fieldnames=fields)
    writer.writeheader()
    print('\n%d trials, %.1f s grating each, frame rate %.1f Hz, window %dx%d'
          % (len(trials), duration, fr, W, H))

    aborted = False
    for i, tr in enumerate(trials):
        n_cyc, w_used = cycles_per_screen(tr['bar_width_requested_deg'])
        period = 2.0 * w_used
        k = 2.0 * math.pi / period
        print('\nTrial %d/%d  contrast %.3g | bar %.3f deg | %.3g deg/s | %s   -> SPACE to start, ESC to stop'
              % (i + 1, len(trials), tr['contrast'], w_used, tr['speed_deg_s'], tr['direction']))
        kb.clearEvents()
        while True:
            win.flip()
            keys = [key.name for key in kb.getKeys(keyList=['space', 'escape'], waitRelease=False)]
            if 'escape' in keys:
                aborted = True
                break
            if 'space' in keys:
                break
        if aborted:
            break

        win.frameIntervals = []
        onset = [None]
        win.callOnFlip(clock.reset)
        win.callOnFlip(lambda: onset.__setitem__(0, time.time()))
        if ser is not None:
            desc = 'c=%g w=%.3f v=%g %s' % (tr['contrast'], w_used, tr['speed_deg_s'], tr['direction'])
            win.callOnFlip(ser.write, ('T%d %s\n' % (i + 1, desc)).encode())
        frames, t = 0, 0.0
        while True:
            sgn = np.sin(k * (theta - tr['dir_sign'] * tr['speed_deg_s'] * t))
            if square:
                sgn = np.where(sgn >= 0, 1.0, -1.0)
            img[:] = np.clip(MEAN_GREY + tr['contrast'] * sgn, -1, 1)
            stim.image = img.copy()
            stim.draw()
            win.flip()
            frames += 1
            t = clock.getTime()
            if t >= duration:
                break
            if kb.getKeys(keyList=['escape'], waitRelease=False):
                aborted = True
                break
        if ser is not None:
            win.callOnFlip(ser.write, b'E%d\n' % (i + 1))   # grating end marker
        win.flip()

        iv = np.array(win.frameIntervals[1:])
        dropped = int(np.sum(iv > 1.5 / fr)) if iv.size else 0
        writer.writerow({'trial': i + 1, 'repeat': tr['repeat'], 'edge': 'square' if square else 'sine',
                         'contrast': tr['contrast'], 'bar_width_requested_deg': tr['bar_width_requested_deg'],
                         'bar_width_used_deg': round(w_used, 4), 'cycles_per_screen': n_cyc,
                         'spatial_freq_cpd': round(1.0 / period, 5), 'speed_deg_s': tr['speed_deg_s'],
                         'temporal_freq_hz': round(tr['speed_deg_s'] / period, 4), 'direction': tr['direction'],
                         'duration_s': duration, 'shown_s': round(t, 4), 'onset_unix_time': onset[0],
                         'frames': frames, 'dropped_frames': dropped})
        fcsv.flush()
        print('  done: %.2f s, %d frames, %d dropped' % (t, frames, dropped))
        if aborted:
            break

    fcsv.close()
    if ser is not None:
        ser.close()
    logging.flush()
    logging.root.removeTarget(logfile)
    win.close()
    print('\nSaved %s.csv%s\nBack to the settings window.' % (base, '  (stopped early)' if aborted else ''))
    return base


def main():
    set_windows_taskbar_id()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    if icon_path():
        app.setWindowIcon(QtGui.QIcon(icon_path()))
    print('%s stimulus  v%s' % (APP_NAME, __version__))
    while True:
        s, trials = get_settings(app)
        if s is None:
            break
        run(s, trials)
    try:
        from psychopy import core
        core.quit()
    except ImportError:
        pass


# ------------------------------------------------------------------ self-test
def selftest(render=False):
    """Checks the experiment on synthetic settings. Exit code 0 = all good.

    Without --render: trial lists, ranges, bar-width rounding, screen geometry and the
    settings window (offscreen).  With --render (needs PsychoPy and a display, e.g.
    xvfb-run on Linux): two short gratings are drawn by PsychoPy, the drawn stripes are
    compared with the expected warped pattern, the trial CSV is checked and the serial
    markers (T/E) sent to the Raspberry Pi are captured from a stand-in serial port.
    """
    import tempfile
    import types
    fails = []

    def check(cond, msg):
        print(('  ok    ' if cond else '  FAIL  ') + msg)
        if not cond:
            fails.append(msg)

    print('%s stimulus self-test, version %s' % (APP_NAME, __version__))
    check(range_values(0.2, 1.0, 0.2) == [0.2, 0.4, 0.6, 0.8, 1.0], 'range 0.2:1.0:0.2 gives 5 values')
    check(range_values(1.25, 5, 1.25) == [1.25, 2.5, 3.75, 5.0], 'range includes the end value')
    for w, n in ((5, 9), (2.5, 18), (1.25, 36), (45, 1)):
        check(cycles_per_screen(w) == (n, 45.0 / n), 'bar %g deg -> %d cycles per screen' % (w, n))
    check(abs(cycles_per_screen(4.0)[1] - 45.0 / 11) < 1e-9, 'bar 4 deg rounded to 45/11 deg')
    s = json.loads(json.dumps(DEFAULTS))
    s['contrast'].update(range=True, start=0.25, end=1.0, step=0.25)
    s['speed'].update(range=True, start=6, end=12, step=6)
    s['repeats'] = 2
    tr = build_trials(s)
    check(len(tr) == 4 * 1 * 2 * 2 * 2, '4 contrasts x 2 speeds x 2 directions x 2 repeats = 32 trials')
    check([t['contrast'] for t in tr[:4]] == [0.25] * 4, 'ranges are stepped in order')
    s['order'] = 'random'
    random.seed(1)
    tr2 = build_trials(s)
    check(sorted(map(str, tr2[:16])) == sorted(map(str, tr[:16])), 'random order shuffles within a repeat')
    th = screen_azimuths(1024, DEFAULTS)
    check(abs(th[0] + 42.68) < 0.05 and abs(th[-1] - 44.89) < 0.05, 'screen spans -42.7 to +44.9 deg')
    gap = 90 - (th[-1] - th[0])
    check(abs(gap - 2.4) < 0.3, 'bezel seam hides %.2f deg' % gap)

    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    d = SettingsDialog(load_settings())
    d.pw['bar_width']['chk'].setChecked(True)
    check(not d.pw['bar_width']['value'].isEnabled() and d.pw['bar_width']['start'].isEnabled(),
          'range tick switches value/start-end fields')
    check('trials' in d.preview.text(), 'settings window shows the trial preview')
    check(d.port.count() >= 1, 'serial port list is filled')
    check(__version__ in d.windowTitle(), 'window title shows version %s' % __version__)
    d.close()

    if render:
        from psychopy import visual
        from psychopy.hardware import keyboard
        sent = []

        class FakeSerial:
            def __init__(self, *a, **k): pass
            def write(self, b): sent.append(b.decode().strip())
            def close(self): pass

        sys.modules['serial'] = types.SimpleNamespace(Serial=FakeSerial)

        class Key:
            def __init__(self, name): self.name = name

        class FakeKeyboard:
            def __init__(self): self.n = 0
            def clearEvents(self): pass
            def getKeys(self, keyList=None, waitRelease=False):
                self.n += 1
                return [Key('space')] if 'space' in keyList and self.n % 3 == 0 else []

        keyboard.Keyboard = FakeKeyboard
        grabbed = []
        draws = [0]
        orig_flip = visual.Window.flip
        orig_draw = visual.ImageStim.draw

        def draw(stim, *a, **k):          # count grating frames
            draws[0] += 1
            return orig_draw(stim, *a, **k)

        def flip(win, *a, **k):           # grab the 20th grating frame before it is shown
            if not grabbed and draws[0] == 20:
                win.getMovieFrame(buffer='back')
                grabbed.append(np.array(win.movieFrames.pop())[:, :, 0].astype(float))
            return orig_flip(win, *a, **k)

        visual.Window.flip = flip
        visual.ImageStim.draw = draw
        tmp = tempfile.mkdtemp(prefix='okr_selftest_')
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            s = json.loads(json.dumps(DEFAULTS))
            s.update(duration=0.6, fullscreen=False, serial_port='selftest', direction='both (CW and CCW)')
            base = run(s, build_trials(s))
        finally:
            os.chdir(cwd)
            visual.Window.flip = orig_flip
            visual.ImageStim.draw = orig_draw
        rows = list(csv.DictReader(open(os.path.join(tmp, base + '.csv'))))
        check(len(rows) == 2, 'two trials written to the CSV')
        check(all(float(r['shown_s']) >= 0.55 and int(r['frames']) > 10 for r in rows),
              'each grating ran for its duration')
        check([m.split()[0] for m in sent] == ['T1', 'E1', 'T2', 'E2'], 'serial markers T1 E1 T2 E2 sent')
        check(len(grabbed) == 1, 'a drawn frame was captured')
        if grabbed:
            img = grabbed[0]
            col = img[img.shape[0] // 2]
            W = len(col)
            th = screen_azimuths(W, s)
            n, wu = cycles_per_screen(s['bar_width']['value'])
            seen = col > 127
            # direction-dependent phase is unknown at frame 20 -> try all phases, take the best
            best = max(np.mean(seen == (np.sin(2 * np.pi / (2 * wu) * (th - ph)) >= 0))
                       for ph in np.arange(0, 2 * wu, 0.05))
            check(best > 0.97, 'drawn stripes match the warped pattern (%.1f%% of columns)' % (100 * best))
            check(img.std() > 100, 'drawn frame is full-contrast black/white stripes')

    print('\nSELF-TEST %s (%d problem%s)' % ('PASSED' if not fails else 'FAILED', len(fails),
                                             '' if len(fails) == 1 else 's'))
    return 0 if not fails else 1


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(selftest(render='--render' in sys.argv))
    if '--version' in sys.argv:
        print(__version__)
        sys.exit(0)
    main()

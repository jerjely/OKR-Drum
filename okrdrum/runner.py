"""Runs a protocol on the stimulus window: grey interval, SPACE to start, grating for the set
duration with vsync-paced frames, markers to the Pi, one CSV row per trial."""
from __future__ import annotations

import csv
import json
import os
import time

import numpy as np
from PySide6 import QtCore

from . import __version__
from .geometry import Rig
from .protocol import StaircaseRun, build_trials, merged
from .renderer import StimState, make_stim_window, place_on_screen
from .sync import MarkerPort

FIELDS = ["trial", "repeat", "staircase", "edge", "contrast", "bar_width_requested_deg", "bar_width_used_deg",
          "cycles_per_screen", "spatial_freq_cpd", "speed_deg_s", "temporal_freq_hz", "direction",
          "duration_s", "shown_s", "onset_unix_time", "end_unix_time", "frames", "dropped_frames",
          "mean_frame_ms", "response"]


def session_info(meta, protocol=None, stim_log=""):
    from .protocol import summary
    info = {k: meta.get(k, "") for k in ("animal", "session", "treatment", "group") if meta.get(k, "") != ""}
    info.update(date=time.strftime("%Y-%m-%d"), time=time.strftime("%H:%M:%S"), stim_log=stim_log,
                app=__version__)
    if protocol:
        info["protocol"] = summary(protocol)
    return info


class Runner(QtCore.QObject):
    status = QtCore.Signal(str)            # one line for the status bar / log
    trial_started = QtCore.Signal(dict)
    trial_done = QtCore.Signal(dict)
    need_response = QtCore.Signal(dict)    # staircase: operator must press Y or N
    finished = QtCore.Signal(str)          # path of the CSV

    def __init__(self, parent=None):
        super().__init__(parent)
        self.win = None
        self.state = None
        self.running = False

    # ------------------------------------------------------------------ control
    def start(self, protocol, rig: Rig, meta, out_dir, port=None, window=None, refresh_hz=60.0):
        self.p = merged(protocol)
        self.rig = rig
        self.meta = dict(meta)
        self.refresh = refresh_hz
        self.stair = StaircaseRun(self.p) if self.p["mode"] == "staircase" else None
        self.trials = [] if self.stair else build_trials(self.p)
        self.idx = -1
        self.cur = None
        self.phase = "idle"                 # idle | iti | wait | stim | respond | done
        self.phase_t0 = time.perf_counter()
        self.pending_onset = self.pending_end = False
        self.frame_times = []
        self.port = port if isinstance(port, MarkerPort) else MarkerPort(port)
        if self.port.error:
            self.status.emit("Serial port not opened (%s) - running without markers" % self.port.error)
        os.makedirs(out_dir, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d_%H%M%S")
        safe = lambda s: "".join(c if c.isalnum() or c in "-_." else "_" for c in str(s))
        self.base = os.path.join(os.path.abspath(out_dir), "%s_s%s_%s" % (
            safe(self.meta.get("animal") or "noID"), safe(self.meta.get("session") or "1"), stamp))
        with open(self.base + "_settings.json", "w", encoding="utf-8") as f:
            json.dump({"protocol": self.p, "rig": rig.to_dict(), "meta": self.meta, "app_version": __version__,
                       "serial_port": self.port.device}, f, indent=1)
        self.port.session(session_info(self.meta, self.p, os.path.basename(self.base) + ".csv"))
        self.fcsv = open(self.base + ".csv", "w", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(self.fcsv, fieldnames=FIELDS, extrasaction="ignore")
        self.writer.writeheader()
        self.state = StimState(rig)
        self.win = window or make_stim_window(self.state)
        self.win.state = self.state
        self.win.on_before_draw = self._before_draw
        self.win.log.frame.connect(self._frame)
        self.win.key_handler = self._key_event
        if window is None:
            place_on_screen(self.win, rig)
        self.running = True
        self._named = False
        self._last_frame = time.perf_counter()
        self._stall_warned = False
        import collections
        self._recent = collections.deque(maxlen=400)
        # Watchdog: the run normally advances on every drawn frame. If the stimulus window stops
        # drawing (covered by another window, minimised, on a screen that isn't there), keep the
        # run going from the clock and say so, instead of silently freezing.
        self._watch = QtCore.QTimer(self)
        self._watch.setTimerType(QtCore.Qt.PreciseTimer)
        self._watch.timeout.connect(self._watchdog)
        self._watch.start(10)
        self._next()

    def display_rate(self):
        """(frames per second actually drawn over the last second, renderer name)."""
        now = time.perf_counter()
        n = sum(1 for t in self._recent if now - t <= 1.0)
        return float(n), getattr(self.win, "renderer_name", "?")

    def _watchdog(self):
        if not self.running:
            return
        now = time.perf_counter()
        if now - self._last_frame < 0.25:
            return
        if not self._stall_warned:
            self._stall_warned = True
            self.status.emit("The stimulus window is not drawing (covered, minimised or on a missing screen?) - "
                             "the run continues on the clock, but nothing is shown and frames are not counted")
        self._before_draw(now)
        self._frame(now, real=False)

    def key(self, name):
        """space = start trial, escape = stop, y / n = staircase answer."""
        if not self.running:
            return
        if name == "escape":
            self.stop("stopped by the operator")
        elif name == "space" and self.phase in ("wait", "iti") and self.p["wait_for_key"]:
            # during the grey the press is remembered: the grating starts as soon as the grey ends
            self._begin_stim_next_frame = True
            if self.phase == "iti":
                left = max(0.0, self.p["iti"] - (time.perf_counter() - self.phase_t0))
                self.status.emit("Trial %d starts after the grey (%.1f s)" % (self.cur["trial"], left))
        elif name in ("y", "n") and self.phase == "respond":
            self.cur["response"] = "yes" if name == "y" else "no"
            self.stair.respond(name == "y")
            self._write(self.cur)
            self._next()

    def stop(self, why="finished"):
        if not self.running:
            return
        if self.phase == "stim" and self.cur:
            self._finish_trial(time.perf_counter(), aborted=True)
        self.running = False
        self.phase = "done"
        try:
            self._watch.stop()
        except Exception:
            pass
        self.fcsv.close()
        if self.stair:
            with open(self.base + "_staircase.json", "w", encoding="utf-8") as f:
                json.dump(self.stair.results(), f, indent=1)
        self.port.run_end()
        self.port.close()
        try:
            self.win.on_before_draw = None
            self.win.close()
        except Exception:
            pass
        self.status.emit("Run %s - saved %s.csv" % (why, os.path.basename(self.base)))
        self.finished.emit(self.base + ".csv")

    # ------------------------------------------------------------------ internals
    def _key_event(self, ev):
        from PySide6.QtCore import Qt
        names = {Qt.Key_Space: "space", Qt.Key_Escape: "escape", Qt.Key_Y: "y", Qt.Key_N: "n"}
        if ev.key() in names:
            self.key(names[ev.key()])

    def _next(self):
        self.state.mode = 0
        if self.stair:
            self.cur = self.stair.next_trial()
        else:
            self.idx += 1
            self.cur = dict(self.trials[self.idx]) if self.idx < len(self.trials) else None
        if self.cur is None:
            self.stop("finished")
            return
        self.cur["response"] = ""
        self._begin_stim_next_frame = False
        self.phase = "iti" if self.p["iti"] > 0 else ("wait" if self.p["wait_for_key"] else "go")
        self.phase_t0 = time.perf_counter()
        self.status.emit("Trial %d  %s c=%g  %.3f deg  %g deg/s  %s" % (
            self.cur["trial"], self.cur["staircase"] or "", self.cur["contrast"],
            self.cur["bar_width_used_deg"], self.cur["speed_deg_s"], self.cur["direction"])
            + ("  - grey %g s%s" % (self.p["iti"], ", then SPACE" if self.p["wait_for_key"] else "")
               if self.phase == "iti" else "  - SPACE to start"))

    def _before_draw(self, now):
        if not self.running:
            return
        if self.phase == "iti" and now - self.phase_t0 >= self.p["iti"]:
            self.phase = "wait" if self.p["wait_for_key"] else "go"
            if self.phase == "wait":
                self.status.emit("Trial %d ready - SPACE to start" % self.cur["trial"])
        if self.phase == "go" or (self.phase == "wait" and self._begin_stim_next_frame):
            self.state.start_grating(self.cur, t0=now)
            self.phase = "stim"
            self.phase_t0 = now
            self.frame_times = []
            self.pending_onset = True
            self.trial_started.emit(dict(self.cur))
        elif self.phase == "stim" and now - self.phase_t0 >= self.cur["duration_s"]:
            self._finish_trial(now)

    def _frame(self, t, real=True):
        if real:
            self._last_frame = time.perf_counter()
            self._recent.append(self._last_frame)
            if self._stall_warned:
                self._stall_warned = False
                self.status.emit("The stimulus window is drawing again")
        if not getattr(self, "_named", False):
            self._named = True
            self.status.emit("Renderer: %s" % getattr(self.win, "renderer_name", "?"))
        if self.phase == "stim" and real:
            self.frame_times.append(t)
        if self.pending_onset:
            self.pending_onset = False
            self.cur["onset_unix_time"] = time.time()
            self.port.onset(self.cur)
        if self.pending_end:
            self.pending_end = False
            self.cur_done["end_unix_time"] = time.time()
            self.port.end(self.cur_done)
            if self.stair:
                self.phase = "respond"
                self.status.emit("Trial %d: did the mouse track?  Y = yes, N = no" % self.cur_done["trial"])
                self.need_response.emit(dict(self.cur_done))
            else:
                self._write(self.cur_done)
                self._next()

    def _finish_trial(self, now, aborted=False):
        self.state.mode = 0
        ft = np.array(self.frame_times)
        iv = np.diff(ft) if ft.size > 1 else np.array([])
        self.cur["shown_s"] = round(now - self.phase_t0, 4)
        self.cur["frames"] = int(ft.size)
        self.cur["dropped_frames"] = int(np.sum(iv > 1.5 / self.refresh)) if iv.size else 0
        self.cur["mean_frame_ms"] = round(float(iv.mean() * 1000), 3) if iv.size else ""
        self.cur_done = self.cur
        self.phase = "ending"
        self.trial_done.emit(dict(self.cur))
        if aborted:
            self.cur["end_unix_time"] = time.time()
            self.port.end(self.cur)
            self._write(self.cur)
        else:
            self.pending_end = True

    def _write(self, row):
        self.writer.writerow(row)
        self.fcsv.flush()

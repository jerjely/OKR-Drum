"""Experiment protocols: fixed trial lists (values or ranges) and adaptive staircases."""
from __future__ import annotations

import itertools
import json
import math
import random

from .geometry import cycles_per_screen

PARAMS = [  # key, label, unit, min, max, decimals, spin step
    ("contrast", "Contrast", "", 0.0, 1.0, 3, 0.05),
    ("bar_width", "Bar width", "deg", 0.1, 45.0, 3, 0.25),
    ("speed", "Speed", "deg/s", 0.0, 500.0, 2, 1.0),
]
DIRECTIONS = {"both (CW and CCW)": [1, -1], "CW only": [1], "CCW only": [-1]}

DEFAULT_PROTOCOL = {
    "mode": "fixed",                    # fixed | staircase
    "edge": "square",                   # square | sine
    "contrast": {"range": False, "value": 1.0, "start": 0.1, "end": 1.0, "step": 0.1},
    "bar_width": {"range": False, "value": 5.0, "start": 1.25, "end": 5.0, "step": 1.25},
    "speed": {"range": False, "value": 12.0, "start": 4.0, "end": 20.0, "step": 4.0},
    "direction": "both (CW and CCW)",
    "duration": 10.0,
    "iti": 5.0,                         # grey before each trial (s); 0 = wait for SPACE only
    "wait_for_key": True,               # start each trial with SPACE
    "repeats": 1,
    "order": "sequential",              # sequential | random
    # staircase
    "sc_variable": "spatial frequency",  # spatial frequency | contrast
    "sc_start": 0.1,                    # c/deg (or contrast)
    "sc_step": 0.05,                    # first step (c/deg or contrast)
    "sc_min_step": 0.0125,
    "sc_reversals": 6,                  # stop after this many reversals per direction
    "sc_max_trials": 60,
}


def range_values(start, end, step):
    if step <= 0:
        raise ValueError("interval must be > 0")
    if end < start:
        raise ValueError("end must be >= start")
    n = int(math.floor((end - start) / step + 1e-9)) + 1
    return [round(start + i * step, 6) for i in range(n)]


def param_values(p):
    return range_values(p["start"], p["end"], p["step"]) if p["range"] else [p["value"]]


def merged(protocol):
    p = json.loads(json.dumps(DEFAULT_PROTOCOL))
    for k, v in (protocol or {}).items():
        if isinstance(v, dict) and isinstance(p.get(k), dict):
            p[k].update(v)
        elif k in p:
            p[k] = v
    return p


def build_trials(protocol, seed=None):
    """Every combination of the entered values x directions, `repeats` times."""
    p = merged(protocol)
    contrasts, widths, speeds = (param_values(p[k]) for k in ("contrast", "bar_width", "speed"))
    combos = list(itertools.product(contrasts, widths, speeds, DIRECTIONS[p["direction"]]))
    rng = random.Random(seed)
    trials = []
    for rep in range(int(p["repeats"])):
        block = list(combos)
        if p["order"] == "random":
            rng.shuffle(block)
        for c, w, v, d in block:
            trials.append(make_trial(len(trials) + 1, c, w, v, d, p, repeat=rep + 1))
    return trials


def make_trial(n, contrast, bar_width, speed, direction, p, repeat=1, staircase=""):
    ncyc, w_used = cycles_per_screen(bar_width)
    period = 2 * w_used
    return {"trial": n, "repeat": repeat, "edge": p["edge"], "contrast": float(contrast),
            "bar_width_requested_deg": float(bar_width), "bar_width_used_deg": round(w_used, 5),
            "cycles_per_screen": ncyc, "spatial_freq_cpd": round(1 / period, 5),
            "speed_deg_s": float(speed), "temporal_freq_hz": round(speed / period, 4),
            "direction": "CW" if direction > 0 else "CCW", "dir_sign": direction,
            "duration_s": float(p["duration"]), "staircase": staircase}


def summary(protocol):
    p = merged(protocol)
    if p["mode"] == "staircase":
        return ("Staircase on %s, start %g, step %g, %d reversals per direction (max %d trials)"
                % (p["sc_variable"], p["sc_start"], p["sc_step"], p["sc_reversals"], p["sc_max_trials"]))
    tr = build_trials(p, seed=0)
    return "%d trials, %.1f min of grating" % (len(tr), len(tr) * p["duration"] / 60)


# ---------------------------------------------------------------------- staircase
class Staircase:
    """Adaptive threshold for one direction (one eye), OptoMotry-style.

    The operator scores each grating: tracked (yes) or not (no).
    Spatial frequency: yes -> finer grating (+step), no -> coarser (-step).
    Contrast: yes -> lower contrast, no -> higher. The step halves at every reversal
    (down to min_step); the threshold is the mean of the reversal values after the first.
    """

    def __init__(self, variable, start, step, min_step, reversals, direction):
        self.variable, self.value, self.step = variable, float(start), float(step)
        self.min_step, self.n_rev, self.direction = float(min_step), int(reversals), direction
        self.last = None
        self.reversal_values = []
        self.history = []

    def harder(self, yes):
        return 1 if yes else -1     # +1 = make the task harder

    def respond(self, yes):
        self.history.append((self.value, bool(yes)))
        move = self.harder(yes)
        if self.last is not None and move != self.last:
            self.reversal_values.append(self.value)
            self.step = max(self.step / 2, self.min_step)
        self.last = move
        if self.variable == "contrast":
            self.value = min(1.0, max(0.005, self.value - move * self.step))
        else:
            self.value = max(0.005, self.value + move * self.step)

    @property
    def done(self):
        return len(self.reversal_values) >= self.n_rev

    @property
    def threshold(self):
        r = self.reversal_values[1:] if len(self.reversal_values) > 1 else self.reversal_values
        return sum(r) / len(r) if r else float("nan")


class StaircaseRun:
    """Two interleaved staircases (CW and CCW = the two eyes), producing trials on demand."""

    def __init__(self, protocol, seed=None):
        self.p = merged(protocol)
        self.rng = random.Random(seed)
        dirs = DIRECTIONS[self.p["direction"]]
        self.sc = {d: Staircase(self.p["sc_variable"], self.p["sc_start"], self.p["sc_step"],
                                self.p["sc_min_step"], self.p["sc_reversals"], d) for d in dirs}
        self.n = 0
        self.pending = None

    def next_trial(self):
        live = [d for d, s in self.sc.items() if not s.done]
        if not live or self.n >= self.p["sc_max_trials"]:
            return None
        d = self.rng.choice(live)
        s = self.sc[d]
        self.n += 1
        if self.p["sc_variable"] == "contrast":
            c, w = s.value, self.p["bar_width"]["value"]
        else:
            c, w = self.p["contrast"]["value"], 1.0 / (2 * s.value)
        self.pending = d
        t = make_trial(self.n, c, w, self.p["speed"]["value"], d, self.p,
                       staircase="%s %s" % (self.p["sc_variable"], "CW" if d > 0 else "CCW"))
        if self.p["sc_variable"] != "contrast":
            s.value = t["spatial_freq_cpd"]       # follow what is really shown (whole cycles per screen)
        return t

    def respond(self, yes):
        if self.pending is not None:
            self.sc[self.pending].respond(yes)
            self.pending = None

    def results(self):
        return {("CW" if d > 0 else "CCW"): {"threshold": s.threshold, "reversals": s.reversal_values,
                                           "trials": len(s.history), "done": s.done}
                for d, s in self.sc.items()}

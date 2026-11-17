"""DeepLabCut output -> clean keypoints -> head direction, gaze point on the screens.

Keypoints used: nose, left ear, right ear, neck (names are matched loosely, e.g.
'LeftEar', 'ear_left', 'L_ear'). Head direction is the vector from the midpoint of the ears
to the nose; when the nose is missing, from the neck to the ear midpoint. The "gaze line"
is this direction drawn from the ear midpoint; where it meets the drum wall gives the
point on the screens the face points to.
"""
from __future__ import annotations

import os
import re

import numpy as np
import pandas as pd

from ..geometry import ray_to_wall, wall_point_azimuth
from . import calibration as calmod

ROLES = {
    "nose": [r"^nose$", r"snout", r"nose"],
    "left_ear": [r"^(left|l)[_\s-]?ear$", r"^ear[_\s-]?(left|l)$", r"left.*ear", r"ear.*left"],
    "right_ear": [r"^(right|r)[_\s-]?ear$", r"^ear[_\s-]?(right|r)$", r"right.*ear", r"ear.*right"],
    "neck": [r"^neck$", r"neck", r"head[_\s-]?base", r"spine1"],
}


def read_dlc(path):
    """DLC .h5 or .csv -> DataFrame with columns (bodypart, x|y|likelihood)."""
    if path.lower().endswith((".h5", ".hdf5")):
        df = pd.read_hdf(path)
    else:
        df = pd.read_csv(path, header=[0, 1, 2], index_col=0)
    if df.columns.nlevels == 4:                  # multi-animal: take the first individual
        ind = df.columns.get_level_values(1)[0]
        df = df.xs(ind, axis=1, level=1)
    df.columns = df.columns.droplevel(0)         # drop scorer
    return df


def bodyparts(df):
    return list(dict.fromkeys(df.columns.get_level_values(0)))


def auto_map(parts):
    """{'nose': 'Nose', 'left_ear': 'leftear', ...} from the model's bodypart names."""
    out = {}
    for role, pats in ROLES.items():
        for pat in pats:
            hit = [p for p in parts if re.search(pat, p, re.I) and p not in out.values()]
            if hit:
                out[role] = hit[0]
                break
    return out


def clean(xy, lik, threshold=0.6, max_gap=6, median=3):
    """Low-confidence points -> NaN, short gaps interpolated, light median filter."""
    xy = np.array(xy, float)
    xy[np.asarray(lik) < threshold] = np.nan
    s = pd.DataFrame(xy)
    s = s.interpolate(limit=max_gap, limit_area="inside")
    if median and median > 1:
        s = s.rolling(median, center=True, min_periods=1).median()
    return s.to_numpy()


def keypoints_cm(df, mapping, cal, threshold=0.6, max_gap=6):
    """{role: (N,2) cm array} plus the fraction of good frames per role."""
    out, good = {}, {}
    for role, bp in mapping.items():
        if not bp or bp not in df.columns.get_level_values(0):
            continue
        sub = df[bp]
        xy = clean(sub[["x", "y"]].to_numpy(), sub["likelihood"].to_numpy(), threshold, max_gap)
        out[role] = calmod.to_cm(xy, cal)
        good[role] = float(np.mean(sub["likelihood"].to_numpy() >= threshold))
    return out, good


def smooth_derivative(y, fps, window_s=0.2):
    """Savitzky-Golay derivative (units per second), NaN-tolerant."""
    from scipy.signal import savgol_filter
    y = np.asarray(y, float)
    n = len(y)
    if n < 5:
        return np.full(n, np.nan)
    win = max(5, int(round(window_s * fps)) | 1)
    win = min(win, n - (1 - n % 2))
    ok = np.isfinite(y)
    if ok.sum() < win:
        return np.full(n, np.nan)
    yi = pd.Series(y).interpolate(limit_direction="both").to_numpy()
    d = savgol_filter(yi, win, 2, deriv=1, delta=1.0 / fps)
    d[~ok] = np.nan
    return d


def head_kinematics(kp, fps, half_cm, window_s=0.2):
    """Per-frame head position, yaw and gaze point on the drum walls.

    yaw_deg      head direction, compass style: 0 = towards the top wall, increasing clockwise
                 (seen from above), unwrapped
    yaw_vel      deg/s, + = clockwise (= the same sign as a CW grating)
    gaze_az      drum azimuth (deg, clockwise) of the point where the gaze line meets a wall,
                 seen from the arena centre, unwrapped
    gaze_vel     deg/s of that point along the screens, + = clockwise
    wall, along  which wall and where on it (cm)
    """
    n = len(next(iter(kp.values())))
    nan2 = np.full((n, 2), np.nan)
    nose, le, re_, neck = (kp.get(k, nan2) for k in ("nose", "left_ear", "right_ear", "neck"))
    ears = (le + re_) / 2
    centre = np.where(np.isfinite(ears), ears, np.where(np.isfinite(neck), neck, nose))
    v = nose - ears
    v2 = ears - neck
    v = np.where(np.isfinite(v).all(1, keepdims=True), v, v2)
    # ear line as a last resort: perpendicular to left->right ear, towards the front
    perp = np.c_[-(re_ - le)[:, 1], (re_ - le)[:, 0]]
    v = np.where(np.isfinite(v).all(1, keepdims=True), v, perp)
    norm = np.hypot(v[:, 0], v[:, 1])
    u = v / np.where(norm > 0, norm, np.nan)[:, None]
    yaw = np.degrees(np.arctan2(u[:, 0], u[:, 1]))           # compass: atan2(x, y)
    yaw_u = unwrap_nan(yaw)
    wall, along, dist = ray_to_wall(centre[:, 0], centre[:, 1], u[:, 0], u[:, 1], half_cm)
    gaze = wall_point_azimuth(wall, along, half_cm)
    gaze_u = unwrap_nan(gaze)
    return pd.DataFrame({
        "head_x": centre[:, 0], "head_y": centre[:, 1], "head_off_cm": np.hypot(centre[:, 0], centre[:, 1]),
        "yaw_deg": yaw_u, "yaw_vel": smooth_derivative(yaw_u, fps, window_s),
        "wall": wall, "along_cm": along, "gaze_dist_cm": dist,
        "gaze_az": gaze_u, "gaze_vel": smooth_derivative(gaze_u, fps, window_s),
        "dir_x": u[:, 0], "dir_y": u[:, 1],
    })


def unwrap_nan(deg):
    a = np.asarray(deg, float)
    ok = np.isfinite(a)
    out = np.full_like(a, np.nan)
    if ok.any():
        out[ok] = np.degrees(np.unwrap(np.radians(a[ok])))
    return out


def find_dlc_output(video, folder=None):
    """DLC result file (.h5 preferred, else .csv) for a video, searched next to it / in folder."""
    stem = os.path.splitext(os.path.basename(video))[0]
    dirs = [d for d in (folder, os.path.dirname(os.path.abspath(video))) if d]
    hits = []
    for d in dirs:
        if os.path.isdir(d):
            hits += [os.path.join(d, f) for f in os.listdir(d)
                     if f.startswith(stem) and "DLC" in f and f.endswith((".h5", ".csv"))
                     and "_meta" not in f and "_cm" not in f]
    hits.sort(key=lambda p: (not p.endswith(".h5"), "filtered" not in p, -os.path.getmtime(p)))
    return hits[0] if hits else None

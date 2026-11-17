"""Putting a session together and measuring the optokinetic response.

Inputs of one session
    stimulus CSV       written by OKR Drum on the lab PC (one row per grating)
    Pi frames CSV      every video frame's timestamp (+ trial number)       *_frames.csv
    Pi markers CSV     grating onsets (T) and ends (E) as seen by the Pi    *_markers.csv
    DLC file           keypoints per video frame                           *DLC*.h5 / .csv
    calibration        pixels -> cm in the arena frame                      *.json

Per trial (stimulus window) and its baseline (the same length right before the onset):
    v_dir        mean head-yaw velocity in the stimulus direction (deg/s)
    gain         v_dir / stimulus speed (net, includes the fast resets)
    slow_gain    mean velocity without the fast resets (|v| > hi_frac x speed) / speed
    gaze_v_dir   same for the gaze point moving along the screens
    with_frac    fraction of time the head turns with the stimulus (between
                 lo_frac x speed and hi_frac x speed); against_frac the opposite
    okr_index    with_frac - against_frac during the grating (base_index: same, before it)
    episodes     tracking episodes (with-stimulus runs >= min_episode_s), their total time
                 and mean amplitude (deg)
    tracked      automatic score: >= 1 episode and okr_index >= index_criterion
"""
from __future__ import annotations

import json
import math
import os

import numpy as np
import pandas as pd

DEFAULTS = {"likelihood": 0.6, "max_gap": 6, "deriv_window_s": 0.2, "lo_frac": 0.25, "min_lo": 2.0,
            "hi_frac": 3.0, "min_episode_s": 0.3, "index_criterion": 0.3, "baseline_s": None,
            "max_head_offset_cm": 4.0}


# ---------------------------------------------------------------------- loading
def load_stimulus(path):
    df = pd.read_csv(path)
    settings = {}
    sp = path[:-4] + "_settings.json"
    if os.path.exists(sp):
        with open(sp, encoding="utf-8") as f:
            settings = json.load(f)
    return df, settings


def load_pi(frames_csv, markers_csv=None):
    fr = pd.read_csv(frames_csv)
    mk = None
    if markers_csv and os.path.exists(markers_csv):
        mk = pd.read_csv(markers_csv)
    return fr, mk


def guess_companions(video):
    """For a Pi video *_raw.mp4 -> its _frames.csv, _markers.csv, _info.json if present."""
    base = video
    for suf in ("_raw.mp4", "_raw.avi", ".mp4", ".avi"):
        if video.endswith(suf):
            base = video[: -len(suf)]
            break
    out = {}
    for k in ("frames", "markers", "info"):
        p = base + ("_%s.csv" % k if k != "info" else "_info.json")
        out[k] = p if os.path.exists(p) else None
    return out


def trial_windows(frames, markers, stim, fps, align="markers", offset_s=0.0):
    """[(trial number, onset frame, end frame)] in video frames.

    markers: T/E markers matched to frames by the Pi (default)
    clock:   PC onset_unix_time vs the Pi's per-frame unix_time (needs synced clocks) + offset
    """
    out = []
    if align == "markers" and markers is not None and len(markers):
        on, end = {}, {}
        for _, m in markers.iterrows():
            lab = str(m["message"]).split()[0]
            if pd.isna(m.get("frame")) or m.get("frame") == "":
                continue
            if lab[0] == "T":
                on[int(lab[1:])] = int(m["frame"])
            elif lab[0] == "E":
                end[int(lab[1:])] = int(m["frame"])
        for t, f0 in sorted(on.items()):
            row = stim[stim["trial"] == t]
            dur = float(row["shown_s"].iloc[0]) if len(row) else float("nan")
            f1 = end.get(t, f0 + int(round(dur * fps)) if np.isfinite(dur) else f0)
            out.append((t, f0, f1))
        return out
    ut = frames["unix_time"].to_numpy(float)
    for _, r in stim.iterrows():
        if pd.isna(r.get("onset_unix_time")):
            continue
        t0 = float(r["onset_unix_time"]) + offset_s
        t1 = float(r["end_unix_time"]) + offset_s if "end_unix_time" in r and not pd.isna(r["end_unix_time"]) \
            else t0 + float(r["shown_s"])
        f0, f1 = int(np.searchsorted(ut, t0)), int(np.searchsorted(ut, t1))
        if f0 < len(ut):
            out.append((int(r["trial"]), f0, f1))
    return out


# ---------------------------------------------------------------------- metrics
def _runs(mask):
    """[(start, stop)] of True runs."""
    m = np.r_[False, np.asarray(mask, bool), False]
    d = np.diff(m.astype(int))
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0]))


def window_metrics(yaw_vel, gaze_vel, yaw, speed, direction, fps, prm):
    v = direction * np.asarray(yaw_vel, float)
    g = direction * np.asarray(gaze_vel, float)
    ok = np.isfinite(v)
    out = {"valid_frac": float(ok.mean()) if len(v) else 0.0}
    if ok.sum() < max(3, 0.3 * len(v)):
        out.update({k: np.nan for k in ("v_dir", "gain", "slow_gain", "gaze_v_dir", "with_frac", "against_frac", "index",
                                        "episodes", "episode_s", "episode_amp")})
        return out
    lo = max(prm["lo_frac"] * speed, prm["min_lo"])
    hi = max(prm["hi_frac"] * speed, lo * 2)
    vv = np.where(ok, v, 0)
    with_ = ok & (vv >= lo) & (vv <= hi)
    against = ok & (-vv >= lo) & (-vv <= hi)
    eps = [(a, b) for a, b in _runs(with_) if (b - a) / fps >= prm["min_episode_s"]]
    amps = []
    yaw = np.asarray(yaw, float)
    for a, b in eps:
        seg = yaw[a:b]
        seg = seg[np.isfinite(seg)]
        if seg.size > 1:
            amps.append(abs(seg[-1] - seg[0]))
    out.update({
        "v_dir": float(np.nanmean(v)), "gain": float(np.nanmean(v) / speed) if speed else np.nan,
        # slow-phase gain: mean velocity with the fast resets (|v| > hi) removed, as in OKN analysis
        "slow_gain": float(np.mean(vv[ok & (np.abs(vv) <= hi)]) / speed) if speed and (ok & (np.abs(vv) <= hi)).any() else np.nan,
        "gaze_v_dir": float(np.nanmean(g)) if np.isfinite(g).any() else np.nan,
        "with_frac": float(with_[ok].mean()), "against_frac": float(against[ok].mean()),
        "index": float(with_[ok].mean() - against[ok].mean()),
        "episodes": len(eps), "episode_s": float(sum(b - a for a, b in eps) / fps),
        "episode_amp": float(np.mean(amps)) if amps else 0.0,
    })
    return out


def analyse(kin, frames_t, windows, stim, fps, params=None):
    """Per-trial table. kin: head_kinematics DataFrame (one row per video frame)."""
    prm = dict(DEFAULTS, **(params or {}))
    rows = []
    n = len(kin)
    prev_end = 0
    for t, f0, f1 in sorted(windows, key=lambda w: w[1]):
        r = stim[stim["trial"] == t]
        if not len(r) or f0 >= n:
            continue
        r = r.iloc[0].to_dict()
        f1 = min(f1, n)
        speed, d = float(r["speed_deg_s"]), (1 if str(r["direction"]).upper() == "CW" else -1)
        base_len = int(round((prm["baseline_s"] or (f1 - f0) / fps) * fps))
        b0 = max(prev_end, f0 - base_len)          # baseline never overlaps the previous grating
        prev_end = f1
        seg = kin.iloc[f0:f1]
        m = window_metrics(seg["yaw_vel"], seg["gaze_vel"], seg["yaw_deg"], speed, d, fps, prm)
        b = window_metrics(kin["yaw_vel"].iloc[b0:f0], kin["gaze_vel"].iloc[b0:f0], kin["yaw_deg"].iloc[b0:f0],
                           speed, d, fps, prm) if f0 - b0 >= 3 else {}
        off = float(np.nanmedian(seg["head_off_cm"])) if seg["head_off_cm"].notna().any() else np.nan
        row = {"trial": t, "contrast": r["contrast"], "spatial_freq_cpd": r["spatial_freq_cpd"],
               "bar_width_deg": r.get("bar_width_used_deg"), "speed_deg_s": speed, "direction": r["direction"],
               "eye": "left" if d > 0 else "right", "onset_frame": f0, "end_frame": f1,
               "onset_s": float(frames_t[f0]) if f0 < len(frames_t) else np.nan,
               "head_offset_cm": off, "operator_response": r.get("response", "")}
        row.update(m)
        row.update({"base_" + k: v for k, v in b.items() if k in ("v_dir", "index", "with_frac", "episodes")})
        row["okr_index"] = m.get("index", np.nan)
        row["tracked"] = bool(m.get("episodes", 0) and row["okr_index"] >= prm["index_criterion"])
        row["note"] = "head off-centre" if np.isfinite(off) and off > prm["max_head_offset_cm"] else ""
        rows.append(row)
    return pd.DataFrame(rows)


def condition_summary(trials, by=("spatial_freq_cpd", "contrast", "speed_deg_s", "eye")):
    if trials is None or not len(trials):
        return pd.DataFrame()
    by = [b for b in by if b in trials]
    g = trials.groupby(by)
    agg = g.agg(n=("trial", "count"), okr_index=("okr_index", "mean"), okr_index_sem=("okr_index", "sem"),
                gain=("gain", "mean"), slow_gain=("slow_gain", "mean"), slow_gain_sem=("slow_gain", "sem"),
                v_dir=("v_dir", "mean"), base_index=("base_index", "mean"),
                episodes=("episodes", "mean"), tracked_frac=("tracked", "mean"))
    return agg.reset_index()


def threshold(summary, x="spatial_freq_cpd", y="okr_index", criterion=0.1, eye=None):
    """Highest x at which y still reaches the criterion (linear interpolation of the drop)."""
    s = summary if eye is None else summary[summary["eye"] == eye]
    if not len(s):
        return math.nan
    s = s.groupby(x)[y].mean().sort_index()
    xs, ys = s.index.to_numpy(float), s.to_numpy(float)
    if x == "contrast":
        xs, ys = xs[::-1], ys[::-1]          # lowest contrast that still works
    above = np.where(ys >= criterion)[0]
    if not len(above):
        return math.nan
    i = above.max()
    if i == len(xs) - 1:
        return float(xs[i])
    x0, x1, y0, y1 = xs[i], xs[i + 1], ys[i], ys[i + 1]
    return float(x0 + (criterion - y0) * (x1 - x0) / (y1 - y0)) if y1 != y0 else float(x0)


def per_frame_table(kin, frames_t, windows, stim):
    """kinematics + time + trial / stimulus per frame (for export and plots)."""
    out = kin.copy()
    out.insert(0, "t_s", np.asarray(frames_t[: len(kin)], float))
    out["trial"] = np.nan
    out["stim_speed_signed"] = 0.0
    for t, f0, f1 in windows:
        r = stim[stim["trial"] == t]
        if not len(r):
            continue
        d = 1 if str(r["direction"].iloc[0]).upper() == "CW" else -1
        out.loc[f0:f1 - 1, "trial"] = t
        out.loc[f0:f1 - 1, "stim_speed_signed"] = d * float(r["speed_deg_s"].iloc[0])
    return out


def frame_times(frames, fps):
    if frames is not None and "sensor_timestamp_ns" in frames:
        ts = frames["sensor_timestamp_ns"].to_numpy(np.int64)
        return (ts - ts[0]) / 1e9
    return None

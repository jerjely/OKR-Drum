"""A complete synthetic session with a known answer, for the self-test, the demo and screenshots.

The simulated mouse sits on the pedestal; during a grating it follows the stimulus with
smooth head turns (gain ~0.7) interrupted by fast resets, with a probability that falls with
spatial frequency (acuity ~0.38 c/deg) - the left eye (CW) slightly better than the right.
Files written (like a real session):
    stim.csv + stim_settings.json            (OKR Drum, lab PC)
    rec_raw.mp4, rec_frames.csv, rec_markers.csv, rec_info.json   (Pi recorder)
    rec_rawDLC_resnet50_okrSimShuffle1_100000.csv   (DeepLabCut)
    calibration.json
"""
from __future__ import annotations

import json
import os

import cv2
import numpy as np
import pandas as pd

from ..geometry import Rig
from ..protocol import merged, make_trial
from . import calibration as calmod
from .overlay import open_writer

SFS = [0.044, 0.1, 0.2, 0.3, 0.4, 0.5]


def p_track(sf, eye_bonus=0.0):
    return 1 / (1 + np.exp((sf - (0.38 + eye_bonus)) / 0.045))


def make(folder, fps=30.0, duration=4.0, iti=3.0, sfs=SFS, speed=12.0, video=True, size=(640, 480),
         seed=1, px_per_cm=26.0):
    os.makedirs(folder, exist_ok=True)
    rng = np.random.default_rng(seed)
    rig = Rig()
    p = merged({"duration": duration, "iti": iti})
    trials = []
    for sf in sfs:
        for d in (1, -1):
            trials.append(make_trial(len(trials) + 1, 1.0, 1 / (2 * sf), speed, d, p))
    # ---------------- timeline
    total = iti + len(trials) * (duration + iti)
    n = int(total * fps)
    t = np.arange(n) / fps
    stim_speed = np.zeros(n)
    win = []
    for i, tr in enumerate(trials):
        t0 = iti + i * (duration + iti)
        f0, f1 = int(round(t0 * fps)), int(round((t0 + duration) * fps))
        win.append((tr["trial"], f0, f1))
        stim_speed[f0:f1] = tr["dir_sign"] * speed
    # ---------------- head yaw (compass deg, + = clockwise)
    yaw = np.zeros(n)
    yaw[0] = rng.uniform(0, 360)
    resp = {}
    for tr, f0, f1 in win:
        tri = trials[tr - 1]
        resp[tr] = rng.random() < p_track(tri["spatial_freq_cpd"], 0.02 if tri["dir_sign"] > 0 else -0.02)
    state_until = 0
    reset_left = 0
    for i in range(1, n):
        dt = 1 / fps
        tr = next((w for w in win if w[1] <= i < w[2]), None)
        v = rng.normal(0, 8)                       # restless baseline
        if tr and resp[tr[0]]:
            d = np.sign(stim_speed[i])
            if reset_left > 0:
                v = -d * 160
                reset_left -= 1
            else:
                v = d * speed * 0.7 + rng.normal(0, 2)
                if i >= state_until:
                    state_until = i + int(fps * rng.uniform(1.2, 2.2))
                elif i == state_until - 1:
                    reset_left = int(0.12 * fps)
        yaw[i] = yaw[i - 1] + v * dt
    # ---------------- keypoints in arena cm
    hx = 0.4 + np.cumsum(rng.normal(0, 0.01, n)); hy = -0.3 + np.cumsum(rng.normal(0, 0.01, n))
    hx = 0.4 + 0.3 * np.tanh(hx - 0.4); hy = -0.3 + 0.3 * np.tanh(hy + 0.3)
    a = np.radians(yaw)
    fwd = np.c_[np.sin(a), np.cos(a)]
    right = np.c_[np.cos(a), -np.sin(a)]
    ears = np.c_[hx, hy]
    kp = {"nose": ears + 1.3 * fwd, "leftear": ears - 0.85 * right - 0.1 * fwd,
          "rightear": ears + 0.85 * right - 0.1 * fwd, "neck": ears - 1.4 * fwd}
    cal = calmod.new_calibration(size)
    cal["px_per_cm"] = px_per_cm
    cal["centre_px"] = [size[0] / 2 + 6.0, size[1] / 2 - 4.0]
    calmod.save(cal, os.path.join(folder, "calibration.json"))
    kp_px = {k: calmod.from_cm(v, cal) + rng.normal(0, 0.7, (n, 2)) for k, v in kp.items()}
    # ---------------- DLC table
    scorer = "DLC_resnet50_okrSimShuffle1_100000"
    cols, data = [], []
    for bp, xy in kp_px.items():
        lik = np.clip(rng.normal(0.97, 0.03, n), 0, 1)
        drop = rng.random(n) < 0.02
        lik[drop] = 0.2
        for c, col in (("x", xy[:, 0]), ("y", xy[:, 1]), ("likelihood", lik)):
            cols.append((scorer, bp, c))
            data.append(col)
    dlc = pd.DataFrame(np.array(data).T, columns=pd.MultiIndex.from_tuples(cols, names=["scorer", "bodyparts", "coords"]))
    dlc_csv = os.path.join(folder, "rec_raw" + scorer + ".csv")
    dlc.to_csv(dlc_csv)
    # ---------------- Pi files
    ns0 = 5_000_000_000
    ts = (ns0 + t * 1e9 + rng.normal(0, 2e5, n)).astype(np.int64)
    ts.sort()
    unix0 = 1_790_000_000.0
    trial_col = np.full(n, "", object)
    for tr, f0, f1 in win:
        trial_col[f0:f1] = str(tr)
    pd.DataFrame({"frame": np.arange(n), "sensor_timestamp_ns": ts, "unix_time": unix0 + (ts - ts[0]) / 1e9,
                  "exposure_us": 8000, "analogue_gain": 4.0, "trial": trial_col}).to_csv(
        os.path.join(folder, "rec_frames.csv"), index=False)
    mk = []
    for tr, f0, f1 in win:
        tri = trials[tr - 1]
        for lab, f in (("T%d c=1 w=%.3f v=%g %s" % (tr, tri["bar_width_used_deg"], speed, tri["direction"]), f0),
                       ("E%d" % tr, f1)):
            arr = int(ts[f] - 3e6)
            mk.append({"message": lab, "frame": f, "frame_delay_ms": 3.0, "arrival_ns": arr,
                       "unix_time": unix0 + (arr - ts[0]) / 1e9})
    pd.DataFrame(mk).to_csv(os.path.join(folder, "rec_markers.csv"), index=False)
    with open(os.path.join(folder, "rec_info.json"), "w") as f:
        json.dump({"mouse": "demo", "fps": fps, "size": list(size), "app_version": "synthetic"}, f)
    # ---------------- stimulus log (lab PC)
    rows = []
    for tr, f0, f1 in win:
        r = dict(trials[tr - 1])
        r.update({"shown_s": (f1 - f0) / fps, "onset_unix_time": unix0 + (ts[f0] - ts[0]) / 1e9 - 0.003,
                  "end_unix_time": unix0 + (ts[f1] - ts[0]) / 1e9 - 0.003, "frames": int((f1 - f0) * 2),
                  "dropped_frames": 0, "mean_frame_ms": 16.67, "response": ""})
        rows.append(r)
    stim_csv = os.path.join(folder, "stim.csv")
    pd.DataFrame(rows).to_csv(stim_csv, index=False)
    with open(os.path.join(folder, "stim_settings.json"), "w") as f:
        json.dump({"protocol": p, "rig": rig.to_dict(), "meta": {"animal": "demo"}}, f, indent=1)
    # ---------------- video
    vid = os.path.join(folder, "rec_raw.mp4")
    if video:
        vid = draw_video(vid, kp_px, cal, fps, size, rng)
    truth = {"responded": resp, "trials": trials}
    return {"folder": folder, "video": vid, "stim_csv": stim_csv, "frames_csv": os.path.join(folder, "rec_frames.csv"),
            "markers_csv": os.path.join(folder, "rec_markers.csv"), "dlc_file": dlc_csv,
            "calibration": os.path.join(folder, "calibration.json"), "truth": truth, "fps": fps, "n": n}


def draw_video(path, kp_px, cal, fps, size, rng):
    W, H = size
    writer, path = open_writer(path, fps, (W, H))
    yy, xx = np.mgrid[0:H, 0:W]
    floor = (70 + 25 * np.exp(-(((xx - W / 2) / 420) ** 2 + ((yy - H / 2) / 360) ** 2))).astype(np.float32)
    c = tuple(int(v) for v in cal["centre_px"])
    r_ped = int(2.5 * cal["px_per_cm"])
    cv2.circle(floor, c, r_ped, 150, -1)
    n = len(kp_px["nose"])
    s = cal["px_per_cm"]
    for i in range(n):
        img = floor.copy()
        nose, le, re_, neck = (kp_px[k][i] for k in ("nose", "leftear", "rightear", "neck"))
        ears = (le + re_) / 2
        ang = np.degrees(np.arctan2(*(nose - neck)[::-1]))
        body_c = neck - 0.9 * s * (nose - neck) / max(np.hypot(*(nose - neck)), 1e-6)
        cv2.ellipse(img, tuple(body_c.astype(int)), (int(2.2 * s), int(1.3 * s)), ang, 0, 360, 205, -1)
        cv2.ellipse(img, tuple(((ears + nose) / 2).astype(int)), (int(1.1 * s), int(0.75 * s)), ang, 0, 360, 212, -1)
        for e in (le, re_):
            cv2.circle(img, tuple(e.astype(int)), int(0.45 * s), 190, -1)
        cv2.circle(img, tuple(nose.astype(int)), max(2, int(0.15 * s)), 140, -1)
        img = cv2.GaussianBlur(img, (0, 0), 1.2) + rng.normal(0, 2.0, img.shape)
        g = np.clip(img, 0, 255).astype(np.uint8)
        writer.write(cv2.cvtColor(g, cv2.COLOR_GRAY2BGR))
    writer.release()
    return path

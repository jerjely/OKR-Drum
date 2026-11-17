"""Inbox: finds new recordings in a shared folder (e.g. the Google Drive folder the Pi uploads
to, synced by Google Drive for desktop) and pairs every Pi video with the stimulus log of the
same session by time."""
from __future__ import annotations

import json
import os

import pandas as pd

VIDEO_SUFFIXES = ("_raw.mp4", "_raw.avi")


def _scan(folder, max_depth=4):
    root_depth = folder.rstrip(os.sep).count(os.sep)
    for d, dirs, files in os.walk(folder):
        if d.count(os.sep) - root_depth >= max_depth:
            dirs[:] = []
        yield d, files


def find_videos(folder):
    out = []
    for d, files in _scan(folder):
        for f in files:
            if f.endswith(VIDEO_SUFFIXES):
                stem = f[: -len("_raw.mp4")]
                rec = {"video": os.path.join(d, f), "stem": stem}
                for k in ("frames", "markers"):
                    p = os.path.join(d, "%s_%s.csv" % (stem, k))
                    rec[k + "_csv"] = p if os.path.exists(p) else None
                ip = os.path.join(d, stem + "_info.json")
                rec["info"] = {}
                if os.path.exists(ip):
                    try:
                        with open(ip, encoding="utf-8") as fh:
                            rec["info"] = json.load(fh)
                    except Exception:
                        pass
                out.append(rec)
    return out


def find_stim_logs(folder):
    out = []
    for d, files in _scan(folder):
        for f in files:
            if f.endswith(".csv") and f[:-4] + "_settings.json" in files:
                p = os.path.join(d, f)
                try:
                    df = pd.read_csv(p, usecols=lambda c: c in ("trial", "onset_unix_time"))
                    t = df["onset_unix_time"].dropna().to_numpy(float)
                except Exception:
                    continue
                meta = {}
                try:
                    with open(p[:-4] + "_settings.json", encoding="utf-8") as fh:
                        meta = json.load(fh).get("meta", {})
                except Exception:
                    pass
                out.append({"stim_csv": p, "onsets": t, "meta": meta})
    return out


def pair_sessions(folder):
    """[{video, frames_csv, markers_csv, stim_csv, dlc_file, animal, date, n_inside}]"""
    from .analysis.tracking import find_dlc_output
    logs = find_stim_logs(folder)
    pairs = []
    for v in find_videos(folder):
        best, n_best = None, 0
        named = (v["info"].get("session_info") or {}).get("stim_log")
        if named:                                  # sent by OKR Drum over the serial line: exact match
            hit = [lg for lg in logs if os.path.basename(lg["stim_csv"]) == named]
            if hit:
                best, n_best = hit[0], len(hit[0]["onsets"])
        if best is None and v["frames_csv"]:
            try:
                ut = pd.read_csv(v["frames_csv"], usecols=["unix_time"])["unix_time"].to_numpy(float)
                t0, t1 = ut.min(), ut.max()
                for lg in logs:
                    n = int(((lg["onsets"] >= t0 - 5) & (lg["onsets"] <= t1 + 5)).sum())
                    if n > n_best:
                        best, n_best = lg, n
            except Exception:
                pass
        info = v["info"]
        meta = best["meta"] if best else {}
        date = ""
        try:
            date = (v["info"].get("session_info") or {}).get("date") or \
                pd.Timestamp(v["info"].get("start_unix_time"), unit="s").strftime("%Y-%m-%d")
        except Exception:
            pass
        pairs.append({"video": v["video"], "frames_csv": v["frames_csv"], "markers_csv": v["markers_csv"],
                      "stim_csv": best["stim_csv"] if best else None, "n_inside": n_best,
                      "dlc_file": find_dlc_output(v["video"]) or "",
                      "animal": meta.get("animal") or info.get("mouse", ""),
                      "treatment": meta.get("treatment") or info.get("treatment", ""), "date": date})
    return pairs

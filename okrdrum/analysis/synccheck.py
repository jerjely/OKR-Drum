"""Sync check: are video, markers and the stimulus log consistent before analysing?"""
from __future__ import annotations

import numpy as np
import pandas as pd

OK, WARN, BAD = "ok", "warning", "problem"


def check(stim=None, frames=None, markers=None, fps=None, video_frames=None):
    """List of (level, message)."""
    out = []
    add = out.append
    if frames is not None and len(frames) > 1 and "sensor_timestamp_ns" in frames:
        dt = np.diff(frames["sensor_timestamp_ns"].to_numpy(np.int64)) / 1e6
        med = float(np.median(dt))
        f = 1000 / med if med > 0 else float("nan")
        gaps = int(np.sum(dt > 1.5 * med))
        add((OK if gaps == 0 else WARN if gaps < 0.005 * len(dt) + 2 else BAD,
             "Video: %d frames at %.2f fps, %d gap(s) (skipped frames)%s" % (
                 len(frames), f, gaps, "" if not gaps else ", longest %.0f ms" % dt.max())))
        if fps and abs(f - fps) > 0.5:
            add((WARN, "Video file says %.2f fps but the frames came at %.2f fps" % (fps, f)))
    elif frames is None:
        add((WARN, "No frame-timestamp file (*_frames.csv): times come from the video's frame rate"))
    if video_frames is not None and frames is not None and abs(video_frames - len(frames)) > 2:
        add((BAD, "Video has %d frames but the timestamp file lists %d" % (video_frames, len(frames))))
    if markers is None:
        add((WARN, "No marker file (*_markers.csv): trials will be aligned by clock time"))
    else:
        labs = markers["message"].astype(str).str.split().str[0]
        on = sorted(int(x[1:]) for x in labs if x.startswith("T"))
        en = sorted(int(x[1:]) for x in labs if x.startswith("E"))
        add((OK, "Markers: %d onsets, %d ends" % (len(on), len(en))))
        miss_end = sorted(set(on) - set(en))
        if miss_end:
            add((WARN, "Trial(s) without an end marker: %s" % _short(miss_end)))
        if "frame" in markers and markers["frame"].isna().any():
            add((BAD, "%d marker(s) arrived outside the recording" % int(markers["frame"].isna().sum())))
        if stim is not None:
            st = sorted(stim["trial"].astype(int))
            nm = sorted(set(st) - set(on))
            if nm:
                add((BAD, "Trial(s) in the stimulus log with no marker on the Pi: %s" % _short(nm)))
            extra = sorted(set(on) - set(st))
            if extra:
                add((WARN, "Marker(s) for trials missing from the stimulus log: %s" % _short(extra)))
            # durations seen by the Pi vs shown by the PC
            if "arrival_ns" in markers:
                tt = {}
                for lab, ns in zip(labs, markers["arrival_ns"]):
                    tt.setdefault(int(lab[1:]), {})[lab[0]] = ns
                diffs = []
                for t, d in tt.items():
                    if "T" in d and "E" in d and t in set(st):
                        shown = float(stim.loc[stim["trial"] == t, "shown_s"].iloc[0])
                        diffs.append((d["E"] - d["T"]) / 1e9 - shown)
                if diffs:
                    worst = float(np.max(np.abs(diffs)))
                    add((OK if worst < 0.05 else WARN if worst < 0.2 else BAD,
                         "Trial durations Pi vs PC agree within %.0f ms" % (worst * 1000)))
    if stim is not None and "dropped_frames" in stim:
        d = pd.to_numeric(stim["dropped_frames"], errors="coerce").fillna(0)
        add((OK if d.sum() == 0 else WARN if d.max() <= 2 else BAD,
             "Stimulus: %d dropped frame(s) in %d trial(s)" % (int(d.sum()), int((d > 0).sum()))))
    return out


def _short(xs, n=12):
    return ", ".join(map(str, xs[:n])) + (" ..." if len(xs) > n else "")


def worst(results):
    lv = [r[0] for r in results]
    return BAD if BAD in lv else WARN if WARN in lv else OK

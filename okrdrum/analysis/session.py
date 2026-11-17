"""One recording session from files to results (used by the app, the self-test and scripts)."""
from __future__ import annotations

import json
import os

import cv2
import numpy as np
import pandas as pd

from ..geometry import Rig
from . import calibration as calmod
from . import okr, synccheck, tracking


class Session:
    def __init__(self, video=None, stim_csv=None, frames_csv=None, markers_csv=None, dlc_file=None,
                 calibration=None, rig=None, params=None, mapping=None, align="markers", offset_s=0.0):
        self.video, self.stim_csv = video, stim_csv
        self.frames_csv, self.markers_csv = frames_csv, markers_csv
        self.dlc_file, self.calibration = dlc_file, calibration
        self.rig = rig if isinstance(rig, Rig) else Rig.from_dict(rig or {})
        self.params = dict(okr.DEFAULTS, **(params or {}))
        self.mapping = mapping or {}
        self.align, self.offset_s = align, offset_s
        self.results = {}

    @classmethod
    def from_video(cls, video, **kw):
        comp = okr.guess_companions(video)
        s = cls(video=video, frames_csv=comp["frames"], markers_csv=comp["markers"], **kw)
        s.dlc_file = s.dlc_file or tracking.find_dlc_output(video)
        return s

    def to_dict(self):
        return {k: getattr(self, k) for k in ("video", "stim_csv", "frames_csv", "markers_csv", "dlc_file",
                                               "calibration", "params", "mapping", "align", "offset_s")} | \
               {"rig": self.rig.to_dict()}

    # ------------------------------------------------------------------ steps
    def video_info(self):
        if not self.video or not os.path.exists(self.video):
            return None
        cap = cv2.VideoCapture(self.video)
        info = {"fps": cap.get(cv2.CAP_PROP_FPS) or 30.0, "frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
                "w": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), "h": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}
        cap.release()
        return info

    def load(self):
        self.stim, self.stim_settings = okr.load_stimulus(self.stim_csv)
        if self.stim_settings.get("rig") and not getattr(self, "_rig_set", False):
            self.rig = Rig.from_dict(self.stim_settings["rig"])
        self.frames, self.markers = (okr.load_pi(self.frames_csv, self.markers_csv)
                                     if self.frames_csv else (None, None))
        info = self.video_info() or {}
        fps = info.get("fps", 30.0)
        if self.frames is not None and len(self.frames) > 1:
            dt = np.median(np.diff(self.frames["sensor_timestamp_ns"].to_numpy(np.int64))) / 1e9
            fps = 1 / dt
        self.fps = float(fps)
        self.info = info
        if isinstance(self.calibration, str):
            self.cal = calmod.load(self.calibration)
        elif isinstance(self.calibration, dict):
            self.cal = self.calibration
        else:
            self.cal = calmod.new_calibration((info.get("w", 1280), info.get("h", 960)))
            self.cal["px_per_cm"] = None
        return self

    def sync_report(self):
        return synccheck.check(self.stim, self.frames, self.markers, fps=self.info.get("fps"),
                               video_frames=self.info.get("frames"))

    def track(self):
        df = tracking.read_dlc(self.dlc_file)
        parts = tracking.bodyparts(df)
        self.mapping = {**tracking.auto_map(parts), **{k: v for k, v in self.mapping.items() if v}}
        if self.cal.get("px_per_cm") is None and self.cal.get("H") is None:
            raise ValueError("No camera calibration: run the calibration tool (or set the pedestal scale)")
        self.kp_cm, self.kp_good = tracking.keypoints_cm(df, self.mapping, self.cal, self.params["likelihood"],
                                                         self.params["max_gap"])
        self.kp_px = {}
        for role, bp in self.mapping.items():
            sub = df[bp]
            xy = sub[["x", "y"]].to_numpy(float)
            xy[sub["likelihood"].to_numpy() < self.params["likelihood"]] = np.nan
            self.kp_px[role] = xy
        self.kin = tracking.head_kinematics(self.kp_cm, self.fps, self.rig.dist, self.params["deriv_window_s"])
        return self

    def analyse(self):
        ft = okr.frame_times(self.frames, self.fps)
        if ft is None:
            ft = np.arange(len(self.kin)) / self.fps
        self.t = ft
        self.windows = okr.trial_windows(self.frames, self.markers, self.stim, self.fps, self.align, self.offset_s)
        self.trials = okr.analyse(self.kin, ft, self.windows, self.stim, self.fps, self.params)
        self.summary = okr.condition_summary(self.trials)
        self.per_frame = okr.per_frame_table(self.kin, ft, self.windows, self.stim)
        thr = {}
        for eye in ("left", "right"):
            for x in ("spatial_freq_cpd", "contrast"):
                if len(self.summary) and self.summary[x].nunique() > 1:
                    thr["%s_%s" % (eye, x)] = okr.threshold(self.summary, x, "okr_index",
                                                           self.params["index_criterion"], eye)
        self.thresholds = thr
        return self

    def run_all(self):
        return self.load().track().analyse()

    def save(self, folder=None):
        folder = folder or os.path.dirname(os.path.abspath(self.video or self.stim_csv))
        stem = os.path.splitext(os.path.basename(self.video or self.stim_csv))[0].replace("_raw", "")
        base = os.path.join(folder, stem + "_okr")
        self.trials.to_csv(base + "_trials.csv", index=False)
        self.summary.to_csv(base + "_summary.csv", index=False)
        self.per_frame.to_csv(base + "_frames.csv", index=False)
        with open(base + "_session.json", "w", encoding="utf-8") as f:
            json.dump({"session": self.to_dict(), "thresholds": self.thresholds,
                       "keypoint_quality": self.kp_good}, f, indent=1, default=str)
        return base

    def overlay(self, out_path, start=0, stop=None, progress=None, scale=1.0):
        from . import overlay
        return overlay.render(self.video, out_path, self.kp_px, self.kin, self.per_frame,
                              lambda cm: calmod.from_cm(cm, self.cal), self.rig.dist, start, stop, progress, scale)

"""Overlay video: keypoints, head direction, gaze line to the wall, a top-view inset of the
drum with the gaze point, and the stimulus state."""
from __future__ import annotations

import os

import cv2
import numpy as np

COL = {"nose": (60, 220, 255), "left_ear": (80, 255, 120), "right_ear": (255, 140, 80), "neck": (220, 120, 255)}


def open_writer(path, fps, size):
    """Absolute path + codec fallback (mp4v -> avc1 -> MJPG .avi), as macOS needs."""
    path = os.path.abspath(path)
    stem = os.path.splitext(path)[0]
    for fourcc, ext in (("mp4v", ".mp4"), ("avc1", ".mp4"), ("MJPG", ".avi")):
        w = cv2.VideoWriter(stem + ext, cv2.VideoWriter_fourcc(*fourcc), float(fps), size)
        if w.isOpened():
            return w, stem + ext
        w.release()
    raise RuntimeError("no working video codec for " + path)


def render(video, out_path, kp_px, kin, per_frame, cal_inv, half_cm, start=0, stop=None, progress=None,
           scale=1.0):
    """kp_px: {role: (N,2) image px}; kin/per_frame: tables with gaze info per frame;
    cal_inv: function cm (N,2) -> image px for drawing the gaze line (None = skip)."""
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    stop = n if stop is None else min(stop, n)
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) * scale), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) * scale)
    writer, out_path = open_writer(out_path, fps, (W, H))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start)
    inset = 170
    for i in range(start, stop):
        ok, fr = cap.read()
        if not ok:
            break
        if fr.ndim == 2:
            fr = cv2.cvtColor(fr, cv2.COLOR_GRAY2BGR)
        if scale != 1.0:
            fr = cv2.resize(fr, (W, H), interpolation=cv2.INTER_AREA)
        for role, xy in kp_px.items():
            if i < len(xy) and np.isfinite(xy[i]).all():
                cv2.circle(fr, tuple(int(v * scale) for v in xy[i]), max(3, int(6 * scale)), COL.get(role, (255, 255, 255)), -1)
        if i < len(kin) and cal_inv is not None:
            k = kin.iloc[i]
            if np.isfinite(k["head_x"]) and np.isfinite(k["gaze_dist_cm"]):
                p0 = np.array([[k["head_x"], k["head_y"]]])
                p1 = p0 + k["gaze_dist_cm"] * np.array([[k["dir_x"], k["dir_y"]]])
                a, b = cal_inv(np.vstack([p0, p1])) * scale
                if np.isfinite(a).all() and np.isfinite(b).all():
                    cv2.line(fr, tuple(a.astype(int)), tuple(b.astype(int)), (0, 215, 255), max(2, int(3 * scale)))
        # top-view inset
        x0, y0 = W - inset - 12, 12
        cv2.rectangle(fr, (x0, y0), (x0 + inset, y0 + inset), (30, 20, 16), -1)
        m = 18
        cv2.rectangle(fr, (x0 + m, y0 + m), (x0 + inset - m, y0 + inset - m), (200, 200, 200), 2)
        c = np.array([x0 + inset / 2, y0 + inset / 2])
        sc = (inset / 2 - m) / half_cm
        if i < len(kin):
            k = kin.iloc[i]
            if np.isfinite(k["head_x"]):
                hp = c + sc * np.array([k["head_x"], -k["head_y"]])
                cv2.circle(fr, tuple(hp.astype(int)), 4, (255, 255, 255), -1)
                if np.isfinite(k["gaze_dist_cm"]):
                    gp = hp + sc * k["gaze_dist_cm"] * np.array([k["dir_x"], -k["dir_y"]])
                    cv2.line(fr, tuple(hp.astype(int)), tuple(gp.astype(int)), (0, 215, 255), 2)
                    cv2.circle(fr, tuple(gp.astype(int)), 6, (0, 215, 255), -1)
        # status text
        txt = "t %.2f s" % (i / fps)
        col = (220, 220, 220)
        if per_frame is not None and i < len(per_frame):
            r = per_frame.iloc[i]
            if np.isfinite(r["trial"]):
                txt += "   trial %d  stimulus %+g deg/s" % (int(r["trial"]), r["stim_speed_signed"])
                col = (60, 60, 255)
                cv2.rectangle(fr, (0, 0), (W - 1, H - 1), (60, 60, 255), 6)
            if np.isfinite(r.get("yaw_vel", np.nan)):
                txt += "   head %+.1f deg/s" % r["yaw_vel"]
        cv2.putText(fr, txt, (14, H - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.7 * max(scale, 0.6), (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(fr, txt, (14, H - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.7 * max(scale, 0.6), col, 2, cv2.LINE_AA)
        writer.write(fr)
        if progress and (i - start) % 25 == 0:
            progress(i - start, stop - start)
    writer.release()
    cap.release()
    return out_path

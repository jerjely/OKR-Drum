"""Camera calibration: lens distortion (checkerboard) and the mapping from image pixels to
centimetres in the arena frame (origin = pedestal centre, x right, y up, at pedestal-top
height, rotated so the arena walls are axis-aligned).

A calibration is a plain dict (saved as JSON):
    size        [w, h] of the camera image it belongs to
    K, D        camera matrix and distortion (None = no lens correction)
    H           3x3 homography undistorted px -> board cm (None = simple scale)
    px_per_cm   simple scale (used when H is None)
    centre_px   pedestal centre in the raw image
    rotation    deg, turns the image so the arena walls are horizontal/vertical
    mirror      true if the image is mirrored (camera seen from below / flipped sensor)
    rms         lens-fit reprojection error, px
"""
from __future__ import annotations

import json

import cv2
import numpy as np


def find_corners(img, pattern):
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ok, corners = cv2.findChessboardCorners(gray, pattern,
                                            cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE)
    if not ok:
        return None
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 1e-4)
    return cv2.cornerSubPix(gray, corners, (7, 7), (-1, -1), crit)


def board_points(cols, rows, square_mm):
    obj = np.zeros((rows * cols, 3), np.float32)
    obj[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2) * square_mm
    return obj


def frames_from_video(path, n=30):
    """Up to n evenly spaced frames of a calibration video."""
    cap = cv2.VideoCapture(path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    out = []
    for i in np.linspace(0, total - 1, min(n, total)).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, fr = cap.read()
        if ok:
            out.append(fr)
    cap.release()
    return out


def calibrate_lens(images, cols=9, rows=6, square_mm=10.0, progress=None):
    """images: list of arrays. Returns (K, D, rms, n_used, size)."""
    pattern = (cols, rows)
    objp = board_points(cols, rows, square_mm)
    op, ip, size = [], [], None
    for i, img in enumerate(images):
        if progress:
            progress(i, len(images))
        size = (img.shape[1], img.shape[0])
        c = find_corners(img, pattern)
        if c is not None:
            op.append(objp)
            ip.append(c)
    if len(ip) < 6:
        raise ValueError("checkerboard found in only %d image(s); need at least 6 (20-30 is best)" % len(ip))
    rms, K, D, _, _ = cv2.calibrateCamera(op, ip, size, None, None, flags=cv2.CALIB_RATIONAL_MODEL)
    return K, D, float(rms), len(ip), size


def undistort_px(pts, K, D):
    pts = np.asarray(pts, np.float64).reshape(-1, 1, 2)
    if K is None:
        return pts.reshape(-1, 2)
    return cv2.undistortPoints(pts, np.asarray(K), np.asarray(D), P=np.asarray(K)).reshape(-1, 2)


def plane_from_board(img, cols, rows, square_mm, K=None, D=None):
    """Homography undistorted px -> board cm, from one image of the board lying at
    pedestal-top height. Returns (H, max_err_mm)."""
    c = find_corners(img, (cols, rows))
    if c is None:
        raise ValueError("checkerboard not found in the plane image")
    und = undistort_px(c, K, D)
    board = board_points(cols, rows, square_mm)[:, :2] / 10.0
    H, _ = cv2.findHomography(und, board)
    # keep the board frame un-mirrored relative to the image (corner order can flip it)
    m = und.mean(0)
    p0, px, py = (cv2.perspectiveTransform(np.array([[q]], np.float64), H)[0, 0]
                  for q in (m, m + [1, 0], m + [0, 1]))
    ax_, ay_ = px - p0, py - p0
    if ax_[0] * ay_[1] - ax_[1] * ay_[0] < 0:
        H = np.diag([1.0, -1.0, 1.0]) @ H
        board = board * [1, -1]
    back = cv2.perspectiveTransform(und.reshape(-1, 1, 2), H).reshape(-1, 2)
    return H, float(np.abs(back - board).max() * 10)


def new_calibration(size):
    return {"size": list(size), "K": None, "D": None, "H": None, "px_per_cm": None,
            "centre_px": [size[0] / 2, size[1] / 2], "rotation": 0.0, "mirror": False, "rms": None}


def scale_from_circle(points_px, diameter_cm):
    """Pedestal (or any circle of known size) clicked on its rim -> (centre_px, px_per_cm)."""
    p = np.asarray(points_px, float)
    A = np.c_[2 * p[:, 0], 2 * p[:, 1], np.ones(len(p))]
    sol, *_ = np.linalg.lstsq(A, p[:, 0] ** 2 + p[:, 1] ** 2, rcond=None)
    cx, cy = sol[0], sol[1]
    r = np.sqrt(max(sol[2] + cx ** 2 + cy ** 2, 0))
    return [float(cx), float(cy)], float(2 * r / diameter_cm)


def rotation_from_wall(p1, p2):
    """Two points clicked along one arena wall (or a screen edge) -> rotation (deg) that
    makes that wall horizontal."""
    (x1, y1), (x2, y2) = p1, p2
    a = np.degrees(np.arctan2(-(y2 - y1), x2 - x1))          # image y points down
    return float(-((a + 45) % 90 - 45))


def to_cm(xy_px, cal):
    """Image pixels (N x 2, NaN allowed) -> arena cm (x right, y up), origin pedestal centre."""
    xy = np.asarray(xy_px, float).reshape(-1, 2)
    out = np.full_like(xy, np.nan)
    good = np.isfinite(xy).all(1)
    if not good.any():
        return out
    K, D = cal.get("K"), cal.get("D")
    pts = undistort_px(xy[good], K, D)
    centre = undistort_px([cal["centre_px"]], K, D)
    if cal.get("H") is not None:
        H = np.asarray(cal["H"], float)
        cm = cv2.perspectiveTransform(pts.reshape(-1, 1, 2), H).reshape(-1, 2)
        c0 = cv2.perspectiveTransform(centre.reshape(-1, 1, 2), H).reshape(-1, 2)
        v = cm - c0
        # board axes: x along the board, y down the board (like the image) -> flip y
        v[:, 1] *= -1
    else:
        s = cal.get("px_per_cm") or 1.0
        v = (pts - centre) / s
        v[:, 1] *= -1
    if cal.get("mirror"):
        v[:, 0] *= -1
    a = np.radians(cal.get("rotation") or 0.0)
    R = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    out[good] = v @ R.T
    return out


def save(cal, path):
    def conv(o):
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, (np.floating, np.integer)):
            return o.item()
        raise TypeError(type(o))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cal, f, indent=1, default=conv)


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def undistort_image(img, cal):
    if cal.get("K") is None:
        return img
    return cv2.undistort(img, np.asarray(cal["K"]), np.asarray(cal["D"]))


def from_cm(cm, cal):
    """Inverse of to_cm: arena cm (N,2) -> raw image pixels (for drawing)."""
    v = np.asarray(cm, float).reshape(-1, 2).copy()
    a = -np.radians(cal.get("rotation") or 0.0)
    R = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    v = v @ R.T
    if cal.get("mirror"):
        v[:, 0] *= -1
    v[:, 1] *= -1
    K, D = cal.get("K"), cal.get("D")
    centre = undistort_px([cal["centre_px"]], K, D)
    if cal.get("H") is not None:
        H = np.asarray(cal["H"], float)
        c0 = cv2.perspectiveTransform(centre.reshape(-1, 1, 2), H).reshape(-1, 2)
        und = cv2.perspectiveTransform((v + c0).reshape(-1, 1, 2), np.linalg.inv(H)).reshape(-1, 2)
    else:
        und = centre + v * (cal.get("px_per_cm") or 1.0)
    if K is None:
        return und
    K = np.asarray(K, float)
    norm = np.c_[(und[:, 0] - K[0, 2]) / K[0, 0], (und[:, 1] - K[1, 2]) / K[1, 1], np.ones(len(und))]
    px, _ = cv2.projectPoints(norm, np.zeros(3), np.zeros(3), K, np.asarray(D, float))
    return px.reshape(-1, 2)

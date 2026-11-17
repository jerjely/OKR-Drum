"""Drum geometry: where every screen pixel lies, seen from the arena centre.

Coordinates (top view, cm): origin at the arena centre (pedestal), x to the right, y "up"
in the camera image. Screen k (k = 0..3) faces the centre from azimuth k*90 deg; its own
azimuth axis runs from -45 deg (left end, seen from the pedestal) to +45 deg. Azimuths in
the drum frame are k*90 + screen azimuth, so the four screens tile 360 deg.

The pinwheel layout leaves the visible screen area shifted by the bezel at one end
(the "seam"), which is why every screen spans e.g. -42.7 .. +44.9 deg, not +-45 deg.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np


@dataclass
class Rig:
    vis_w: float = 40.98        # visible screen width, cm
    vis_h: float = 23.0         # visible screen height, cm
    dist: float = 21.35         # arena centre -> screen surface, cm
    seam: float = 1.65          # bezel visible at the seam end, cm
    seam_side: str = "left"     # end of each screen that stops short of the corner (from pedestal)
    eye_height: float = 0.0     # eye height relative to the screen centre, cm (+ = above)
    gamma: float = 1.0          # monitor gamma (1 = linear, fitted with the luminance tool)
    screen: int = 1             # display that shows the stimulus (1 = main)
    res_w: int = 1024
    res_h: int = 768
    fullscreen: bool = True

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        f = {k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__}
        return cls(**f)

    # ------------------------------------------------------------------ screen geometry
    def x_left(self) -> float:
        """x (cm, along the screen, 0 = straight ahead) of the first visible column's left edge."""
        return -self.dist + (self.seam if self.seam_side == "left" else 0.0)

    def azimuths(self, width_px: int) -> np.ndarray:
        """Azimuth (deg, -45..45 range) of every pixel column centre, seen from the arena centre."""
        x = self.x_left() + (np.arange(width_px) + 0.5) * self.vis_w / width_px
        return np.degrees(np.arctan(x / self.dist))

    def span(self):
        a = self.azimuths(2048)
        return float(a[0]), float(a[-1])

    def side_mismatch(self) -> float:
        """Visible width + bezel should equal one side of the square (2 x dist)."""
        return self.vis_w + self.seam - 2 * self.dist

    def px_per_deg_centre(self, width_px: int) -> float:
        return width_px / self.vis_w * self.dist * math.pi / 180

    def elevation(self) -> float:
        return math.degrees(math.atan(self.vis_h / 2 / self.dist))


def cycles_per_screen(bar_width_deg: float):
    """Stripes only meet at the corners with a whole number of cycles per 90 deg screen."""
    n = max(1, int(round(90.0 / (2.0 * bar_width_deg))))
    return n, 45.0 / n


def grating_values(theta_deg, phase_deg, period_deg, contrast, square=True, mean=0.5):
    """Luminance 0..1 of a grating at the given azimuths (same formula as the shader)."""
    s = np.sin(2 * np.pi / period_deg * (np.asarray(theta_deg) - phase_deg))
    if square:
        s = np.where(s >= 0, 1.0, -1.0)
    return np.clip(mean + 0.5 * contrast * s, 0, 1)


# ---------------------------------------------------------------------- gaze on the walls
def ray_to_wall(px, py, ux, uy, half):
    """Intersect rays from (px, py) along (ux, uy) with the square |x|,|y| = half.

    Arrays of equal length. Returns (wall, s, t): wall 0 = top (+y), 1 = right (+x),
    2 = bottom (-y), 3 = left (-x); s = position along the wall (cm, -half..half, left->right
    as seen from inside); t = distance to the wall. NaN where undefined.
    """
    px, py, ux, uy = (np.asarray(a, float) for a in (px, py, ux, uy))
    n = px.size
    best_t = np.full(n, np.inf)
    wall = np.full(n, -1)
    s = np.full(n, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        cand = [
            (0, (half - py) / uy, lambda t: px + t * ux),       # top wall y = +half, left->right = +x
            (1, (half - px) / ux, lambda t: -(py + t * uy)),    # right wall x = +half, left->right = -y
            (2, (-half - py) / uy, lambda t: -(px + t * ux)),   # bottom wall, left->right = -x
            (3, (-half - px) / ux, lambda t: py + t * uy),      # left wall, left->right = +y
        ]
        for k, t, along in cand:
            a = along(t)
            ok = np.isfinite(t) & (t > 0) & (np.abs(a) <= half + 1e-9) & (t < best_t)
            best_t = np.where(ok, t, best_t)
            wall = np.where(ok, k, wall)
            s = np.where(ok, a, s)
    best_t[wall < 0] = np.nan
    return wall, s, best_t


def wall_point_azimuth(wall, s, half):
    """Drum azimuth (deg, 0..360, clockwise from the top wall's centre seen from above) of a
    point on a wall, seen from the arena centre."""
    wall = np.asarray(wall)
    a = np.degrees(np.arctan2(np.asarray(s, float), half)) + 90.0 * wall
    a = np.where(wall < 0, np.nan, a)
    return np.mod(a, 360.0)

"""Monitor gamma from photometer readings: L(v) = Lmin + (Lmax - Lmin) * v ** gamma."""
from __future__ import annotations

import numpy as np

LEVELS = [0.0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1.0]


def fit_gamma(levels, readings):
    v = np.asarray(levels, float)
    L = np.asarray(readings, float)
    ok = np.isfinite(L)
    v, L = v[ok], L[ok]
    if len(v) < 3:
        raise ValueError("need at least 3 readings")
    lo, hi = L[np.argmin(v)], L[np.argmax(v)]
    if hi <= lo:
        raise ValueError("the brightest reading must be above the darkest")
    norm = (L - lo) / (hi - lo)
    m = (v > 0.02) & (v < 0.98) & (norm > 0.005)
    if m.sum() < 1:
        raise ValueError("need readings between black and white")
    g = float(np.sum(np.log(norm[m]) * np.log(v[m])) / np.sum(np.log(v[m]) ** 2))
    pred = lo + (hi - lo) * v ** g
    rms = float(np.sqrt(np.mean((pred - L) ** 2)))
    return {"gamma": g, "Lmin": float(lo), "Lmax": float(hi), "rms": rms,
            "michelson_max": float((hi - lo) / (hi + lo)) if hi + lo > 0 else float("nan"),
            "mean_lum": float(lo + (hi - lo) * 0.5)}

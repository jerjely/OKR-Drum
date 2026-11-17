"""Response graphs and PDF reports (matplotlib)."""
from __future__ import annotations

import datetime as _dt

import numpy as np
from matplotlib.figure import Figure

NAVY = "#101d3d"
LEFT, RIGHT = "#1f8fd6", "#e08a1e"
GREY = "#8a97a8"


def _style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(alpha=0.25, lw=0.6)


def trial_figure(s, trial, fig=None):
    """Head yaw and gaze point vs time for one trial, with the stimulus position."""
    fig = fig or Figure(figsize=(8, 5.2))
    fig.clear()
    w = next((w for w in s.windows if w[0] == trial), None)
    if w is None:
        return fig
    t, f0, f1 = w
    pre = max(0, f0 - int(2 * s.fps))
    post = min(len(s.kin), f1 + int(2 * s.fps))
    tt = (np.arange(pre, post) - f0) / s.fps
    row = s.trials[s.trials["trial"] == trial].iloc[0]
    d = 1 if row["direction"] == "CW" else -1
    yaw = s.kin["yaw_deg"].to_numpy()[pre:post]
    gaze = s.kin["gaze_az"].to_numpy()[pre:post]
    y0 = np.nanmean(yaw[max(0, f0 - pre - 3): f0 - pre + 1]) if np.isfinite(yaw).any() else 0
    g0 = np.nanmean(gaze[max(0, f0 - pre - 3): f0 - pre + 1]) if np.isfinite(gaze).any() else 0
    ax1, ax2 = fig.subplots(2, 1, sharex=True, gridspec_kw={"height_ratios": [3, 2]})
    dur = (f1 - f0) / s.fps
    for ax in (ax1, ax2):
        ax.axvspan(0, dur, color="#ffd666", alpha=0.25, lw=0)
        _style(ax)
    ax1.plot(tt, yaw - y0, color=NAVY, lw=1.6, label="head direction")
    ax1.plot(tt, gaze - g0, color=LEFT if d > 0 else RIGHT, lw=1.0, alpha=0.8, label="gaze point on screens")
    ts = np.clip(tt, 0, dur)
    ax1.plot(tt, d * row["speed_deg_s"] * ts, "--", color=GREY, lw=1.2, label="stimulus")
    ax1.set_ylabel("angle (deg, + = CW)")
    ax1.legend(frameon=False, fontsize=8, loc="upper left")
    v = s.kin["yaw_vel"].to_numpy()[pre:post]
    ax2.plot(tt, v, color=NAVY, lw=1.0)
    ax2.axhline(d * row["speed_deg_s"], color=GREY, ls="--", lw=1)
    ax2.axhline(0, color="k", lw=0.5)
    lim = max(3 * row["speed_deg_s"], 20)
    ax2.set_ylim(-lim, lim)
    ax2.set_ylabel("head velocity (deg/s)")
    ax2.set_xlabel("time from grating onset (s)")
    ax1.set_title("Trial %d  -  %.3f c/deg, contrast %g, %g deg/s %s  -  OKR index %.2f, slow gain %.2f, %s"
                  % (trial, row["spatial_freq_cpd"], row["contrast"], row["speed_deg_s"], row["direction"],
                     row["okr_index"], row["slow_gain"], "tracked" if row["tracked"] else "no tracking"),
                  fontsize=9, loc="left")
    fig.tight_layout()
    return fig


def tuning_figure(s_or_summary, thresholds=None, criterion=0.3, fig=None, x=None):
    """OKR index and slow-phase gain vs spatial frequency (or contrast / speed), per eye."""
    summ = getattr(s_or_summary, "summary", s_or_summary)
    thresholds = thresholds if thresholds is not None else getattr(s_or_summary, "thresholds", {})
    fig = fig or Figure(figsize=(8, 3.6))
    fig.clear()
    if summ is None or not len(summ):
        return fig
    if x is None:
        x = max(("spatial_freq_cpd", "contrast", "speed_deg_s"), key=lambda k: summ[k].nunique())
    lab = {"spatial_freq_cpd": "spatial frequency (c/deg)", "contrast": "contrast", "speed_deg_s": "speed (deg/s)"}[x]
    ax1, ax2 = fig.subplots(1, 2)
    for eye, col in (("left", LEFT), ("right", RIGHT)):
        e = summ[summ["eye"] == eye].groupby(x).mean(numeric_only=True).sort_index()
        if not len(e):
            continue
        name = "%s eye (%s)" % (eye, "CW" if eye == "left" else "CCW")
        ax1.errorbar(e.index, e["okr_index"], yerr=e["okr_index_sem"].fillna(0), color=col, marker="o", ms=4,
                     capsize=2, lw=1.5, label=name)
        ax2.errorbar(e.index, e["slow_gain"], yerr=e["slow_gain_sem"].fillna(0), color=col, marker="o", ms=4,
                     capsize=2, lw=1.5, label=name)
        th = thresholds.get("%s_%s" % (eye, x))
        if th is not None and np.isfinite(th):
            ax1.axvline(th, color=col, ls=":", lw=1.2)
            ax1.text(th, 1.02, " %.3g" % th, color=col, fontsize=8, transform=ax1.get_xaxis_transform())
    ax1.axhline(criterion, color=GREY, ls="--", lw=1)
    ax1.set_ylabel("OKR index (with - against)")
    ax2.set_ylabel("slow-phase gain")
    for ax in (ax1, ax2):
        ax.set_xlabel(lab)
        _style(ax)
    ax1.set_ylim(-0.3, 1.0)
    ax2.axhline(0, color="k", lw=0.5)
    ax1.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    return fig


def overview_figure(s, fig=None, max_trials=40):
    """Every trial's head direction (relative to onset), stacked: a quick look at the session."""
    fig = fig or Figure(figsize=(8, 6))
    fig.clear()
    ax = fig.add_subplot(111)
    _style(ax)
    for k, (t, f0, f1) in enumerate(sorted(s.windows)[:max_trials]):
        row = s.trials[s.trials["trial"] == t]
        if not len(row):
            continue
        row = row.iloc[0]
        d = 1 if row["direction"] == "CW" else -1
        yaw = s.kin["yaw_deg"].to_numpy()[f0:f1]
        if not np.isfinite(yaw).any():
            continue
        tt = np.arange(len(yaw)) / s.fps
        y = d * (yaw - yaw[np.isfinite(yaw)][0])
        ax.plot(tt, y / 30.0 + k, color=LEFT if d > 0 else RIGHT, lw=1)
        ax.text(tt[-1] + 0.1, k, "T%d %.2g c/deg %s%s" % (t, row["spatial_freq_cpd"], row["direction"],
                                                          "  *" if row["tracked"] else ""), fontsize=7, va="center")
    ax.set_xlabel("time in grating (s)")
    ax.set_ylabel("trial (head turn with stimulus, 30 deg per row)")
    ax.set_yticks([])
    ax.set_title("Head direction during each grating (* = tracking detected)", fontsize=9, loc="left")
    fig.tight_layout()
    return fig


def gaze_figure(s, fig=None):
    """Where the gaze line meets the drum walls during gratings vs grey."""
    fig = fig or Figure(figsize=(4.5, 4.5))
    fig.clear()
    ax = fig.add_subplot(111, projection="polar")
    pf = s.per_frame
    on = pf["trial"].notna()
    az = np.radians(np.mod(pf["gaze_az"], 360))
    bins = np.linspace(0, 2 * np.pi, 37)
    for mask, col, lab in ((~on, GREY, "grey"), (on, NAVY, "grating")):
        h, _ = np.histogram(az[mask & np.isfinite(az)], bins)
        if h.sum():
            ax.step(np.r_[bins[:-1], bins[0]], np.r_[h / h.sum(), h[0] / h.sum()], where="post", color=col, label=lab)
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_title("Gaze point on the drum (fraction of time)", fontsize=9)
    ax.legend(frameon=False, fontsize=8, loc="lower right", bbox_to_anchor=(1.15, -0.05))
    fig.tight_layout()
    return fig


def pdf_report(s, path, meta=None, sync=None):
    from matplotlib.backends.backend_pdf import PdfPages
    meta = meta or {}
    with PdfPages(path) as pdf:
        f = Figure(figsize=(8.27, 11.69))
        ax = f.add_axes([0.08, 0.05, 0.84, 0.9])
        ax.axis("off")
        lines = ["OKR Drum - session report", "",
                 "Animal: %s    Session: %s    Treatment: %s" % (meta.get("animal", "-"), meta.get("session", "-"),
                                                                   meta.get("treatment", "-")),
                 "Created: %s" % _dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                 "Video: %s" % (s.video or "-"), "Stimulus log: %s" % (s.stim_csv or "-"), "",
                 "Trials analysed: %d, tracking detected in %d" % (len(s.trials), int(s.trials["tracked"].sum())), ""]
        for k, v in (s.thresholds or {}).items():
            lines.append("Threshold %s: %.3f" % (k.replace("_", " "), v))
        if sync:
            lines += ["", "Sync check:"] + ["  [%s] %s" % (lv, m) for lv, m in sync]
        lines += ["", "Keypoint quality (fraction of frames above the likelihood cut-off):"]
        lines += ["  %s: %.0f %%" % (k, 100 * v) for k, v in getattr(s, "kp_good", {}).items()]
        for i, ln in enumerate(lines):
            ax.text(0, 1 - i * 0.028, ln, fontsize=14 if i == 0 else 9.5, weight="bold" if i == 0 else "normal",
                    va="top", family="DejaVu Sans")
        pdf.savefig(f)
        for fig in (tuning_figure(s, fig=Figure(figsize=(8.27, 4.2))), overview_figure(s),
                    gaze_figure(s, Figure(figsize=(6, 6)))):
            pdf.savefig(fig)
        for t in list(s.trials["trial"])[:24]:
            pdf.savefig(trial_figure(s, int(t)))
    return path

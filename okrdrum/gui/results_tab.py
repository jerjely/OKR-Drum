"""Results tab: response graphs of the current session and of the whole project."""
from __future__ import annotations

import numpy as np
from PySide6 import QtWidgets

from ..analysis import okr, report
from . import theme
from .widgets import MplCanvas, combo


class ResultsTab(QtWidgets.QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.s = None
        v = QtWidgets.QVBoxLayout(self)
        h = QtWidgets.QHBoxLayout()
        self.what = combo(["Session: response vs spatial frequency / contrast", "Session: all trials",
                           "Session: gaze on the drum", "Project: tuning by group", "Project: thresholds by group"])
        self.what.currentIndexChanged.connect(self.redraw)
        self.x = combo(["auto", "spatial_freq_cpd", "contrast", "speed_deg_s"])
        self.x.currentIndexChanged.connect(self.redraw)
        self.y = combo(["okr_index", "slow_gain", "tracked_frac", "episodes"])
        self.y.currentIndexChanged.connect(self.redraw)
        h.addWidget(QtWidgets.QLabel("Show"))
        h.addWidget(self.what, 2)
        h.addWidget(QtWidgets.QLabel("x"))
        h.addWidget(self.x)
        h.addWidget(QtWidgets.QLabel("y (project)"))
        h.addWidget(self.y)
        h.addWidget(theme.button("Save figure…", slot=self.save_fig))
        v.addLayout(h)
        self.canvas = MplCanvas((9, 5))
        v.addWidget(self.canvas, 1)
        self.note = QtWidgets.QLabel("Run an analysis (Analyze tab) or add sessions to a project to see results here.")
        self.note.setProperty("muted", True)
        v.addWidget(self.note)

    def set_session(self, s):
        self.s = s
        self.redraw()

    def redraw(self, *_):
        i = self.what.currentIndex()
        x = None if self.x.currentText() == "auto" else self.x.currentText()
        if i < 3:
            if self.s is None:
                return
            fn = [lambda fig: report.tuning_figure(self.s, criterion=self.s.params["index_criterion"], fig=fig, x=x),
                  lambda fig: report.overview_figure(self.s, fig=fig),
                  lambda fig: report.gaze_figure(self.s, fig=fig)][i]
            self.canvas.draw(fn)
            self.note.setText("Thresholds: " + (", ".join("%s %.3f" % (k.replace("_", " "), v)
                                                         for k, v in self.s.thresholds.items() if np.isfinite(v))
                                               or "not reached (criterion %.2f)" % self.s.params["index_criterion"]))
        else:
            pr = self.main.project_tab.project
            df = pr.all_trials()
            if not len(df):
                self.canvas.draw(lambda fig: fig.text(0.05, 0.5, "No analysed sessions in the project yet."))
                return
            if i == 3:
                self.canvas.draw(self._group_tuning, df, x or "spatial_freq_cpd", self.y.currentText())
            else:
                self.canvas.draw(self._thresholds, pr.sessions_table())
            self.note.setText("%d trials from %d sessions" % (len(df), df["session_id"].nunique()))

    @staticmethod
    def _group_tuning(df, x, y, fig):
        df = df.copy()
        df["group_label"] = df["treatment"].replace("", np.nan).fillna(df["group"]).replace("", "all")
        axes = fig.subplots(1, 2, sharey=True)
        cols = ["#1f9fd6", "#e08a1e", "#2e9e6a", "#c8463f", "#7a5bd6", "#101d3d"]
        for ax, eye in zip(axes, ("left", "right")):
            d = df[df["eye"] == eye]
            for k, (g, gd) in enumerate(d.groupby("group_label")):
                per_animal = okr.condition_summary(gd, by=(x, "animal"))
                if y not in per_animal:
                    per_animal[y] = gd.groupby([x, "animal"])[y if y in gd else "okr_index"].mean().values
                m = per_animal.groupby(x)[y].agg(["mean", "sem", "count"])
                ax.errorbar(m.index, m["mean"], yerr=m["sem"].fillna(0), marker="o", ms=4, capsize=2,
                            color=cols[k % len(cols)], label="%s (n=%d animals)" % (g, gd["animal"].nunique()))
            ax.set_title("%s eye (%s)" % (eye, "CW" if eye == "left" else "CCW"), fontsize=10, loc="left")
            ax.set_xlabel(x.replace("_", " "))
            ax.spines[["top", "right"]].set_visible(False)
            ax.grid(alpha=0.25)
        axes[0].set_ylabel(y.replace("_", " "))
        axes[0].legend(frameon=False, fontsize=8)
        fig.tight_layout()

    @staticmethod
    def _thresholds(tab, fig):
        cols = [c for c in tab.columns if c.startswith("thr_")]
        ax = fig.add_subplot(111)
        if not cols:
            ax.text(0.05, 0.5, "No thresholds yet (sessions need a range of spatial frequencies or contrasts).")
            return
        tab = tab.copy()
        tab["group_label"] = tab["treatment"].replace("", np.nan).fillna(tab["group"]).replace("", "all")
        groups = sorted(tab["group_label"].unique())
        w = 0.8 / len(cols)
        rng = np.random.default_rng(0)
        for j, c in enumerate(cols):
            for k, g in enumerate(groups):
                vals = tab.loc[tab["group_label"] == g, c].astype(float).dropna()
                xpos = k + (j - (len(cols) - 1) / 2) * w
                ax.bar(xpos, vals.mean() if len(vals) else 0, w * 0.9, color=["#1f9fd6", "#e08a1e", "#2e9e6a",
                                                                               "#7a5bd6"][j % 4], alpha=0.35,
                       label=c[4:].replace("_", " ") if k == 0 else None)
                ax.scatter(xpos + rng.uniform(-w / 5, w / 5, len(vals)), vals, color="k", s=14, zorder=3)
        ax.set_xticks(range(len(groups)))
        ax.set_xticklabels(groups)
        ax.set_ylabel("threshold")
        ax.legend(frameon=False, fontsize=8)
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()

    def save_fig(self):
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save figure", "okr_figure.pdf",
                                                     "PDF (*.pdf);;PNG (*.png);;SVG (*.svg)")
        if p:
            self.canvas.fig.savefig(p, dpi=200, bbox_inches="tight")

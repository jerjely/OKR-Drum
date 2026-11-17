"""Project database: animals, sessions and their results in one JSON file (okr_project.json),
kept human-readable so it can be versioned, copied or opened by other tools."""
from __future__ import annotations

import datetime as _dt
import json
import os
import uuid

import pandas as pd

SESSION_FIELDS = ["animal", "date", "treatment", "group", "notes", "video", "stim_csv", "frames_csv",
                  "markers_csv", "dlc_file", "calibration"]


class Project:
    def __init__(self, path=None):
        self.path = path
        self.data = {"name": "OKR project", "created": _dt.date.today().isoformat(), "animals": {},
                     "sessions": [], "defaults": {}}
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                self.data.update(json.load(f))

    @property
    def folder(self):
        return os.path.dirname(os.path.abspath(self.path)) if self.path else os.getcwd()

    def save(self, path=None):
        self.path = path or self.path
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=1, default=str)
        os.replace(tmp, self.path)

    # paths are stored relative to the project file when possible, so the folder can move
    def _rel(self, p):
        if not p:
            return p
        try:
            r = os.path.relpath(p, self.folder)
            return r if not r.startswith("..") else os.path.abspath(p)
        except ValueError:
            return os.path.abspath(p)

    def abs(self, p):
        if not p:
            return p
        return p if os.path.isabs(p) else os.path.normpath(os.path.join(self.folder, p))

    # ------------------------------------------------------------------ animals / sessions
    def add_animal(self, name, **info):
        self.data["animals"].setdefault(name, {}).update(info)

    def add_session(self, **kw):
        s = {k: kw.get(k, "") for k in SESSION_FIELDS}
        for k in ("video", "stim_csv", "frames_csv", "markers_csv", "dlc_file", "calibration"):
            s[k] = self._rel(s[k])
        s["id"] = kw.get("id") or uuid.uuid4().hex[:8]
        s["date"] = s["date"] or _dt.date.today().isoformat()
        s["results"] = {}
        self.data["sessions"].append(s)
        if s["animal"]:
            self.add_animal(s["animal"])
        return s

    def session(self, sid):
        return next((s for s in self.data["sessions"] if s["id"] == sid), None)

    def remove_session(self, sid):
        self.data["sessions"] = [s for s in self.data["sessions"] if s["id"] != sid]

    def update(self, sid, **kw):
        s = self.session(sid)
        for k, v in kw.items():
            s[k] = self._rel(v) if k in ("video", "stim_csv", "frames_csv", "markers_csv", "dlc_file",
                                         "calibration") else v

    def store_results(self, sid, session_obj, base):
        tr = session_obj.trials
        self.session(sid)["results"] = {
            "analysed": _dt.datetime.now().isoformat(timespec="seconds"),
            "files": self._rel(base),
            "n_trials": int(len(tr)), "tracked": int(tr["tracked"].sum()) if len(tr) else 0,
            "thresholds": {k: (None if v != v else round(float(v), 4)) for k, v in session_obj.thresholds.items()},
            "mean_okr_index": round(float(tr["okr_index"].mean()), 4) if len(tr) else None,
        }

    # ------------------------------------------------------------------ export
    def sessions_table(self):
        rows = []
        for s in self.data["sessions"]:
            r = {k: s.get(k, "") for k in ("id", "animal", "date", "treatment", "group", "notes")}
            res = s.get("results") or {}
            r["n_trials"] = res.get("n_trials")
            r["tracked"] = res.get("tracked")
            for k, v in (res.get("thresholds") or {}).items():
                r["thr_" + k] = v
            r["analysed"] = res.get("analysed", "")
            rows.append(r)
        return pd.DataFrame(rows)

    def all_trials(self):
        """Every analysed trial of every session in one long table (for statistics)."""
        frames = []
        for s in self.data["sessions"]:
            base = (s.get("results") or {}).get("files")
            if not base:
                continue
            p = self.abs(base) + "_trials.csv"
            if os.path.exists(p):
                df = pd.read_csv(p)
                for k in ("id", "animal", "date", "treatment", "group"):
                    df.insert(0, "session_id" if k == "id" else k, s.get(k, ""))
                frames.append(df)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

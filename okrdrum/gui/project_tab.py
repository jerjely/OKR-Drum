"""Project tab: animals and sessions in one project file, batch analysis, exports and reports."""
from __future__ import annotations

import os

from PySide6 import QtCore, QtWidgets

from ..analysis import report
from ..analysis.session import Session
from ..project import Project
from . import theme
from .widgets import FileRow, show_in_folder, table_from_df

EDITABLE = ["animal", "date", "treatment", "group", "notes"]


class ProjectTab(QtWidgets.QWidget):
    changed = QtCore.Signal()

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.project = Project()
        v = QtWidgets.QVBoxLayout(self)
        h = QtWidgets.QHBoxLayout()
        self.name = QtWidgets.QLabel("No project file - sessions are kept until you save")
        self.name.setProperty("h2", True)
        h.addWidget(self.name, 1)
        for txt, fn, kind in (("New…", self.new, None), ("Open…", self.open, None), ("Save", self.save, "primary")):
            h.addWidget(theme.button(txt, kind, fn))
        v.addLayout(h)
        self.table = QtWidgets.QTableWidget()
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.itemChanged.connect(self._edited)
        self.table.doubleClicked.connect(lambda *_: self.open_in_analyze())
        v.addWidget(self.table, 1)
        h = QtWidgets.QHBoxLayout()
        for txt, fn, kind in (("Add session…", self.add_dialog, None), ("Remove", self.remove, None),
                              ("Open in Analyze", self.open_in_analyze, None),
                              ("Analyse all", self.analyse_all, "primary"),
                              ("Export sessions CSV", self.export_sessions, None),
                              ("Export all trials CSV", self.export_trials, None),
                              ("Session reports (PDF)", self.reports, None)):
            h.addWidget(theme.button(txt, kind, fn))
        v.addLayout(h)
        self.prog = QtWidgets.QProgressBar()
        self.prog.setVisible(False)
        v.addWidget(self.prog)
        hint = QtWidgets.QLabel("Double-click a session to open it in Analyze. Animal, date, treatment, group and notes "
                                "can be edited in the table. Paths are stored relative to the project file, so the "
                                "whole folder can be moved.")
        hint.setWordWrap(True)
        hint.setProperty("muted", True)
        v.addWidget(hint)

        g = QtWidgets.QGroupBox("Inbox - new recordings in a shared folder (e.g. Google Drive)")
        gv = QtWidgets.QVBoxLayout(g)
        h = QtWidgets.QHBoxLayout()
        self.inbox_dir = FileRow(folder=True, placeholder="e.g. G:\\My Drive\\OKR Drum  (synced by Google Drive for desktop)")
        self.inbox_dir.set(main.settings.get("inbox", ""))
        h.addWidget(self.inbox_dir, 1)
        h.addWidget(theme.button("Scan", slot=self.scan_inbox))
        self.watch = QtWidgets.QCheckBox("check every minute")
        self.watch.setChecked(bool(main.settings.get("inbox_watch")))
        self.watch.toggled.connect(lambda on: self.timer.start(60000) if on else self.timer.stop())
        h.addWidget(self.watch)
        h.addWidget(theme.button("Import selected", "good", self.import_inbox))
        gv.addLayout(h)
        self.inbox = QtWidgets.QTableWidget(0, 6)
        self.inbox.setHorizontalHeaderLabels(["video", "stimulus log (paired by time)", "trials in video", "DLC",
                                              "animal", "date"])
        self.inbox.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.inbox.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.inbox.setMaximumHeight(190)
        gv.addWidget(self.inbox)
        v.addWidget(g)
        self.pairs = []
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(lambda: self.scan_inbox(quiet=True))
        if self.watch.isChecked():
            self.timer.start(60000)
        last = main.settings.get("last_project")
        if last and os.path.exists(last):
            self.load(last)

    # ------------------------------------------------------------------ file
    def load(self, path):
        try:
            self.project = Project(path)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Project", str(e))
            return
        self.main.settings["last_project"] = path
        self.refresh()

    def new(self):
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self, "New project", "okr_project.json", "OKR project (*.json)")
        if p:
            self.project = Project()
            self.project.data["name"] = os.path.splitext(os.path.basename(p))[0]
            self.project.save(p)
            self.main.settings["last_project"] = p
            self.refresh()

    def open(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open project", "", "OKR project (*.json)")
        if p:
            self.load(p)

    def save(self):
        if not self.project.path:
            p, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save project", "okr_project.json",
                                                         "OKR project (*.json)")
            if not p:
                return
            self.project.path = p
        self.project.save()
        self.main.settings["last_project"] = self.project.path
        self.refresh()
        self.main.status("Project saved: %s" % self.project.path)

    def refresh(self):
        self.name.setText(("Project: %s" % os.path.basename(self.project.path)) if self.project.path
                          else "No project file - sessions are kept until you save")
        df = self.project.sessions_table()
        self.table.blockSignals(True)
        if len(df):
            table_from_df(self.table, df)
            for r in range(self.table.rowCount()):
                for c in range(self.table.columnCount()):
                    it = self.table.item(r, c)
                    if it and self.table.horizontalHeaderItem(c).text() not in EDITABLE:
                        it.setFlags(it.flags() & ~QtCore.Qt.ItemIsEditable)
        else:
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
        self.table.blockSignals(False)
        self.changed.emit()

    def _edited(self, it):
        col = self.table.horizontalHeaderItem(it.column()).text()
        sid = self.table.item(it.row(), 0).text()
        if col in EDITABLE:
            self.project.update(sid, **{col: it.text()})
            if col == "animal" and it.text():
                self.project.add_animal(it.text())

    def _selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.table.item(r, 0).text() for r in rows]

    # ------------------------------------------------------------------ sessions
    def add_from_session(self, s):
        meta = self.main.current_meta()
        ss = self.project.add_session(animal=meta.get("animal", ""), treatment=meta.get("treatment", ""),
                                      video=s.video, stim_csv=s.stim_csv, frames_csv=s.frames_csv,
                                      markers_csv=s.markers_csv, dlc_file=s.dlc_file,
                                      calibration=s.calibration if isinstance(s.calibration, str) else "")
        base = s.save()
        self.project.store_results(ss["id"], s, base)
        if self.project.path:
            self.project.save()
        self.refresh()
        self.main.status("Session added to the project%s" % ("" if self.project.path else " (not saved yet)"))

    def add_dialog(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Pi video of the session", "",
                                                     "Video (*.mp4 *.avi *.mov);;All files (*)")
        if not p:
            return
        from ..analysis import okr, tracking
        comp = okr.guess_companions(p)
        stim, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Stimulus log of the same session",
                                                        os.path.dirname(p), "Stimulus log (*.csv)")
        animal, ok = QtWidgets.QInputDialog.getText(self, "Animal", "Animal ID:")
        self.project.add_session(animal=animal if ok else "", video=p, stim_csv=stim, frames_csv=comp["frames"],
                                 markers_csv=comp["markers"], dlc_file=tracking.find_dlc_output(p) or "",
                                 calibration=self.main.settings.get("last_calibration", ""))
        self.refresh()

    def remove(self):
        for sid in self._selected():
            self.project.remove_session(sid)
        self.refresh()

    def _session_obj(self, rec):
        a = self.project.abs
        return Session(video=a(rec.get("video")) or None, stim_csv=a(rec.get("stim_csv")),
                       frames_csv=a(rec.get("frames_csv")) or None, markers_csv=a(rec.get("markers_csv")) or None,
                       dlc_file=a(rec.get("dlc_file")), calibration=a(rec.get("calibration")) or None,
                       params=self.main.analyze_tab.params())

    def open_in_analyze(self):
        sel = self._selected()
        if not sel:
            return
        rec = self.project.session(sel[0])
        a = self.project.abs
        self.main.analyze_tab.set_files(video=a(rec.get("video")), stim_csv=a(rec.get("stim_csv")),
                                        frames_csv=a(rec.get("frames_csv")), markers_csv=a(rec.get("markers_csv")),
                                        dlc_file=a(rec.get("dlc_file")), calibration=a(rec.get("calibration")))
        self.main.tabs.setCurrentWidget(self.main.analyze_tab)

    def analyse_all(self):
        recs = [self.project.session(i) for i in (self._selected() or [s["id"] for s in self.project.data["sessions"]])]
        self.prog.setVisible(True)
        self.prog.setMaximum(len(recs))
        problems = []
        for k, rec in enumerate(recs):
            self.prog.setValue(k)
            QtWidgets.QApplication.processEvents()
            try:
                s = self._session_obj(rec).run_all()
                self.project.store_results(rec["id"], s, s.save())
            except Exception as e:
                problems.append("%s (%s): %s" % (rec.get("animal") or rec["id"], rec.get("date"), e))
        self.prog.setVisible(False)
        if self.project.path:
            self.project.save()
        self.refresh()
        if problems:
            QtWidgets.QMessageBox.warning(self, "Analyse all", "Not analysed:\n\n" + "\n".join(problems))
        else:
            self.main.status("Analysed %d session(s)" % len(recs))

    def export_sessions(self):
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Sessions", "okr_sessions.csv", "CSV (*.csv)")
        if p:
            self.project.sessions_table().to_csv(p, index=False)
            show_in_folder(p)

    def export_trials(self):
        df = self.project.all_trials()
        if not len(df):
            QtWidgets.QMessageBox.information(self, "Export", "No analysed sessions yet.")
            return
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self, "All trials", "okr_all_trials.csv", "CSV (*.csv)")
        if p:
            df.to_csv(p, index=False)
            show_in_folder(p)

    def reports(self):
        recs = [self.project.session(i) for i in self._selected()] or self.project.data["sessions"]
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Folder for the PDF reports", self.project.folder)
        if not folder:
            return
        done = 0
        for rec in recs:
            try:
                s = self._session_obj(rec).run_all()
                name = "%s_%s_%s_report.pdf" % (rec.get("animal") or "animal", rec.get("date"), rec["id"])
                report.pdf_report(s, os.path.join(folder, name), rec, s.sync_report())
                done += 1
            except Exception as e:
                self.main.status("Report for %s failed: %s" % (rec["id"], e))
        self.main.status("Wrote %d report(s)" % done)
        show_in_folder(folder)

    # ------------------------------------------------------------------ inbox
    def scan_inbox(self, quiet=False):
        from ..inbox import pair_sessions
        folder = self.inbox_dir.path()
        if not folder or not os.path.isdir(folder):
            if not quiet:
                QtWidgets.QMessageBox.information(self, "Inbox", "Choose the shared folder first.")
            return
        self.main.settings.update(inbox=folder, inbox_watch=self.watch.isChecked())
        known = {os.path.normcase(self.project.abs(s.get("video")) or "") for s in self.project.data["sessions"]}
        self.pairs = [p for p in pair_sessions(folder) if os.path.normcase(p["video"]) not in known]
        self.inbox.setRowCount(len(self.pairs))
        for r, p in enumerate(self.pairs):
            vals = [os.path.basename(p["video"]), os.path.basename(p["stim_csv"]) if p["stim_csv"] else "- not found -",
                    p["n_inside"], "yes" if p["dlc_file"] else "not yet", p["animal"], p["date"]]
            for c, val in enumerate(vals):
                self.inbox.setItem(r, c, QtWidgets.QTableWidgetItem(str(val)))
        self.inbox.resizeColumnsToContents()
        self.inbox.horizontalHeader().setStretchLastSection(True)
        if self.pairs:
            self.main.status("Inbox: %d new recording(s)" % len(self.pairs))

    def import_inbox(self):
        rows = sorted({i.row() for i in self.inbox.selectedIndexes()}) or list(range(len(self.pairs)))
        for r in rows:
            p = self.pairs[r]
            self.project.add_session(animal=p["animal"], treatment=p["treatment"], date=p["date"], video=p["video"],
                                     stim_csv=p["stim_csv"] or "", frames_csv=p["frames_csv"] or "",
                                     markers_csv=p["markers_csv"] or "", dlc_file=p["dlc_file"],
                                     calibration=self.main.settings.get("last_calibration", ""))
        if self.project.path:
            self.project.save()
        self.refresh()
        self.scan_inbox(quiet=True)

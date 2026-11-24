"""Upload finished recordings to Google Drive (or any cloud rclone supports) in the background.

Uses rclone (sudo apt install rclone; then once: rclone config -> new remote "gdrive", type
"drive"). Files go to <remote>/<YYYY-MM-DD>/. The queue is saved, so uploads that could not
finish (no network, Pi switched off) continue next time the recorder starts.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time

from .core import CONFIG_DIR

QUEUE_FILE = os.path.join(CONFIG_DIR, "upload_queue.json")


def rclone_path():
    return shutil.which("rclone")


def explain_error(err, remote=""):
    """Turn rclone's error output (often a JSON blob from Google/Microsoft) into one readable line."""
    import re
    text = (err or "").strip()
    low = text.lower()
    name = remote.split(":")[0] + ":" if ":" in remote else "the remote:"
    if not text:
        return "unknown error"
    if any(k in low for k in ("invalid_grant", "aadsts", "token has been expired", "token expired",
                              "couldn't fetch token", "unauthorized", "error 401", "status 401")):
        return ("sign-in expired or refused - in a terminal run:  rclone config reconnect %s" % name)
    if "didn't find section in config file" in low or "not found in config" in low:
        return "no remote called %s - check the name with: rclone listremotes" % name
    if any(k in low for k in ("no such host", "network is unreachable", "dial tcp", "timeout", "i/o timeout")):
        return "no internet connection - will retry"
    if "quota" in low or "storage" in low and "full" in low:
        return "the cloud storage is full"
    lines = [ln for ln in text.splitlines() if "ERROR" in ln or "Failed" in ln] or text.splitlines()
    line = re.sub(r"^\S+ \S+ (ERROR|NOTICE|Failed)\s*:?\s*", "", lines[-1]).strip()
    line = re.sub(r"\{.*", "", line).strip(" :(") or lines[-1]
    return line[:120]


def list_remotes():
    exe = rclone_path()
    if not exe:
        return []
    try:
        r = subprocess.run([exe, "listremotes"], capture_output=True, text=True, timeout=20)
        return [x.strip() for x in r.stdout.splitlines() if x.strip()]
    except Exception:
        return []


class Uploader(threading.Thread):
    def __init__(self, remote, delete_local=False, runner=None):
        super().__init__(daemon=True)
        self.remote, self.delete_local = remote.rstrip("/"), delete_local
        self.run_cmd = runner or (lambda cmd: subprocess.run(cmd, capture_output=True, text=True, timeout=6 * 3600))
        self.lock = threading.Lock()
        self.queue = self._load()
        # files still waiting go to the destination chosen now (a changed destination fixes a stuck queue)
        for it in self.queue:
            day = it.get("day") or it["dest"].rstrip("/").rsplit("/", 1)[-1]
            it["day"], it["dest"] = day, "%s/%s" % (self.remote, day)
        self.status, self.done, self.failed = "idle", [], []
        self.wake = threading.Event()
        self.stop_flag = False

    def _load(self):
        try:
            with open(QUEUE_FILE, encoding="utf-8") as f:
                return [q for q in json.load(f) if os.path.exists(q["file"])]
        except Exception:
            return []

    def _save(self):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(QUEUE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.queue, f, indent=1)
        except Exception:
            pass

    def add(self, files, day=None):
        day = day or time.strftime("%Y-%m-%d")
        with self.lock:
            for p in files:
                if p and os.path.exists(p):
                    self.queue.append({"file": os.path.abspath(p), "dest": "%s/%s" % (self.remote, day), "day": day,
                                       "tries": 0})
            self._save()
        self.wake.set()

    def pending(self):
        with self.lock:
            return len(self.queue)

    def run(self):
        exe = rclone_path() or "rclone"
        while not self.stop_flag:
            with self.lock:
                item = self.queue[0] if self.queue else None
            if item is None:
                self.status = "idle"
                self.wake.wait(30)
                self.wake.clear()
                continue
            name = os.path.basename(item["file"])
            self.status = "uploading %s" % name
            verb = "moveto" if self.delete_local else "copyto"
            cmd = [exe, verb, item["file"], "%s/%s" % (item["dest"], name), "--retries", "3",
                   "--low-level-retries", "10"]
            try:
                r = self.run_cmd(cmd)
                ok = r.returncode == 0
                err = (r.stderr or "")[-300:]
            except Exception as e:
                ok, err = False, str(e)
            with self.lock:
                if ok:
                    self.queue.pop(0)
                    self.done.append(name)
                else:
                    item["tries"] += 1
                    self.queue.append(self.queue.pop(0))       # try the others first
                    self.failed.append((name, err))
                self._save()
            if not ok:
                self.status = "waiting to retry: " + explain_error(err, self.remote)
                self.wake.wait(min(600, 30 * item["tries"]))
                self.wake.clear()

    def close(self):
        self.stop_flag = True
        self.wake.set()

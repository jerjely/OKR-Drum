"""Runs DeepLabCut in its own Python environment (DLC is not bundled with OKR Drum).

The app writes a small script and starts the chosen environment's python with it, so
analyze_videos and create_labeled_video run exactly as in that environment.
"""
from __future__ import annotations

import glob
import os
import subprocess
import sys

SCRIPT = r'''
import sys, json
args = json.loads(sys.argv[1])
import deeplabcut
print("DeepLabCut", deeplabcut.__version__, flush=True)
kw = dict(save_as_csv=True)
if args.get("destfolder"): kw["destfolder"] = args["destfolder"]
if args.get("shuffle"): kw["shuffle"] = int(args["shuffle"])
deeplabcut.analyze_videos(args["config"], args["videos"], **kw)
if args.get("filter"):
    deeplabcut.filterpredictions(args["config"], args["videos"], save_as_csv=True,
                                 **({"destfolder": args["destfolder"]} if args.get("destfolder") else {}))
if args.get("labeled"):
    deeplabcut.create_labeled_video(args["config"], args["videos"], filtered=bool(args.get("filter")),
                                    **({"destfolder": args["destfolder"]} if args.get("destfolder") else {}))
print("DLC-DONE", flush=True)
'''


def candidate_pythons():
    """Python executables of conda environments that look like DeepLabCut environments."""
    home = os.path.expanduser("~")
    roots = [os.path.join(home, d) for d in ("miniconda3", "anaconda3", "miniforge3", "mambaforge",
                                              "opt/miniconda3", "opt/anaconda3")]
    roots += [r"C:\ProgramData\miniconda3", r"C:\ProgramData\anaconda3", "/opt/miniconda3", "/opt/anaconda3"]
    if os.environ.get("CONDA_EXE"):
        roots.append(os.path.dirname(os.path.dirname(os.environ["CONDA_EXE"])))
    exe = "python.exe" if sys.platform.startswith("win") else os.path.join("bin", "python")
    found = []
    for r in roots:
        for env in sorted(glob.glob(os.path.join(r, "envs", "*"))):
            p = os.path.join(env, exe)
            if os.path.exists(p):
                found.append(p)
    dlc_first = sorted(found, key=lambda p: ("dlc" not in p.lower() and "deeplabcut" not in p.lower(), p))
    return list(dict.fromkeys(dlc_first))


def has_deeplabcut(python, timeout=120):
    try:
        r = subprocess.run([python, "-c", "import deeplabcut, sys; print(deeplabcut.__version__)"],
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout.strip().splitlines() or [""])[-1] or r.stderr.strip()[-300:]
    except Exception as e:
        return False, str(e)


def command(python, config, videos, destfolder=None, labeled=True, filter_=True, shuffle=None):
    import json
    args = {"config": config, "videos": list(videos), "destfolder": destfolder, "labeled": labeled,
            "filter": filter_, "shuffle": shuffle}
    return [python, "-u", "-c", SCRIPT, json.dumps(args)]

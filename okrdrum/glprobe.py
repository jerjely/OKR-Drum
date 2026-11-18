"""OpenGL check in a separate process.

A broken or missing graphics driver can crash the whole program inside OpenGL (an access
violation, not a Python error). So the shader is first tried in a child process: if that child
crashes, the app simply uses the CPU renderer instead of crashing itself.

    child:  OKR-Drum --gl-probe <result.json>               (built app)
            python -m okrdrum.glprobe <result.json>         (from source)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile


def _checks():
    """Runs in the child. Returns the renderer name and the shader checks."""
    from PySide6 import QtGui
    app = QtGui.QGuiApplication.instance() or QtGui.QGuiApplication(sys.argv[:1])  # noqa: F841
    from .geometry import Rig
    from .protocol import build_trials
    from .renderer import StimState, check_against_numpy, render_offscreen
    st = StimState(Rig())
    st.start_grating(build_trials({"bar_width": {"value": 2.5}})[0], t0=10.0)
    img, name = render_offscreen(st, 1024, 768, now=11.0)
    if img is None:
        return {"ok": False, "reason": name}
    checks = [[check_against_numpy(img, st, 11.0) > 0.995, "shader grating = numpy grating (moving, warped)"]]
    st.mode, st.level = 2, 0.37
    st.rig.gamma = 2.2
    img, _ = render_offscreen(st, 640, 480)
    checks.append([img is not None and check_against_numpy(img, st, 0) > 0.99, "shader flat level with gamma 2.2"])
    st.mode = 3
    img, _ = render_offscreen(st, 1024, 768)
    checks.append([img is not None and check_against_numpy(img, st, 0) > 0.99, "shader alignment lines"])
    ok = all(c[0] for c in checks)
    return {"ok": ok, "name": name, "checks": checks, "reason": "" if ok else "shader output wrong"}


def child_main(out_path):
    try:
        res = _checks()
    except Exception as e:      # Python-level errors still produce a result
        res = {"ok": False, "reason": "%s: %s" % (type(e).__name__, e)}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(res, f)
    return 0


def _command(out_path):
    if getattr(sys, "frozen", False):
        return [sys.executable, "--gl-probe", out_path], None
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ)
    env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
    return [sys.executable, "-m", "okrdrum.glprobe", out_path], env


_RESULT = None


def probe(timeout=90, refresh=False):
    """{'ok': bool, 'name': renderer, 'checks': [...], 'reason': why not} - checked once per run."""
    global _RESULT
    if _RESULT is not None and not refresh:
        return _RESULT
    fd, out = tempfile.mkstemp(prefix="okr_glprobe_", suffix=".json")
    os.close(fd)
    os.remove(out)
    cmd, env = _command(out)
    flags = 0x08000000 if os.name == "nt" else 0          # CREATE_NO_WINDOW
    try:
        p = subprocess.run(cmd, env=env, timeout=timeout, creationflags=flags,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        code = p.returncode
    except subprocess.TimeoutExpired:
        code = "timeout"
    except Exception as e:
        code = "could not start (%s)" % e
    try:
        with open(out, encoding="utf-8") as f:
            res = json.load(f)
    except Exception:
        if isinstance(code, int):
            code = "exit code %d (0x%08X)" % (code, code & 0xFFFFFFFF)
        res = {"ok": False, "crashed": True,
               "reason": "the OpenGL test crashed (%s) - graphics driver problem" % code}
    finally:
        try:
            os.remove(out)
        except OSError:
            pass
    _RESULT = res
    return res


if __name__ == "__main__":
    sys.exit(child_main(sys.argv[1]))

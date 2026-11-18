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


def _window_check(app, timeout=10.0):
    """Open the real stimulus window (the code path a run uses), let it draw, read the image back."""
    import time
    import numpy as np
    from PySide6 import QtGui
    from .geometry import Rig
    from .protocol import build_trials
    from .renderer import GLStimWindow, StimState
    st = StimState(Rig())
    st.start_grating(build_trials({"bar_width": {"value": 5.0}})[0], t0=time.perf_counter())
    w = GLStimWindow(st)
    frames = []
    w.log.frame.connect(frames.append)
    w.resize(512, 256)
    w.show()
    t0 = time.time()
    while len(frames) < 30 and time.time() - t0 < timeout:
        app.processEvents()
        time.sleep(0.002)
    img = w.grabFramebuffer().convertToFormat(QtGui.QImage.Format_Grayscale8)
    name = w.renderer_name
    w.close()
    app.processEvents()
    ok_img = False
    if not img.isNull() and img.width() > 0:
        a = np.array(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine())[:, :img.width()]
        ok_img = int(a.min()) < 40 and int(a.max()) > 215
    dt = np.diff(frames) * 1000 if len(frames) > 2 else []
    return [len(frames) >= 30 and ok_img,
            "stimulus window draws the grating on screen (%d frames%s)" % (
                len(frames), ", %.1f ms per frame" % float(np.median(dt)) if len(dt) else "")], name


def _checks():
    """Runs in the child. Returns the renderer name and the shader checks."""
    from PySide6 import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
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
    if all(c[0] for c in checks):
        chk, wname = _window_check(app)
        checks.append(chk)
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
    if os.environ.get("OKR_DRUM_RENDERER", "").lower() == "cpu":
        _RESULT = {"ok": False, "reason": "CPU renderer chosen with OKR_DRUM_RENDERER=cpu"}
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

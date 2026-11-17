"""Run a built OKR Drum app's self-test, print its report and exit with its exit code.

    python install/run_selftest.py dist/OKR-Drum/OKR-Drum          (Linux / Windows .exe)
    python install/run_selftest.py dist/OKR-Drum.app               (macOS bundle)
"""
import os
import subprocess
import sys
import tempfile
import time


def exe_path(p):
    if p.endswith(".app"):
        return os.path.join(p, "Contents", "MacOS", "OKR-Drum")
    if os.name == "nt" and not p.lower().endswith(".exe"):
        p += ".exe"
    return p


def main():
    exe = exe_path(sys.argv[1])
    expect = sys.argv[2] if len(sys.argv) > 2 else None
    if not os.path.exists(exe):
        print("not found:", exe)
        return 2
    if expect:
        v = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=300)
        print("--version ->", repr(v.stdout.strip()))
    out = os.path.join(tempfile.gettempdir(), "okr_drum_selftest_%d.txt" % os.getpid())
    if os.path.exists(out):
        os.remove(out)
    t = time.time()
    p = subprocess.run([exe, "--selftest", out], timeout=1800)
    print("self-test took %.0f s, exit code %d" % (time.time() - t, p.returncode))
    if os.path.exists(out):
        with open(out, encoding="utf-8", errors="replace") as f:
            report = f.read()
        print(report)
        if expect and ("version " + expect) not in report:
            print("version %s not found in the self-test report" % expect)
            return 3
    else:
        print("no report written")
        return 4
    return p.returncode


if __name__ == "__main__":
    sys.exit(main())

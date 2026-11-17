"""Stimulus drawing.

The grating is computed per pixel in a small OpenGL fragment shader: every pixel column's
azimuth seen from the arena centre (atan(x / dist)), then a sine or square wave in degrees,
so bar width and speed are true degrees for the mouse. Frames are paced by the monitor's
vertical sync (swap interval 1) and every frame's time is logged.

If OpenGL is not available, a CPU renderer (QPainter) draws the same image; timing is then
not locked to the refresh, which the app reports.

Modes: 0 grey (mean luminance), 1 grating, 2 flat level (luminance tool), 3 alignment lines.
"""
from __future__ import annotations

import math
import time

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from .geometry import Rig, grating_values

try:
    from PySide6 import QtOpenGL
    HAVE_QTOPENGL = True
except Exception:          # pragma: no cover - very unusual Qt builds
    QtOpenGL = None
    HAVE_QTOPENGL = False

GL_COLOR_BUFFER_BIT = 0x4000
GL_TRIANGLE_STRIP = 0x0005
GL_FLOAT = 0x1406

VERTEX_SRC = """
attribute highp vec2 pos;
void main() { gl_Position = vec4(pos, 0.0, 1.0); }
"""

FRAGMENT_SRC = """
#ifdef GL_ES
precision highp float;
#endif
uniform vec2 res;
uniform float xleft;
uniform float visw;
uniform float dist;
uniform float phase;
uniform float period;
uniform float contrast;
uniform float meanlum;
uniform float square;
uniform float mode;
uniform float level;
uniform float gamma;
uniform float linestep;
uniform float pxdeg;
void main() {
    float x = xleft + gl_FragCoord.x / res.x * visw;
    float th = degrees(atan(x / dist));
    float L = meanlum;
    if (mode > 0.5 && mode < 1.5) {
        float s = sin(6.283185307179586 / period * (th - phase));
        if (square > 0.5) { s = (s >= 0.0) ? 1.0 : -1.0; }
        L = clamp(meanlum + 0.5 * contrast * s, 0.0, 1.0);
    } else if (mode > 1.5 && mode < 2.5) {
        L = level;
    } else if (mode > 2.5) {
        float d = abs(mod(th + 90.0 + 0.5 * linestep, linestep) - 0.5 * linestep);
        float big = abs(mod(th + 90.0 + 22.5, 45.0) - 22.5);
        float y = abs(gl_FragCoord.y - 0.5 * res.y);
        L = 0.0;
        if (d * pxdeg < 1.5) { L = 0.75; }
        if (big * pxdeg < 3.0) { L = 1.0; }
        if (y < 1.5) { L = 0.6; }
    }
    gl_FragColor = vec4(vec3(pow(L, 1.0 / gamma)), 1.0);
}
"""


class StimState:
    """What to draw. Phase advances in real time while a grating runs."""

    def __init__(self, rig: Rig):
        self.rig = rig
        self.mode = 0
        self.contrast = 1.0
        self.period = 10.0
        self.speed = 0.0
        self.direction = 1
        self.square = True
        self.mean = 0.5
        self.level = 0.5
        self.linestep = 15.0
        self.t0 = time.perf_counter()
        self.phase0 = 0.0

    def start_grating(self, trial, t0=None):
        self.mode = 1
        self.contrast = trial["contrast"]
        self.period = 2 * trial["bar_width_used_deg"]
        self.speed = trial["speed_deg_s"]
        self.direction = trial["dir_sign"]
        self.square = trial["edge"] == "square"
        self.t0 = time.perf_counter() if t0 is None else t0

    def phase(self, now=None):
        if self.mode != 1:
            return 0.0
        t = (time.perf_counter() if now is None else now) - self.t0
        return self.phase0 + self.direction * self.speed * t

    def uniforms(self, w, h, now=None):
        r = self.rig
        return {"res": (float(w), float(h)), "xleft": r.x_left(), "visw": r.vis_w, "dist": r.dist,
                "phase": self.phase(now), "period": self.period, "contrast": self.contrast,
                "meanlum": self.mean, "square": 1.0 if self.square else 0.0, "mode": float(self.mode),
                "level": self.level, "gamma": max(r.gamma, 0.1), "linestep": self.linestep,
                "pxdeg": r.px_per_deg_centre(w)}

    def cpu_row(self, w, now=None):
        """The same image row computed with numpy (CPU renderer and checks)."""
        th = self.rig.azimuths(w)
        if self.mode == 1:
            L = grating_values(th, self.phase(now), self.period, self.contrast, self.square, self.mean)
        elif self.mode == 2:
            L = np.full(w, self.level)
        elif self.mode == 3:
            pxdeg = self.rig.px_per_deg_centre(w)
            d = np.abs(np.mod(th + 90 + 0.5 * self.linestep, self.linestep) - 0.5 * self.linestep)
            big = np.abs(np.mod(th + 90 + 22.5, 45) - 22.5)
            L = np.where(big * pxdeg < 3, 1.0, np.where(d * pxdeg < 1.5, 0.75, 0.0))
        else:
            L = np.full(w, self.mean)
        return np.power(np.clip(L, 0, 1), 1.0 / max(self.rig.gamma, 0.1))


class _Quad:
    """Shader program + full-screen quad, shared by the window and the offscreen renderer."""

    def __init__(self):
        self.prog = QtOpenGL.QOpenGLShaderProgram()
        ok = self.prog.addShaderFromSourceCode(QtOpenGL.QOpenGLShader.Vertex, VERTEX_SRC)
        ok = ok and self.prog.addShaderFromSourceCode(QtOpenGL.QOpenGLShader.Fragment, FRAGMENT_SRC)
        self.prog.bindAttributeLocation("pos", 0)
        if not ok or not self.prog.link():
            raise RuntimeError("shader: " + self.prog.log())
        self.vao = QtOpenGL.QOpenGLVertexArrayObject()
        self.vao.create()
        self.vao.bind()
        self.buf = QtOpenGL.QOpenGLBuffer(QtOpenGL.QOpenGLBuffer.VertexBuffer)
        self.buf.create()
        self.buf.bind()
        data = np.array([-1, -1, 1, -1, -1, 1, 1, 1], np.float32)
        self.buf.allocate(data.tobytes(), data.nbytes)
        self.prog.bind()
        self.prog.enableAttributeArray(0)
        self.prog.setAttributeBuffer(0, GL_FLOAT, 0, 2, 0)
        self.vao.release()

    def draw(self, fns, uniforms):
        self.prog.bind()
        for k, v in uniforms.items():
            if isinstance(v, tuple):
                self.prog.setUniformValue(k, QtGui.QVector2D(*v))
            else:
                self.prog.setUniformValue1f(k, float(v))
        self.vao.bind()
        self.buf.bind()
        self.prog.enableAttributeArray(0)
        self.prog.setAttributeBuffer(0, GL_FLOAT, 0, 2, 0)
        fns.glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
        self.vao.release()


def render_offscreen(state: StimState, w=1024, h=768, now=None):
    """Draw one frame with the real shader into an image (self-test, previews).
    Returns (gray uint8 array h x w, renderer name) or (None, reason)."""
    if not HAVE_QTOPENGL:
        return None, "Qt OpenGL module missing"
    fmt = QtGui.QSurfaceFormat()
    ctx = QtGui.QOpenGLContext()
    ctx.setFormat(fmt)
    if not ctx.create():
        return None, "no OpenGL context"
    surf = QtGui.QOffscreenSurface()
    surf.setFormat(ctx.format())
    surf.create()
    if not ctx.makeCurrent(surf):
        return None, "cannot make the OpenGL context current"
    try:
        fbo = QtOpenGL.QOpenGLFramebufferObject(w, h)
        fbo.bind()
        fns = ctx.functions()
        fns.glViewport(0, 0, w, h)
        quad = _Quad()
        quad.draw(fns, state.uniforms(w, h, now))
        img = fbo.toImage().convertToFormat(QtGui.QImage.Format_Grayscale8)
        fbo.release()
        arr = np.array(img.constBits(), np.uint8).reshape(h, img.bytesPerLine())[:, :w].copy()
        name = fns.glGetString(0x1F01) if hasattr(fns, "glGetString") else "OpenGL"
        return arr, str(name)
    except Exception as e:      # shader or FBO problems
        return None, str(e)
    finally:
        ctx.doneCurrent()


# ---------------------------------------------------------------------- windows
class _FrameLog(QtCore.QObject):
    frame = QtCore.Signal(float)     # perf_counter time at which a frame was handed to the display


if HAVE_QTOPENGL:
    class GLStimWindow(QtOpenGL.QOpenGLWindow):
        """Full-screen OpenGL window on the stimulus display, redrawn every refresh."""

        def __init__(self, state: StimState):
            super().__init__(QtOpenGL.QOpenGLWindow.NoPartialUpdate)
            fmt = QtGui.QSurfaceFormat()
            fmt.setSwapInterval(1)           # vsync
            self.setFormat(fmt)
            self.state = state
            self.log = _FrameLog()
            self.quad = None
            self.renderer_name = "OpenGL"
            self.on_before_draw = None       # callable(now) -> None, runs right before drawing
            self.frameSwapped.connect(self._swapped)

        def initializeGL(self):
            self.quad = _Quad()
            fns = self.context().functions()
            try:
                self.renderer_name = "OpenGL " + str(fns.glGetString(0x1F01))
            except Exception:
                pass

        def paintGL(self):
            now = time.perf_counter()
            if self.on_before_draw:
                self.on_before_draw(now)
            fns = self.context().functions()
            dpr = self.devicePixelRatio()
            w, h = int(self.width() * dpr), int(self.height() * dpr)
            fns.glViewport(0, 0, w, h)
            self.quad.draw(fns, self.state.uniforms(w, h, now))

        def _swapped(self):
            self.log.frame.emit(time.perf_counter())
            self.update()

        def keyPressEvent(self, ev):
            self.key_handler(ev) if hasattr(self, "key_handler") else None


class CPUStimWindow(QtWidgets.QWidget):
    """Fallback without OpenGL: the same image from numpy, painted with QPainter."""

    def __init__(self, state: StimState):
        super().__init__()
        self.state = state
        self.log = _FrameLog()
        self.renderer_name = "CPU (no OpenGL - timing not locked to the refresh)"
        self.on_before_draw = None
        self.setAttribute(QtCore.Qt.WA_OpaquePaintEvent)
        self.timer = QtCore.QTimer(self)
        self.timer.setTimerType(QtCore.Qt.PreciseTimer)
        self.timer.timeout.connect(self.update)
        self.timer.start(16)

    def paintEvent(self, ev):
        now = time.perf_counter()
        if self.on_before_draw:
            self.on_before_draw(now)
        w = max(1, int(self.width() * self.devicePixelRatioF()))
        row = (self.state.cpu_row(w, now) * 255).astype(np.uint8)
        img = QtGui.QImage(row.tobytes(), w, 1, w, QtGui.QImage.Format_Grayscale8)
        p = QtGui.QPainter(self)
        p.drawImage(self.rect(), img)
        p.end()
        self.log.frame.emit(time.perf_counter())

    def keyPressEvent(self, ev):
        self.key_handler(ev) if hasattr(self, "key_handler") else None


_GL_OK = None


def gl_works():
    """True if this computer's OpenGL compiles and runs the stimulus shader correctly (checked once)."""
    global _GL_OK
    if _GL_OK is None:
        try:
            st = StimState(Rig())
            from .protocol import build_trials
            st.start_grating(build_trials({"bar_width": {"value": 5.0}})[0], t0=0.0)
            img, why = render_offscreen(st, 256, 32, now=0.4)
            _GL_OK = img is not None and check_against_numpy(img, st, 0.4) > 0.98
            gl_works.reason = "" if _GL_OK else (why if img is None else "shader output wrong")
        except Exception as e:
            _GL_OK, gl_works.reason = False, str(e)
    return _GL_OK


gl_works.reason = ""


def make_stim_window(state: StimState, prefer_gl=True):
    if prefer_gl and HAVE_QTOPENGL and gl_works():
        return GLStimWindow(state)
    w = CPUStimWindow(state)
    if prefer_gl:
        w.renderer_name += " - OpenGL unavailable: %s" % (gl_works.reason or "no OpenGL")
    return w


def place_on_screen(win, rig: Rig):
    """Put the window on the chosen display, full screen or at the set size."""
    screens = QtGui.QGuiApplication.screens()
    scr = screens[min(max(rig.screen - 1, 0), len(screens) - 1)]
    geo = scr.geometry()
    if isinstance(win, QtGui.QWindow):
        win.setScreen(scr)
        win.setGeometry(geo.x(), geo.y(), rig.res_w if not rig.fullscreen else geo.width(),
                        rig.res_h if not rig.fullscreen else geo.height())
        win.showFullScreen() if rig.fullscreen else win.show()
    else:
        win.move(geo.topLeft())
        if rig.fullscreen:
            win.setWindowFlag(QtCore.Qt.FramelessWindowHint, True)
            win.setGeometry(geo)
            win.showFullScreen()
        else:
            win.resize(rig.res_w, rig.res_h)
            win.show()
    try:
        win.setCursor(QtCore.Qt.BlankCursor)
    except Exception:
        pass
    return scr


def check_against_numpy(img, state, now):
    """Fraction of columns (middle row) where the shader agrees with numpy (within 1 grey level
    for flat/grey, same side of mean for gratings)."""
    h, w = img.shape
    row = img[h // 3].astype(float) / 255     # not the middle row: alignment mode draws a line there
    ref = state.cpu_row(w, now)
    if state.mode == 1 and state.square:
        return float(np.mean((row > 0.5) == (ref > 0.5)))
    return float(np.mean(np.abs(row - ref) < 2.5 / 255 + 0.01))


def expected_phase_shift(speed, seconds, direction=1):
    return direction * speed * seconds


def describe_timing(intervals_s, refresh_hz):
    iv = np.asarray(intervals_s, float)
    if iv.size == 0:
        return {"frames": 0, "mean_ms": math.nan, "dropped": 0}
    return {"frames": int(iv.size + 1), "mean_ms": float(iv.mean() * 1000),
            "dropped": int(np.sum(iv > 1.5 / refresh_hz))}

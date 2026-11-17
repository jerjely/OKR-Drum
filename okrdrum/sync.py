"""Trial markers to the Raspberry Pi over a USB-serial adapter.

Messages (one line each, 115200 baud):
    S {"animal": ..., "treatment": ..., ...}                       session info (run start)
    T<n> c=<contrast> w=<bar width deg> v=<speed deg/s> CW|CCW     grating onset
    E<n>                                                           grating end
    X                                                              run finished
The Pi recorder timestamps them on arrival and matches them to video frames.
"""
from __future__ import annotations


def list_ports():
    """[(device, 'COM3 - USB-SERIAL CH340'), ...]"""
    try:
        from serial.tools import list_ports as lp
        return [(p.device, "%s  -  %s" % (p.device, p.description)) for p in lp.comports()]
    except Exception:
        return []


class MarkerPort:
    def __init__(self, device=None, baud=115200):
        self.device, self.ser, self.error, self.sent = device, None, "", []
        if device and device != "none":
            try:
                import serial
                self.ser = serial.Serial(device, baud, timeout=0)
            except Exception as e:
                self.error = str(e)

    @property
    def ok(self):
        return self.ser is not None

    def send(self, text):
        self.sent.append(text)
        if self.ser is not None:
            try:
                self.ser.write((text + "\n").encode())
            except Exception as e:
                self.error = str(e)

    def onset(self, trial):
        self.send("T%d c=%g w=%.3f v=%g %s" % (trial["trial"], trial["contrast"], trial["bar_width_used_deg"],
                                                trial["speed_deg_s"], trial["direction"]))

    def session(self, info):
        """'S {json}' - who / what is being recorded; the Pi fills its fields and can start recording."""
        import json
        self.send("S " + json.dumps(info, ensure_ascii=True, separators=(",", ":"), default=str))

    def run_end(self):
        """'X' - the run is over; the Pi can stop recording."""
        self.send("X")

    def end(self, trial):
        self.send("E%d" % trial["trial"])

    def close(self):
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None

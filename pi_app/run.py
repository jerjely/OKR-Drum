#!/usr/bin/env python3
"""Start the OKR Drum recorder (Raspberry Pi):  python3 run.py   (self-test: --selftest)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from okr_recorder.app import main  # noqa: E402

sys.exit(main())

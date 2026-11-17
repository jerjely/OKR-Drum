"""OKR Drum - start the app:  python okr_drum.py   (self-test: --selftest out.txt)"""
import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from okrdrum.gui.main import main
    sys.exit(main())

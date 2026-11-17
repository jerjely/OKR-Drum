# OKR Drum – Stimulus (lab PC)

Draws drifting gratings on the four monitors of the drum, warped so that bar width and
speed are true degrees seen from the pedestal, and sends a marker to the Raspberry Pi
camera at the start (`T<n> …`) and end (`E<n>`) of every grating.

**Needs:** Miniconda (or Anaconda) and PsychoPy. PsychoPy is not bundled; the installer
script puts it into a conda environment called `okr`.

| Windows | Mac |
|---|---|
| 1. Double-click `install_windows.bat` (once) | 1. Double-click `install_mac.command` (once) |
| 2. Start **OKR Drum** from the Start menu, or `run_okr.bat` | 2. Double-click `run_okr.command` |

In the settings window: tick **range** for contrast, bar width or speed to step through
start → end in intervals; pick the USB-serial adapter as **Serial port**; enter the
monitor/rig geometry. **Start run** → SPACE starts each trial, ESC goes back to the
settings, **Quit** closes. **About** shows the version.

Data go to `data/` next to the script: one CSV per run (every trial's parameters,
onset time, frames, dropped frames), plus `_settings.json` and a log.

Check the installation any time: `python okr_gui_experiment.py --selftest`

#!/bin/bash
# Double-click to run the OKR experiment (Mac). Keep next to okr_gui_experiment.py.
cd "$(dirname "$0")"
for d in "$HOME/miniconda3" "$HOME/opt/miniconda3" "/opt/miniconda3" "/opt/homebrew/Caskroom/miniconda/base" "$HOME/anaconda3"; do
  if [ -f "$d/etc/profile.d/conda.sh" ]; then source "$d/etc/profile.d/conda.sh"; break; fi
done
conda activate okr || { echo "Run install_mac.command first."; read -p "Press Enter to close"; exit 1; }
python okr_gui_experiment.py

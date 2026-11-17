#!/bin/bash
# OKR Drum - one-time setup on a Mac stimulus PC. Needs Miniconda (or Anaconda).
cd "$(dirname "$0")"
ENV_NAME=okr
for d in "$HOME/miniconda3" "$HOME/opt/miniconda3" "/opt/miniconda3" "/opt/homebrew/Caskroom/miniconda/base" "$HOME/anaconda3"; do
  if [ -f "$d/etc/profile.d/conda.sh" ]; then source "$d/etc/profile.d/conda.sh"; break; fi
done
if ! command -v conda >/dev/null; then
  echo "Miniconda was not found. Install it from https://docs.conda.io/projects/miniconda and run this again."
  read -p "Press Enter to close"; exit 1
fi
conda activate "$ENV_NAME" 2>/dev/null || { conda create -n "$ENV_NAME" python=3.10 -y && conda activate "$ENV_NAME"; } || exit 1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt || { read -p "Install failed. Press Enter to close"; exit 1; }
python okr_gui_experiment.py --selftest || { read -p "Self-test failed. Press Enter to close"; exit 1; }
echo
echo "Done. Double-click run_okr.command to start the experiment."
read -p "Press Enter to close"

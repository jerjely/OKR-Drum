# OKR Drum – Camera calibration and DeepLabCut conversion

Corrects the wide-angle lens and converts DeepLabCut tracking to centimetres, centred
on the pedestal (needed to work out the head's distance to each screen).

    pip install -r requirements.txt
    python okr_camera_calibration.py calibrate --images "calib/*.jpg" --cols 9 --rows 6 --square-mm 10 --preview
    python okr_camera_calibration.py plane --image board_on_pedestal.jpg --center-px 812 455
    python okr_camera_calibration.py dlc --csv video1DLC_resnet50.csv

1. **calibrate** – 20–30 photos of a printed checkerboard (inner corners 9 × 6), taken
   with the final focus and resolution, board moved over the whole image.
2. **plane** – one photo of the board lying flat at pedestal-top height, plus the
   pixel position of the pedestal centre.
3. **dlc** – writes `<name>_cm.csv` with every body part in cm.

Redo step 1 whenever focus or resolution changes, step 2 whenever the camera moves.
Self-test: `python okr_camera_calibration.py --selftest`

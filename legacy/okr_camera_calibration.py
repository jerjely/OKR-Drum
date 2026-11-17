"""
Wide-lens correction for the OKR drum camera (Pi HQ Camera + CS lens, Pi Camera 3 Wide, Arducam).

Three steps, each a sub-command:

1) calibrate  - lens distortion from ~20-30 checkerboard photos
     python okr_camera_calibration.py calibrate --images calib_imgs/*.jpg --cols 9 --rows 6 --square-mm 10

2) plane      - pixel -> cm mapping at pedestal-top height, from ONE photo of the
                checkerboard lying flat at pedestal-top height, plus the pixel
                position of the pedestal centre (read it off any frame)
     python okr_camera_calibration.py plane --image board_on_pedestal.jpg --center-px 812 455

3) dlc        - convert a DeepLabCut CSV to undistorted cm coordinates,
                centred on the pedestal (x right, y up in the image)
     python okr_camera_calibration.py dlc --csv video1DLC_resnet50.csv

Notes
- Take calibration photos at the SAME resolution/mode and the SAME locked focus
  as the experiment videos; changing either invalidates the calibration.
- The video itself is not undistorted: DeepLabCut runs on the raw video and only
  the tracked points are corrected (faster, no image quality loss).

Self-test on a synthetic wide-angle camera:  python okr_camera_calibration.py --selftest
"""
import argparse
import glob
import sys

import cv2
import numpy as np

__version__ = "dev"         # replaced with the release tag by the GitHub build
CALIB_FILE = 'okr_camera_calib.npz'


def find_corners(path, pattern):
    img = cv2.imread(path)
    if img is None:
        return None, None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ok, corners = cv2.findChessboardCorners(
        gray, pattern, cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE)
    if not ok:
        return None, gray.shape[::-1]
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 1e-4)
    corners = cv2.cornerSubPix(gray, corners, (7, 7), (-1, -1), crit)
    return corners, gray.shape[::-1]


def board_points(cols, rows, square_mm):
    obj = np.zeros((rows * cols, 3), np.float32)
    obj[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2) * square_mm
    return obj


def cmd_calibrate(a):
    paths = sorted(p for pat in a.images for p in glob.glob(pat))
    pattern = (a.cols, a.rows)
    objp = board_points(a.cols, a.rows, a.square_mm)
    obj_pts, img_pts, size = [], [], None
    for p in paths:
        c, s = find_corners(p, pattern)
        size = s or size
        if c is None:
            print('  no board found:', p)
            continue
        obj_pts.append(objp)
        img_pts.append(c)
    print('Board found in %d of %d images' % (len(img_pts), len(paths)))
    if len(img_pts) < 10:
        sys.exit('Need at least 10 good images (20-30 recommended).')
    flags = cv2.CALIB_RATIONAL_MODEL  # handles strong barrel distortion of wide lenses
    rms, K, D, rvecs, tvecs = cv2.calibrateCamera(obj_pts, img_pts, size, None, None, flags=flags)
    print('Reprojection error: %.3f px  (below ~1 px is good)' % rms)
    np.savez(CALIB_FILE, K=K, D=D, size=np.array(size))
    print('Saved', CALIB_FILE)
    if a.preview:
        img = cv2.imread(paths[0])
        und = cv2.undistort(img, K, D)
        cv2.imwrite('undistort_preview.jpg', np.hstack([img, und]))
        print('Wrote undistort_preview.jpg (left raw, right corrected)')


def undistort_px(pts, K, D):
    pts = np.asarray(pts, np.float64).reshape(-1, 1, 2)
    return cv2.undistortPoints(pts, K, D, P=K).reshape(-1, 2)


def cmd_plane(a):
    cal = np.load(CALIB_FILE)
    K, D = cal['K'], cal['D']
    corners, _ = find_corners(a.image, (a.cols, a.rows))
    if corners is None:
        sys.exit('Checkerboard not found in ' + a.image)
    und = undistort_px(corners, K, D)
    board_cm = board_points(a.cols, a.rows, a.square_mm)[:, :2] / 10.0
    H, _ = cv2.findHomography(und, board_cm)
    centre_cm = cv2.perspectiveTransform(
        undistort_px([a.center_px], K, D).reshape(-1, 1, 2), H).reshape(2)
    # check: known square size vs measured
    back = cv2.perspectiveTransform(und.reshape(-1, 1, 2), H).reshape(-1, 2)
    err_mm = np.abs(back - board_cm).max() * 10
    print('Max plane-fit error: %.2f mm' % err_mm)
    np.savez(CALIB_FILE, K=K, D=D, size=cal['size'], H=H, centre_cm=centre_cm)
    print('Plane mapping added to', CALIB_FILE)


def cmd_dlc(a):
    import pandas as pd
    cal = np.load(CALIB_FILE)
    if 'H' not in cal:
        sys.exit('Run the "plane" step first.')
    K, D, H, c0 = cal['K'], cal['D'], cal['H'], cal['centre_cm']
    df = pd.read_csv(a.csv, header=[0, 1, 2], index_col=0)
    scorer = df.columns.get_level_values(0)[0]
    parts = list(dict.fromkeys(df.columns.get_level_values(1)))
    out = pd.DataFrame(index=df.index)
    # sign of y flips so +y points "up" in the image, like a normal plot
    for bp in parts:
        xy = df[(scorer, bp)][['x', 'y']].to_numpy(float)
        good = np.isfinite(xy).all(axis=1)
        cm = np.full_like(xy, np.nan)
        if good.any():
            u = undistort_px(xy[good], K, D)
            cm[good] = cv2.perspectiveTransform(u.reshape(-1, 1, 2), H).reshape(-1, 2) - c0
        out[bp + '_x_cm'] = cm[:, 0]
        out[bp + '_y_cm'] = -cm[:, 1]
        out[bp + '_likelihood'] = df[(scorer, bp)]['likelihood'].to_numpy()
    dst = a.csv.replace('.csv', '_cm.csv')
    out.to_csv(dst)
    print('Wrote', dst, '(%d frames, body parts: %s)' % (len(out), ', '.join(parts)))


def selftest():
    """Renders a checkerboard through a strongly distorting synthetic lens, runs all three
    steps and checks that known positions come back in cm. Exit code 0 = all good."""
    import os
    import tempfile
    import types
    import pandas as pd
    fails = []

    def check(cond, msg):
        print(('  ok    ' if cond else '  FAIL  ') + msg)
        if not cond:
            fails.append(msg)

    print('OKR Drum camera calibration self-test, version %s' % __version__)
    W, H = 800, 600
    K = np.array([[330, 0, 400], [0, 330, 300], [0, 0, 1.]])
    D = np.array([-0.30, 0.08, 0, 0, -0.01])       # strong barrel distortion (wide lens)
    cols, rows, sq = 9, 6, 10.0
    u, v = np.meshgrid(np.arange(W), np.arange(H))
    rays = cv2.undistortPoints(np.stack([u.ravel(), v.ravel()], 1).astype(float).reshape(-1, 1, 2), K, D)
    rays = np.c_[rays.reshape(-1, 2), np.ones(W * H)]

    def render(rvec, tvec, path):
        R, _ = cv2.Rodrigues(rvec)
        t = np.asarray(tvec, float)
        nrm = R[:, 2]
        sc = (nrm @ t) / (rays @ nrm)
        P = (rays * sc[:, None] - t) @ R
        X, Y = P[:, 0], P[:, 1]
        i, j = np.floor(X / sq), np.floor(Y / sq)
        board = (X >= 0) & (X < (cols + 1) * sq) & (Y >= 0) & (Y < (rows + 1) * sq)
        margin = (X >= -sq) & (X < (cols + 2) * sq) & (Y >= -sq) & (Y < (rows + 2) * sq)
        img = np.full(X.shape, 150, np.uint8)
        img[margin] = 255
        img[board] = np.where(((i + j) % 2 == 0)[board], 0, 255)
        cv2.imwrite(path, img.reshape(H, W))

    tmp = tempfile.mkdtemp(prefix='okr_calib_selftest_')
    cwd = os.getcwd()
    os.chdir(tmp)
    try:
        rng = np.random.default_rng(1)
        for k in range(20):
            render(rng.normal(0, 0.3, 3), [rng.uniform(-110, 10), rng.uniform(-70, 0), rng.uniform(130, 230)],
                   'c%02d.png' % k)
        tv = np.array([-50., -35., 175.])
        render(np.zeros(3), tv, 'plane.png')

        def proj(x, y):
            return cv2.projectPoints(np.array([[x, y, 0.]]), np.zeros(3), tv, K, D)[0].ravel()

        centre = proj(50, 35)
        cmd_calibrate(types.SimpleNamespace(images=['c*.png'], cols=cols, rows=rows, square_mm=sq, preview=True))
        check(os.path.exists(CALIB_FILE), 'lens calibration saved')
        check(os.path.exists('undistort_preview.jpg'), 'corrected preview image written')
        cmd_plane(types.SimpleNamespace(image='plane.png', cols=cols, rows=rows, square_mm=sq,
                                        center_px=list(centre)))
        pts = [proj(50, 35), proj(70, 35), proj(50, 20), proj(80, 60)]
        expect = [(0, 0), (2.0, 0), (0, 1.5), (3.0, -2.5)]
        cols_ = pd.MultiIndex.from_tuples([('sc', 'nose', c) for c in ('x', 'y', 'likelihood')])
        pd.DataFrame([[p[0], p[1], .99] for p in pts], columns=cols_).to_csv('track.csv')
        cmd_dlc(types.SimpleNamespace(csv='track.csv'))
        out = pd.read_csv('track_cm.csv')
        err = max(np.hypot(out['nose_x_cm'][i] - ex, out['nose_y_cm'][i] - ey) for i, (ex, ey) in enumerate(expect))
        check(err < 0.05, 'tracked points back in cm, worst error %.2f mm' % (err * 10))
    finally:
        os.chdir(cwd)
    print('\nSELF-TEST %s (%d problem%s)' % ('PASSED' if not fails else 'FAILED', len(fails),
                                             '' if len(fails) == 1 else 's'))
    return 0 if not fails else 1


def main():
    if '--selftest' in sys.argv:
        sys.exit(selftest())
    if '--version' in sys.argv:
        print(__version__)
        sys.exit(0)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('calibrate', 'plane'):
        p = sub.add_parser(name)
        p.add_argument('--cols', type=int, default=9, help='inner corners along the long side')
        p.add_argument('--rows', type=int, default=6, help='inner corners along the short side')
        p.add_argument('--square-mm', type=float, default=10.0, help='measured square size in mm')
        if name == 'calibrate':
            p.add_argument('--images', nargs='+', required=True)
            p.add_argument('--preview', action='store_true')
        else:
            p.add_argument('--image', required=True)
            p.add_argument('--center-px', type=float, nargs=2, required=True, metavar=('X', 'Y'))
    p = sub.add_parser('dlc')
    p.add_argument('--csv', required=True)
    a = ap.parse_args()
    {'calibrate': cmd_calibrate, 'plane': cmd_plane, 'dlc': cmd_dlc}[a.cmd](a)


if __name__ == '__main__':
    main()

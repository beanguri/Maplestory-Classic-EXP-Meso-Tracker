"""Builds assets/filter_bar.npz: the reference status bar filter_ui.py compares a probe crop with.

    python tools/make_filter_ref.py OUT.npz REC_DIR [REC_DIR ...]

Each REC_DIR is a recording folder (record.py: full/*.png = whole game-window pictures) made with UI Size Default at an
ENLARGED size (not 1:1), the filter off. Every picture's probe crop is shrunk to design size; the reference is the mean
of the ones that look like the rest (a first mean, then only pictures within MATCH of it, so a window over the bar or a
frame without the bar doesn't spoil it). Different characters (name, level, HP numbers) average out."""
import glob
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import filter_ui

MATCH = 0.85
PER_DIR = 12


def crops(folder):
    files = sorted(glob.glob(os.path.join(folder, "full", "*.png")))
    for f in files[::max(1, len(files) // PER_DIR)][:PER_DIR]:
        img = cv2.imread(f)
        if img is None:
            continue
        h, w = img.shape[:2]
        if filter_ui.scale_of(h) < filter_ui.MIN_SCALE:
            continue
        x, y, cw, ch = filter_ui.probe_box(w, h)
        if x < 0 or y < 0 or y + ch > h or x + cw > w:
            continue
        yield filter_ui.shrink(img[y:y + ch, x:x + cw])


def main(out, folders):
    shots = [c for d in folders for c in crops(d)]
    if not shots:
        sys.exit("no usable pictures")
    mean = np.mean(shots, axis=0)
    keep = [c for c in shots if filter_ui._ncc(c, mean) >= MATCH]
    print(f"{len(shots)} pictures, {len(keep)} kept")
    if not keep:
        sys.exit("none matched their mean")
    bar = np.clip(np.mean(keep, axis=0).round(), 0, 255).astype(np.uint8)
    np.savez_compressed(out, bar=bar)
    print("wrote", out, os.path.getsize(out), "bytes")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2:])

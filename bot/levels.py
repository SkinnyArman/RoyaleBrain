"""Read a unit's level from its badge digits (owner, 2026-11-16: "read card levels yourself").

The badge finder (vision._badges) gives the badge box. Inside it the digits are white (red badge) or
yellow (the level-15 style); their pixels are cropped tightly (so a box cut a few px off doesn't
matter), resized to 22x16 and matched to labelled badges in datasets/badge_levels/<level|none>/
(nearest neighbour). Answers None when the nearest is "none" (red cloth, wood: not a badge), too far,
or the digits don't look like two digits. Labels: harvested from the enemy unit crops of the
2026-11-15/16 runs, read by eye (experiments #39).
"""
from pathlib import Path

import cv2
import numpy as np

DATA = Path(__file__).resolve().parent.parent / "datasets" / "badge_levels"
WHITE = ((0, 179), (0, 70), (190, 255))           # vision.DIGITS["enemy"]
YELLOW = ((18, 42), (80, 255), (110, 255))        # vision.DIGITS["ally"] (also the level-15 style)
MAX_DIST = 6.5                                    # beyond this 13/15 mix-ups start (#39)


def _in(hsv, rng):
    (h0, h1), (s0, s1), (v0, v1) = rng
    return cv2.inRange(hsv, (h0, s0, v0), (h1, s1, v1))


def feature(hsv):
    """HSV crop around a badge (box + ~3 px) -> 352 floats, or None if no two-digit shape."""
    m = cv2.bitwise_or(_in(hsv, WHITE), _in(hsv, YELLOW))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    H, W = hsv.shape[:2]
    keep = [i for i in range(1, n) if st[i][3] >= 0.4 * H and st[i][4] >= 15 and st[i][2] <= 0.9 * W]
    if not keep:
        return None
    sel = np.isin(lab, keep).astype(np.uint8) * 255
    ys, xs = np.nonzero(sel)
    g = sel[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    if not 0.6 * g.shape[0] <= g.shape[1] <= 2.2 * g.shape[0]:
        return None
    return cv2.resize(g, (22, 16), interpolation=cv2.INTER_AREA).astype(np.float32).ravel() / 255


class LevelReader:
    def __init__(self, data=DATA):
        X, y = [], []
        for d in sorted(Path(data).glob("*")):
            for p in sorted(d.glob("*.png")):
                f = feature(cv2.cvtColor(cv2.imread(str(p)), cv2.COLOR_BGR2HSV))
                if f is not None:
                    X.append(f)
                    y.append(None if d.name == "none" else int(d.name))
        self.X = np.array(X) if X else np.zeros((0, 352), np.float32)
        self.y = y

    def read(self, hsv, exclude=None):
        """HSV badge crop -> level (int) or None."""
        f = feature(hsv)
        if f is None or not self.y:
            return None
        d = np.linalg.norm(self.X - f, axis=1)
        if exclude is not None:
            d[exclude] = np.inf
        i = int(np.argmin(d))
        return self.y[i] if d[i] <= MAX_DIST else None


_reader = None


def reader():
    global _reader
    if _reader is None:
        _reader = LevelReader()
    return _reader

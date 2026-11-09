"""Enemy card recognition from a unit crop (as saved by Recorder.save_enemy_units).

Nearest neighbour over labelled crops in datasets/enemy_units/<card>/*.png. Features: color
histogram of the sprite (hair/armor colors separate e.g. Valkyrie orange, Musketeer purple,
Barbarian yellow) + a small grayscale thumbnail for shape. Returns None when the best match is not
close enough, so an unknown card never gets a confident wrong label.

This is a bootstrap: few samples, one opponent deck. Accuracy is measured with leave-one-out
(tools/eval_recognizer.py) and recorded in docs/experiments.md.
"""
from pathlib import Path

import cv2
import numpy as np

DATA = Path(__file__).resolve().parent.parent / "datasets" / "enemy_units"
SPRITE_ROWS = (35, 175)       # crop rows below the badge (crop is 180px tall, badge at ~row 30)


def features(crop):
    h = crop.shape[0]
    sprite = crop[min(SPRITE_ROWS[0], h - 1):min(SPRITE_ROWS[1], h)]
    sprite = cv2.resize(sprite, (64, 72))
    hsv = cv2.cvtColor(sprite, cv2.COLOR_BGR2HSV)
    # ignore grass (green, saturated) so the background doesn't dominate the colors
    grass = cv2.inRange(hsv, (35, 60, 60), (85, 255, 255))
    mask = cv2.bitwise_not(grass)
    hist = cv2.calcHist([hsv], [0, 1], mask, [18, 4], [0, 180, 0, 256]).flatten()
    hist /= hist.sum() + 1e-6
    thumb = cv2.resize(cv2.cvtColor(sprite, cv2.COLOR_BGR2GRAY), (12, 14)).flatten().astype(np.float32)
    thumb = (thumb - thumb.mean()) / (thumb.std() + 1e-6)
    return np.concatenate([hist * 4.0, thumb * 0.05]).astype(np.float32)


MAX_GRASS = 0.85      # a crop that is >85% grass has no visible unit (plain grass matched
                      # "evo_barbarians" at distance 0.99 once the cutoff went to 1.0)


def grass_fraction(crop):
    h = crop.shape[0]
    sprite = crop[min(SPRITE_ROWS[0], h - 1):min(SPRITE_ROWS[1], h)]
    hsv = cv2.cvtColor(sprite, cv2.COLOR_BGR2HSV)
    return cv2.countNonZero(cv2.inRange(hsv, (35, 60, 60), (85, 255, 255))) / float(sprite.shape[0] * sprite.shape[1])


class Recognizer:
    def __init__(self, data=DATA, max_dist=0.9):     # 27 classes (2026-11-09): 0.9 = 96% precise, 31% answered
        """max_dist 1.0: leave-one-out on 77 labelled crops (2026-11-09) answers 77% of units at 98%
        precision (0.95: 55% at 100%). Coverage matters because Poison and splash rules only act on
        named units. Unsure = None."""
        self.max_dist = max_dist
        self.X, self.y = [], []
        for d in sorted(Path(data).glob("*")) if Path(data).exists() else []:
            for p in d.glob("*.png"):
                img = cv2.imread(str(p))
                if img is not None:
                    self.X.append(features(img))
                    self.y.append(d.name)
        self.X = np.array(self.X) if self.X else np.zeros((0, 1), np.float32)

    def __bool__(self):
        return len(self.y) > 0

    def predict(self, crop, exclude=None, allowed=None):
        """(label or None, distance). `exclude`: index to leave out (leave-one-out).
        `allowed`: only these labels (e.g. the opponent's deck once known): with 27+ classes the
        open-set guess is much weaker (68% vs 91% with one deck's cards, 2026-11-09)."""
        if not self.y or grass_fraction(crop) > MAX_GRASS:
            return None, float("inf")      # nothing but grass: no unit to recognise
        d = np.linalg.norm(self.X - features(crop), axis=1)
        if exclude is not None:
            d[exclude] = np.inf
        if allowed:
            ok = {a.removeprefix("evo_") for a in allowed} | set(allowed)
            d[[y not in ok for y in self.y]] = np.inf
        i = int(np.argmin(d))
        return (self.y[i] if d[i] <= self.max_dist else None), float(d[i])

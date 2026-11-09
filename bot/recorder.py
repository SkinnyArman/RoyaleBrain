"""Per-match logging: everything needed to analyse a match afterwards and to build a training set.

runs/<YYYYmmdd-HHMMSS>/
  log.jsonl     one line per frame: t, ms, elixir, enemy_elixir, hand, enemies, spawns, action
  frames/       half-resolution JPEGs every FRAME_EVERY seconds (+ every frame where we acted)
"""
import json
import time
from pathlib import Path

import cv2

RUNS = Path(__file__).resolve().parent.parent / "runs"
FRAME_EVERY = 0.5


class Recorder:
    def __init__(self, subdir=""):
        self.dir = RUNS / subdir / time.strftime("%Y%m%d-%H%M%S")
        (self.dir / "frames").mkdir(parents=True)
        self.log = open(self.dir / "log.jsonl", "a")
        self.t0 = None                     # set by the first write (live: monotonic, replay: frame time)
        self._last_frame = -1e9

    def _t(self, now):
        if self.t0 is None:
            self.t0 = now
        return now - self.t0

    def write(self, now, img, record, force_frame=False):
        t = round(self._t(now), 3)
        record = {"t": t, **record}
        if force_frame or now - self._last_frame >= FRAME_EVERY:
            name = f"{t:08.3f}.jpg"
            small = cv2.resize(img, (img.shape[1] // 2, img.shape[0] // 2), interpolation=cv2.INTER_AREA)
            cv2.imwrite(str(self.dir / "frames" / name), small, [cv2.IMWRITE_JPEG_QUALITY, 85])
            record["frame"] = name
            self._last_frame = now
        self.log.write(json.dumps(record) + "\n")

    def save_unknown_slots(self, now, img, hand, every=2.0):
        """Save crops of hand slots we couldn't name, to turn into templates/<card>.png later."""
        if now - getattr(self, "_last_slots", -1e9) < every:
            return
        self._last_slots = now
        from . import layout as L
        d = self.dir / "unknown_slots"
        d.mkdir(exist_ok=True)
        for i, (name, (x0, y0, x1, y1)) in enumerate(zip(hand, L.SLOT_BOXES)):
            if name is None:
                cv2.imwrite(str(d / f"{self._t(now):08.2f}_slot{i}.png"), img[y0:y1, x0:x1])

    def save_enemy_units(self, now, img, tracks):
        """Crop each newly seen enemy unit (sprite sits under its level badge). These crops are the
        dataset for recognising enemy cards (Wizard vs Knight...), which the elixir counter and
        card-specific defence need."""
        from .vision import unit_crop
        d = self.dir / "enemy_units"
        d.mkdir(exist_ok=True)
        for t in tracks:
            tag = f"_{t.card}" if t.card else ""
            cv2.imwrite(str(d / f"{self._t(now):08.2f}_id{t.id}_w{int(t.w)}{tag}.png"), unit_crop(img, t.x, t.y))

    def save_play_snapshot(self, now, img, card, xy):
        """Frame crop around a detected owner play, to check the detector by eye."""
        d = self.dir / "human_plays"
        d.mkdir(exist_ok=True)
        x, y = int(xy[0]), int(xy[1])
        crop = img[max(0, y - 220):y + 140, max(0, x - 180):x + 180].copy()
        cv2.circle(crop, (min(180, x), min(220, y)), 10, (0, 0, 255), 3)
        cv2.imwrite(str(d / f"{self._t(now):07.2f}_{card}.jpg"), crop)

    def close(self):
        self.log.close()

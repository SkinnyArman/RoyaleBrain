"""Replays a recorded run's frames through the live loop, offline (no phone): `--frames runs/<id>`.

Frames are the recorder's half-res JPEGs, scaled back to 1080x2400. Taps do nothing. Used to test
pipeline changes and to compare policies on past matches.
"""
from pathlib import Path

import cv2


class FrameDevice:
    def __init__(self, run_dir):
        self.paths = sorted((Path(run_dir) / "frames").glob("*.jpg"))
        if not self.paths:
            raise SystemExit(f"no frames in {run_dir}/frames")
        self.i, self.frames, self.frame = 0, 0, None
        self.t = 0.0

    def grab(self):
        if self.i >= len(self.paths):
            raise KeyboardInterrupt            # end of recording: stop like Ctrl+C
        self.frame = cv2.resize(cv2.imread(str(self.paths[self.i])), (1080, 2400),
                                interpolation=cv2.INTER_CUBIC)
        self.t = float(self.paths[self.i].stem)          # recorded time of this frame
        self.i += 1
        self.frames += 1
        return self.frame

    def clock(self):
        """Replay time = the frame's recorded timestamp, so speeds and ETAs match the real match."""
        return self.t

    def tap(self, x, y):
        pass

    def play(self, slot_xy, target_xy):
        pass

    def close(self):
        pass

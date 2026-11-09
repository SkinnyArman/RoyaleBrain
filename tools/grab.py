"""Calibration helper.

python -m tools.grab            save a full screenshot to shots/ and print timing
python -m tools.grab --cards    also save the 4 hand-slot crops to shots/slot<N>.png;
                                rename the ones you want into templates/<card>.png
"""
import sys
import time
from pathlib import Path

import cv2

from bot import layout as L
from bot.device import Device
from bot.main import phone_serial

OUT = Path(__file__).resolve().parent.parent / "shots"


def main():
    OUT.mkdir(exist_ok=True)
    dev = Device(serial=phone_serial())
    t0 = time.monotonic()
    img = dev.grab()
    print(f"grab took {(time.monotonic() - t0) * 1000:.0f}ms, shape {img.shape}")
    stamp = time.strftime("%H%M%S")
    cv2.imwrite(str(OUT / f"screen_{stamp}.png"), img)
    if "--cards" in sys.argv:
        for i, (x0, y0, x1, y1) in enumerate(L.SLOT_BOXES):
            cv2.imwrite(str(OUT / f"slot{i}_{stamp}.png"), img[y0:y1, x0:x1])
    dev.close()
    print(f"saved to {OUT}")


if __name__ == "__main__":
    main()

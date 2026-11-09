"""Phone I/O over adb: fast raw screenshots and taps through one persistent shell."""
import subprocess

import numpy as np


class Device:
    def __init__(self, serial=None):
        self.adb = ["adb"] + (["-s", serial] if serial else [])
        # One long-lived shell: avoids starting a new adb process per tap.
        self.shell = subprocess.Popen(
            self.adb + ["shell"], stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True,
        )

    def grab(self):
        """Uncompressed screencap (no PNG encoding) -> BGR numpy image."""
        raw = subprocess.run(self.adb + ["exec-out", "screencap"],
                             capture_output=True, check=True).stdout
        w, h = np.frombuffer(raw[:8], dtype=np.uint32)
        header = len(raw) - int(w) * int(h) * 4  # 12 or 16 bytes depending on Android
        rgba = np.frombuffer(raw[header:], dtype=np.uint8).reshape(int(h), int(w), 4)
        return rgba[:, :, 2::-1].copy()  # RGBA -> BGR for OpenCV

    def tap(self, x, y):
        self.shell.stdin.write(f"input tap {int(x)} {int(y)}\n")
        self.shell.stdin.flush()

    def play(self, slot_xy, target_xy):
        """Select a card, then place it. Both taps go out in one write."""
        self.shell.stdin.write(
            f"input tap {slot_xy[0]} {slot_xy[1]}; input tap {int(target_xy[0])} {int(target_xy[1])}\n")
        self.shell.stdin.flush()

    def close(self):
        self.shell.stdin.close()
        self.shell.wait(timeout=5)

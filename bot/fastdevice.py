"""Low-latency phone I/O through the scrcpy server (v5.0.1, protocol read from its source).

Video: the scrcpy server streams raw H.264 over an adb-forwarded socket. A separate ffmpeg
process decodes it to BGR frames (separate process = parallel decoding, and no FFmpeg dylib
clash with OpenCV). A reader thread keeps only the newest frame.

Taps: 32-byte INJECT_TOUCH_EVENT messages on the control socket, a few ms each, instead of
spawning `input tap` (~100ms).
"""
import random
import shutil
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path

import numpy as np

SCRCPY_VERSION = "5.0.1"
SERVER_LOCAL = Path(shutil.which("scrcpy") or "/opt/homebrew/bin/scrcpy").resolve().parent.parent / "share/scrcpy/scrcpy-server"
SERVER_REMOTE = "/data/local/tmp/cr-bot-scrcpy-server.jar"

ACTION_DOWN, ACTION_UP = 0, 1
POINTER_ID = 0x1234  # any id that is not a mouse/finger id scrcpy reserves


class FastDevice:
    # Note: `-fflags nobuffer` makes ffmpeg 9.0 output zero frames on this stream (tested 2026-11-08).
    # `-fps_mode passthrough` stops ffmpeg from duplicating frames to fill an assumed 25 fps.
    DECODER_CMD = ["ffmpeg", "-loglevel", "error", "-flags", "low_delay",
                   "-probesize", "32", "-analyzeduration", "0", "-f", "h264", "-i", "-",
                   "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    def __init__(self, width=1080, height=2400, max_fps=60, bit_rate=8_000_000, serial=None):
        self.adb = ["adb"] + (["-s", serial] if serial else [])
        self.w, self.h = width, height
        self.frame = None
        self.frame_time = 0.0
        self.frames = 0
        self.bytes_in = 0                   # video bytes received (debugging)
        self._lock = threading.Lock()
        self._closed = False

        scid = random.randrange(0, 0x7FFFFFFF)
        self.port = 27183 + random.randrange(0, 1000)
        subprocess.run(self.adb + ["push", str(SERVER_LOCAL), SERVER_REMOTE], check=True, capture_output=True)
        subprocess.run(self.adb + ["forward", f"tcp:{self.port}", f"localabstract:scrcpy_{scid:08x}"],
                       check=True, capture_output=True)
        self.server = subprocess.Popen(
            self.adb + ["shell", f"CLASSPATH={SERVER_REMOTE}", "app_process", "/", "com.genymobile.scrcpy.Server",
                        SCRCPY_VERSION, f"scid={scid:08x}", "log_level=warn", "tunnel_forward=true",
                        "audio=false", "control=true", "video_codec=h264", f"max_fps={max_fps}",
                        f"video_bit_rate={bit_rate}", "stay_awake=true",
                        # raw_stream turns off all headers; then re-enable only the dummy byte,
                        # which tells us the server accepted the connection. Order matters.
                        "raw_stream=true", "send_dummy_byte=true"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

        self.video = self._connect(expect_dummy=True)
        self.control = self._connect(expect_dummy=False)
        self.control.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        self.decoder = subprocess.Popen(
            self.DECODER_CMD,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        threading.Thread(target=self._pump_video, daemon=True).start()
        threading.Thread(target=self._read_frames, daemon=True).start()

    def _connect(self, expect_dummy):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            s = socket.create_connection(("127.0.0.1", self.port))
            if not expect_dummy:
                return s
            # adb accepts the TCP connection even before the server listens; the dummy byte proves it's real.
            s.settimeout(2)
            try:
                if s.recv(1) == b"\x00":
                    s.settimeout(None)
                    return s
            except (socket.timeout, ConnectionError):
                pass
            s.close()
            time.sleep(0.1)
        err = self.server.stderr.read1(4000).decode(errors="replace") if self.server.poll() is not None else ""
        raise RuntimeError(f"scrcpy server did not come up. {err}")

    def _pump_video(self):
        try:
            while not self._closed:
                chunk = self.video.recv(1 << 16)
                if not chunk:
                    break
                self.bytes_in += len(chunk)
                view = memoryview(chunk)
                while view:                         # raw pipe writes can be partial
                    n = self.decoder.stdin.write(view)
                    view = view[n:]
        except (OSError, BrokenPipeError):
            pass

    def _read_frames(self):
        size = self.w * self.h * 3
        buf = bytearray(size)
        view = memoryview(buf)
        out = self.decoder.stdout
        while not self._closed:
            got = 0
            while got < size:
                n = out.readinto(view[got:])
                if not n:
                    return
                got += n
            img = np.frombuffer(bytes(buf), dtype=np.uint8).reshape(self.h, self.w, 3)
            with self._lock:
                self.frame, self.frame_time = img, time.monotonic()
                self.frames += 1

    def grab(self, timeout=3.0):
        """Newest decoded frame (BGR). Waits for the first frame after startup."""
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                if self.frame is not None:
                    return self.frame
            if time.monotonic() > deadline:
                err = ""
                if self.decoder.poll() is not None:
                    err = self.decoder.stderr.read().decode(errors="replace")[-800:]
                raise RuntimeError(f"no video frame yet: {self.bytes_in} video bytes received, "
                                   f"decoder {'exited' if self.decoder.poll() is not None else 'running'}. {err}")
            time.sleep(0.005)

    def _touch(self, action, x, y):
        msg = struct.pack(">BBqiiHHHii", 2, action, POINTER_ID, int(x), int(y),
                          self.w, self.h, 0xFFFF if action == ACTION_DOWN else 0, 0, 0)
        self.control.sendall(msg)

    def tap(self, x, y, hold=0.03):
        self._touch(ACTION_DOWN, x, y)
        time.sleep(hold)
        self._touch(ACTION_UP, x, y)

    def play(self, slot_xy, target_xy):
        """Select a card, then place it."""
        self.tap(*slot_xy)
        time.sleep(0.03)
        self.tap(*target_xy)

    def close(self):
        self._closed = True
        for s in (self.video, self.control):
            try:
                s.close()
            except OSError:
                pass
        for p in (self.decoder, self.server):
            p.kill()
        subprocess.run(self.adb + ["forward", "--remove", f"tcp:{self.port}"], capture_output=True)

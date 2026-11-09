"""Record TV Royale replays (both players visible) as learning data.

    ./tvroyale 10          from the main page: open TV Royale, watch 10 replays, record each

Per replay -> datasets/tv/<timestamp>/
  list.png        the TV Royale list entry (both 8-card decks, levels): ground truth for both decks
  frames/<t>.jpg  half-res frames at FPS (both hands, both elixir bars, the arena)
  meta.json       arena page, entry index, duration
Processing (both sides' plays -> training data) is separate: tools.tv_extract (next step).

Screen positions measured on the owner's phone (1080x2400), 2026-11-09. The arena shown is whatever
TV Royale opens on (the owner set Arena 24).
"""
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import cv2

from bot import vision
from bot.fastdevice import FastDevice
from bot.main import phone_serial

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "datasets" / "tv"
FPS = 8
MENU = (982, 290)
TV_ROYALE = (646, 511)
WATCH_Y = [1171, 1697]          # Watch buttons of the first two entries on the list
WATCH_X = 898
ENTRY_H = 526                   # list entry height (px)
ENTRY_TOP = 735                 # first entry's top edge
MAX_REPLAY_S = 330              # 3 min + overtime + loading
END_GRACE_S = 4.0               # no in-match screen this long = replay over


def adb(*args):
    subprocess.run(["adb", "-s", SERIAL, "shell", *args], capture_output=True)


def entry_crop(img, i):
    y0 = ENTRY_TOP + i * ENTRY_H
    return img[y0:y0 + ENTRY_H - 40, 40:1040]


def in_replay(img, tpl):
    """The replay screen has a smaller 'Next:' label bottom-left (score 1.0 on replays, 0.6 on a
    normal match screen, 2026-11-09)."""
    g = cv2.cvtColor(img[2150:2400, 0:300], cv2.COLOR_BGR2GRAY)
    return float(cv2.matchTemplate(g, tpl, cv2.TM_CCOEFF_NORMED).max()) >= 0.85


def record(dev, out, next_tpl):
    (out / "frames").mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    started = last_seen = None
    last_save = -1.0
    while time.monotonic() - t0 < MAX_REPLAY_S:
        img = dev.grab()
        now = time.monotonic()
        live = in_replay(img, next_tpl)
        if live:
            started = started or now
            last_seen = now
        elif started and now - last_seen > END_GRACE_S:
            break
        if live and now - last_save >= 1.0 / FPS:
            last_save = now
            small = cv2.resize(img, (540, 1200), interpolation=cv2.INTER_AREA)
            cv2.imwrite(str(out / "frames" / f"{now - started:08.3f}.jpg"), small, [cv2.IMWRITE_JPEG_QUALITY, 85])
        time.sleep(0.01)
    return (last_seen - started) if started else 0.0


OK_BUTTON = (540, 2021)          # "OK" on the replay result screen -> back to the list


def watch_buttons(img):
    """y centers of the green Watch buttons visible on the TV Royale list (right column)."""
    hsv = cv2.cvtColor(img[600:2000, 760:1020], cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, (45, 120, 120), (75, 255, 255))
    n, _, st, cen = cv2.connectedComponentsWithStats(m)
    return sorted(int(cen[i][1]) + 600 for i in range(1, n)
                  if st[i][2] > 150 and 50 < st[i][3] < 110 and st[i][4] > 0.6 * st[i][2] * st[i][3])


def deck_thumb(img, by, shift=0):
    """Small grayscale thumbnail of the two decks above a Watch button."""
    y1 = by - 110 + shift
    strip = img[max(0, y1 - 220):y1, 60:1020]          # card art only (no names / score / background)
    t = cv2.resize(cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY), (96, 22)).astype("float32")
    return (t - t.mean()) / (t.std() + 1e-6)            # watched entries turn grey: normalise brightness


def same_replay(img, by, thumbs):
    """True if the decks above this button match an already-recorded replay (tolerates the few-px
    shift the 'Watched' banner causes; an exact hash broke on it, 2026-11-09)."""
    for shift in range(-24, 25, 4):
        t = deck_thumb(img, by, shift)
        if any(float(abs(t - o).mean()) < 0.35 for o in thumbs):
            return True
    return False


def main():
    global SERIAL
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    SERIAL = phone_serial()
    dev = FastDevice(serial=SERIAL)
    next_tpl = cv2.imread(str(ROOT / "templates_ui" / "next_label_tv.png"), cv2.IMREAD_GRAYSCALE)
    import numpy as np
    seen = [np.load(p) for p in OUT.glob("*/deck_thumb.npy")]          # never record a replay twice
    done = swipes = 0
    try:
        if not watch_buttons(dev.grab()):              # not on the TV Royale list yet: open it
            adb("input", "tap", *map(str, MENU)); time.sleep(1.5)
            adb("input", "tap", *map(str, TV_ROYALE)); time.sleep(3)
            if not watch_buttons(dev.grab()):
                raise SystemExit("couldn't open TV Royale: start from the main page (Battle screen)")
        while done < n and swipes < 25:
            lst = dev.grab().copy()
            fresh = [by for by in watch_buttons(lst) if by - 470 > 600 and not same_replay(lst, by, seen)]
            if not fresh:                                    # all visible ones done: scroll down
                adb("input", "swipe", "540", "1800", "540", "1000", "700")
                time.sleep(1.5)
                swipes += 1
                continue
            by = fresh[0]
            thumb = deck_thumb(lst, by)
            seen.append(thumb)
            out = OUT / time.strftime("%Y%m%d-%H%M%S")
            out.mkdir(parents=True)
            np.save(out / "deck_thumb.npy", thumb)
            cv2.imwrite(str(out / "list.png"), lst[by - 470:by + 40, 40:1040])
            print(f"replay {done + 1}/{n}: watching...", flush=True)
            adb("input", "tap", str(WATCH_X), str(by))
            dur = record(dev, out, next_tpl)
            time.sleep(1.5)
            cv2.imwrite(str(out / "result.png"), dev.grab())           # winner + crowns
            nframes = len(list((out / "frames").glob("*.jpg")))
            (out / "meta.json").write_text(json.dumps({"seconds": round(dur, 1), "frames": nframes}, indent=1))
            print(f"  recorded {dur:.0f}s, {nframes} frames -> {out.name}", flush=True)
            adb("input", "tap", *map(str, OK_BUTTON))
            time.sleep(3)
            done += 1
    except KeyboardInterrupt:
        print("stopped")
    finally:
        dev.close()
    print(f"{done} replay(s) recorded in {OUT}")


if __name__ == "__main__":
    main()

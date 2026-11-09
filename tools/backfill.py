"""Repair watched matches recorded before the detector/tower fixes of 2026-11-09.

For runs/<id> in observe mode:
  - towers_fixed.jsonl: tower HP re-read from the saved frames with the current reader
    (ladder arena bars sit lower; the live reader missed them). outcomes.py prefers this file.
  - decisions_backfill.jsonl: the owner's plays re-detected from the full-speed log (hand + elixir per
    frame), placed with the pink cost drop in the saved frames, with the nearest logged state before.
Run: python -m tools.backfill runs/<id> [...]
"""
import json
import sys
from pathlib import Path

import cv2

from bot import vision
from bot.actions import snap
from bot.observer import HumanPlayDetector
from bot.state import State


def frames(run):
    return sorted((float(p.stem), p) for p in (run / "frames").glob("*.jpg"))


def load(p):
    return cv2.resize(cv2.imread(str(p)), (1080, 2400), interpolation=cv2.INTER_CUBIC)


def fix_towers(run, fr):
    mem = vision.TowerMemory()
    with open(run / "towers_fixed.jsonl", "w") as f:
        for t, p in fr:
            f.write(json.dumps({"t": t, "towers": mem.update(vision.tower_hp(load(p)), t)}) + "\n")


def backfill_plays(run, fr):
    rows = [json.loads(l) for l in open(run / "log.jsonl")]
    states = [json.loads(l) for l in open(run / "decisions.jsonl")]
    states = [(d["state"]["t"], d["state"]) for d in states]
    det = HumanPlayDetector()
    real = vision.cost_drops
    vision.cost_drops = lambda img: []          # card/elixir from the log; spots from frames below
    try:
        dummy = State(t=0, elixir=5, regen=0.36, enemy_elixir=5, hand=[None] * 4, enemy_hand=[], enemy_deck=[])
        for r in rows:
            det.update(r["t"], None, r["hand"], r["elixir"], dummy)
    finally:
        vision.cost_drops = real
    out, placed = [], 0
    for slot_card, t in det.confirmed:
        before = [s for ts, s in states if ts <= t]
        if not before:
            continue
        prev = [p for ft, p in fr if ft <= t]
        after = [p for ft, p in fr if t + 0.1 <= ft <= t + 1.6]
        old = vision.cost_drops(load(prev[-1])) if prev else []
        spot = None
        for p in after:
            fresh = [d for d in vision.cost_drops(load(p)) if all(abs(d[0] - o[0]) + abs(d[1] - o[1]) > 40 for o in old)]
            if fresh:
                spot = (fresh[0][0] + vision.DROP_OFFSET[0], fresh[0][1] + vision.DROP_OFFSET[1])
                break
        if not spot:
            continue
        placed += 1
        slot = before[-1]["hand"].index(slot_card) if slot_card in before[-1]["hand"] else 0
        act = snap(slot_card, slot, spot)
        out.append({"state": before[-1], "action": act.to_dict(), "policy": "human", "explored": False,
                    "backfill": True})
    with open(run / "decisions_backfill.jsonl", "w") as f:
        for d in out:
            f.write(json.dumps(d) + "\n")
    return len(det.confirmed), placed


def main():
    for arg in sys.argv[1:]:
        run = Path(arg)
        fr = frames(run)
        fix_towers(run, fr)
        found, placed = backfill_plays(run, fr)
        print(f"{run.name}: towers re-read from {len(fr)} frames; {found} plays found, {placed} placed")


if __name__ == "__main__":
    main()

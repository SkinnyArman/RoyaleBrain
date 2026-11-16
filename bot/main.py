"""Run the bot.

python -m bot.main [--dry-run] [--slow] [--seconds N] [--enemy-deck rocket,golem,...]

--dry-run  read the screen, track elixir, log, print decisions, but never tap
--slow     use adb screencap + input tap instead of the scrcpy stream (fallback)
Every run writes runs/<timestamp>/ (see bot/recorder.py).
"""
import argparse
import json
import traceback
import subprocess
import time
from pathlib import Path

from . import layout as L
from . import vision
from . import brain as brain_mod
from .brain import COST, GK_ABILITY_COST, Brain
from .economy import EnemyElixir
from .recorder import Recorder
from .opponent import Opponent
from .cards import CARDS
from .economy import UNKNOWN_COST
from .recognizer import Recognizer
from .actions import Action
from .observer import HumanPlayDetector, coverage
from .policy import Context, DecisionLog, RulePolicy
from .state import build_state
from . import tracker as tracker_mod
from .tracker import OwnDeploys, Tracker


SCENERY_LEARN_S = 1.5  # detections in the first seconds of a match are arena decorations
MOVED_PX = 30          # a real unit moves (or, if a building, loses HP) before we crop/name it
CROP_AFTER_S = 1.2     # crop new enemy units after the deploy stopwatch is gone
MATCH_OVER_S = 4.0
NO_MATCH_EXIT = 3      # exit code when no match was played (./play then skips retraining)
ROOT = Path(__file__).resolve().parent.parent     # no in-match screen for this long after a match = it's over


def make_policy(args, brain):
    """--model <checkpoint>: the trained model plays (bot/live_model.py, R2). Otherwise the rule
    brain, the live baseline. The old outcome-scorer blend was removed 2026-11-10."""
    if args.model:
        from .live_model import ModelPolicy
        return ModelPolicy(args.model, brain.opponent, gate=args.gate, search=args.search or args.search_timing,
                           search_timing=args.search_timing)
    return RulePolicy(brain)


def phone_serial():
    """First physical device in `adb devices` (emulators, e.g. from other projects, are skipped)."""
    out = subprocess.run(["adb", "devices"], capture_output=True, text=True, check=True).stdout
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) == 2 and parts[1] == "device" and not parts[0].startswith("emulator-"):
            return parts[0]
    raise SystemExit("no physical phone in `adb devices` (plug it in, allow USB debugging)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--slow", action="store_true")
    ap.add_argument("--wait", type=float, default=900, help="max seconds to wait for a match to start")
    ap.add_argument("--verbose", action="store_true", help="print every frame, not just plays")
    ap.add_argument("--tower-hp", type=int, help="princess tower max HP for this match (read it off the screen)")
    ap.add_argument("--enemy-deck", default="", help="comma-separated enemy cards we already know")
    ap.add_argument("--observe", action="store_true",
                    help="watch the owner play: never tap, log their plays as training data")
    ap.add_argument("--frames", help="replay a recorded run's frames offline instead of the phone")
    ap.add_argument("--serial", help="adb serial; default: the first physical (non-emulator) device")
    ap.add_argument("--model", help="play with a trained model checkpoint (e.g. models/r3.pt) instead of the rule brain")
    ap.add_argument("--search", action="store_true",
                    help="--model: rebuild the board in RoyaleSim and let search pick the play (bot/rebuild.py)")
    ap.add_argument("--search-timing", action="store_true",
                    help="--model: search also decides WHEN to play (WAIT is a candidate), implies --search")
    ap.add_argument("--gate", type=float, default=0.0, help="--model: play when the gate logit is above this")
    args = ap.parse_args()

    templates = vision.load_templates()
    if not templates:
        raise SystemExit("templates/ is empty: run `python -m tools.grab --cards` during a match first")

    if args.observe:
        args.dry_run = True
    if args.frames:
        from .framedevice import FrameDevice
        dev, args.dry_run, args.slow = FrameDevice(args.frames), True, True
    elif args.slow:
        serial = args.serial or phone_serial()
        from .device import Device
        dev = Device(serial=serial)
    else:
        serial = args.serial or phone_serial()
        print(f"device {serial}")
        from .fastdevice import FastDevice
        dev = FastDevice(serial=serial)

    if args.tower_hp:
        brain_mod.PRINCESS_MAX_HP = args.tower_hp
    opponent = Opponent([c.strip() for c in args.enemy_deck.split(",") if c.strip()])
    brain, enemy_elixir = Brain(opponent), EnemyElixir()
    rec = Recorder(subdir="replays" if args.frames else "")
    tracker, ally_tracker, own = Tracker(), Tracker(), OwnDeploys()
    static_enemy, static_ally = vision.StaticFilter(), vision.StaticFilter()
    hand_reader = vision.HandReader(templates)
    tower_memory = vision.TowerMemory()
    policy = make_policy(args, brain)
    watcher = HumanPlayDetector()          # observe: logs the owner's plays; else: shadow self-check
    shadow = open(rec.dir / "shadow.jsonl", "a") if not args.observe else None
    print(f"policy: {policy.name}")
    decisions = DecisionLog(rec.dir)
    recognizer = Recognizer()
    print(f"enemy recogniser: {len(recognizer.y)} labelled examples")
    champ_tpl = vision.load_champion_template()
    next_tpl = vision.load_next_template()
    print(f"logging to {rec.dir}")
    last_frame_id, spent = None, 0.0
    started = last_seen_match = None
    last_wait_print = 0.0
    plays_made, enemy_plays_seen, towers = [], 0, {}
    errors = 0
    deadline = time.monotonic() + args.wait
    print("waiting for a match... (start one on the phone)", flush=True)
    try:
        while True:
            img = dev.grab()
            if not args.slow:
                if dev.frames == last_frame_id:   # no new frame decoded yet
                    time.sleep(0.002)
                    continue
                last_frame_id = dev.frames
            wall0 = time.monotonic()
            t0 = dev.clock() if hasattr(dev, "clock") else time.monotonic()
            if not vision.in_match(img, next_tpl):     # loading, result screen, menus: do nothing
                if started is not None and t0 - last_seen_match > MATCH_OVER_S:
                    break                              # the match is over
                if started is None and t0 > deadline:
                    print("no match started; giving up", flush=True)
                    break
                if started is None and t0 - last_wait_print > 10:
                    print("waiting for a match...", flush=True)
                    last_wait_print = t0
                continue
            if started is None:
                started = t0
                print("match started: playing", flush=True)
            last_seen_match = t0

            try:
                elixir = vision.elixir(img)
                hand = hand_reader.read(img)
                if None in hand:
                    rec.save_unknown_slots(t0, img, hand)
                hsv = vision.arena_hsv(img)
                raw_enemy, raw_ally = vision.enemies(img, hsv), vision.allies(img, hsv)
                if t0 - started <= SCENERY_LEARN_S:            # nothing is deployed yet: all scenery
                    static_enemy.learn_now(raw_enemy)
                    static_ally.learn_now(raw_ally)
                points = static_enemy.update(raw_enemy, t0)
                ally_points = static_ally.update(raw_ally, t0)
                towers = tower_memory.update(vision.tower_hp(img), t0)
                enemy_elixir.update(t0, elixir, we_spent=spent)
                plays = [g for g in tracker.update(points, t0) if not tracker_mod.is_spawn(g, tracker.tracks, t0)]
                enemy_plays_seen += len(plays)
                for g in plays:
                    enemy_elixir.enemy_played(t0, note=f"{len(g)} units at ({int(g[0].x)},{int(g[0].y)})")
                    opponent.played(None)
                    for t in g:
                        t.play_index = len(opponent.plays) - 1

                own.update(ally_tracker.update(ally_points, t0), t0)
                own.advance(t0, tracker.tracks, ally_tracker.tracks)
                tracker_mod.set_alive(towers)
                # crop only units that behave like units: moved, or (buildings) lost HP since they appeared
                ready = [t for t in tracker.tracks if not t.cropped and t0 - t.born >= CROP_AFTER_S
                         and (t.travelled >= MOVED_PX or t.hp < 0.97)]
                for t in ready:
                    if recognizer:
                        t.card, _ = recognizer.predict(vision.unit_crop(img, t.x, t.y))
                    if t.card and t.play_index is not None:
                        # was this their answer to one of our attacks (same lane, within 5s)?
                        for ours in ("hog", "ram"):
                            if ours in own.last:
                                ox, oy, ot = own.last[ours]
                                if t0 - ot <= 5.0 and (ox < L.MID_X) == (t.x < L.MID_X):
                                    opponent.note_response(ours, t.card)
                    if t.card and t.play_index is not None and opponent.identify(t.play_index, t.card):
                        # correct the elixir estimate: the play was counted at the average cost
                        enemy_elixir.value = max(0.0, enemy_elixir.value + UNKNOWN_COST
                                             - CARDS.get(t.card, {}).get("cost", UNKNOWN_COST))
                        print(f"  enemy played {t.card}", flush=True)
                if ready:
                    rec.save_enemy_units(t0, img, ready)
                    for t in ready:
                        t.cropped = True
                champ = vision.champion_ready(img, champ_tpl)

                state = build_state(t0 - started, elixir, enemy_elixir, hand, opponent, tracker,
                                    ally_tracker, towers, champ, own, t0)
                ctx = Context(tracks=tracker.tracks, allies=ally_tracker.tracks, new_plays=plays,
                              gk_estimate=own.estimate("golden_knight", t0), own_last=own.last,
                              supports=own.supports(t0), now=t0)
                if args.observe:
                    # owner's match: log their plays, never ours
                    for before, act, xy in watcher.update(t0, img, hand, elixir, state):
                        decisions.record(before, act, "human", t0)
                        own.played(act.card, xy, t0)
                        plays_made.append(act.card)
                        rec.save_play_snapshot(t0, img, act.card, xy)
                        print(f"{t0 - started:6.1f}s you played {act.card} at ({int(xy[0])},{int(xy[1])})", flush=True)
                    decisions.record(state, Action("wait"), "human", t0)
                    chosen = Action("wait")
                else:
                    # shadow: the detector watches our own plays, so its accuracy is measured every match
                    for _, act, xy in watcher.update(t0, img, hand, elixir, state):
                        shadow.write(json.dumps({"t": round(t0 - started, 2), "card": act.card,
                                                 "x": int(xy[0]), "y": int(xy[1])}) + "\n")
                    chosen, _, _ = policy.choose(state, ctx)
                    decisions.record(state, chosen, policy.name, t0, explored=getattr(policy, "last_explored", False))

                action, spent = None, 0.0
                if chosen.kind == "ability":
                    action = ("gk_ability", None, None)
                    if not args.dry_run:
                        dev.tap(*L.CHAMPION_ABILITY)
                    spent = GK_ABILITY_COST
                elif chosen.kind == "play":
                    xy = policy.last_exact or (chosen.x, chosen.y)    # rules keep their exact spot
                    action = (chosen.card, chosen.slot, xy)
                    if not args.dry_run:
                        dev.play(L.SLOTS[chosen.slot], xy)
                    hand_reader.played(chosen.slot)
                    own.played(chosen.card, xy, t0)
                    spent = COST[chosen.card]
                if action:
                    plays_made.append(action[0])

                ms = (time.monotonic() - wall0) * 1000
                rec.write(t0, img, {
                    "ms": round(ms, 1), "elixir": elixir, "enemy_elixir": round(enemy_elixir.value, 2),
                    "regen": round(enemy_elixir.rate, 3), "hand": hand,
                    "tracks": [[t.id, int(t.x), int(t.y), int(t.w), int(t.vy), t.hp, t.card, t.level] for t in tracker.tracks],
                    "enemy_hand": opponent.hand_estimate(),
                    "allies": [[t.id, t.label, int(t.x), int(t.y), t.hp] for t in ally_tracker.tracks],
                    "towers": towers, "champion_ready": champ,
                    "enemy_plays": len(plays),
                    "action": [action[0], [int(v) for v in action[2]] if action[2] else None] if action else None,
                    "model": getattr(policy, "last_info", None) if action else None,
                }, force_frame=bool(action or plays))
                act = ""
                if action:
                    act = f"  -> {action[0]}" + (f" at {tuple(int(v) for v in action[2])}" if action[2] else "")
                    info = getattr(policy, "last_info", None)
                    if info and "search_ms" in info:
                        act += f"  [search {info['search_ms']}ms rebuild {info['rebuild_ms']}ms {info['units']} units]"
                if args.verbose or action:
                    clock = t0 - started
                    print(f"{clock:6.1f}s {ms:5.1f}ms elixir={elixir:4.1f} them~{enemy_elixir.value:4.1f} "
                          f"hand={hand} enemies={len(tracker.tracks)} champ={champ}{act}", flush=True)
            except Exception:                  # one bad frame must never end a match (run 042600)
                errors += 1
                with open(rec.dir / "errors.log", "a") as f:
                    f.write(f"t={t0 - started:.2f}\n{traceback.format_exc()}\n")
                if errors in (1, 10, 100):
                    print(f"  (frame error #{errors}, logged to errors.log; continuing)", flush=True)
    except KeyboardInterrupt:
        print("stopped")
    finally:
        if shadow:
            shadow.close()
        decisions.close()
        rec.close()
        dev.close()
    if started is None:
        raise SystemExit(NO_MATCH_EXIT)          # tells ./play not to retrain
    (rec.dir / "summary.json").write_text(json.dumps({
        "mode": "observe" if args.observe else policy.name, "seconds": round(last_seen_match - started, 1),
        "plays": plays_made, "enemy_plays": enemy_plays_seen, "towers": towers,
        "enemy_deck_seen": sorted(opponent.deck),
        "detection_coverage": round(coverage(watcher), 2) if args.observe else None,
    }, indent=1))
    if started is not None:
        print(f"\nmatch over after {last_seen_match - started:.0f}s: we played {len(plays_made)} cards "
              f"({', '.join(plays_made) or 'none'}), saw {enemy_plays_seen} enemy plays")
        print(f"last tower readings: {towers}")
        if args.observe:
            print(f"play detection self-check: detected plays explain {coverage(watcher):.0%} of the "
                  f"elixir you spent ({watcher.spent_detected:.0f} of {watcher.spent_seen:.0f})")
        print(f"log: {rec.dir}")


if __name__ == "__main__":
    main()

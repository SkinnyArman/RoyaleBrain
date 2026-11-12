"""IL_Replay shards -> training samples, by re-playing every pro match in RoyaleSim.

    .venv/bin/python -m tools.build_dataset --shards 0:4            # first 4 shards (20k replays)
    .venv/bin/python -m tools.build_dataset --shards 0:1 --limit 50 # quick check

For every replay: both decks are loaded at their real levels and evo/hero forms, and every recorded
play is injected at its real tick and tile (a card waits up to 3s for hand/elixir, like the
parity check). At each play we record a sample from the ACTING player's point of view; between
plays we also record "wait" samples, so the model learns when not to play.

One sample = what that player could see at that moment, plus the label:
  board       own frame: the actor's king at the bottom (side 1 is rotated 180 degrees)
  units       up to K_UNITS non-tower bodies: card id + [own, x, y, hp_frac, max_hp, radius,
              flying, deploying]; nearest to the actor's king first
  scalars     time, own elixir, enemy elixir (public count of their plays), 6 tower HP fractions,
              crowns, overtime
  cards       own hand (4) + next card, own deck (8), enemy cards seen so far (up to 8)
  label       played card (index in hand, or -1 = wait) and tile (x, y) in own frame
  outcome     the actor's REAL result in that match (+1 win / 0 draw / -1 loss) and real crowns

What is NOT perfectly "phone-visible" yet: enemy card ids are true ids (the trainer masks a share of
them to "unknown", like live recognition); enemy elixir is the exact public count (live: estimate).

Caveat (docs/experiments.md #21): an open-loop replay drifts from the real match, so late samples
can show a board the player never saw. Each sample stores `drift` = plays rejected so far in that
replay, and the replay's own acceptance rate, so training can filter or down-weight.

Output: datasets/samples/shard-XXXXXX-NN.npz, one file per 1,000 replays (git-ignored, resumable).
"""
import argparse
import json
import math
import random
import re
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import royalesim

from bot.sim import H_TILES, TICKS_PER_S, TILE, W_TILES, Sim

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "datasets" / "il_replay"
OUT = ROOT / "datasets" / "samples"
K_UNITS = 48
UNIT_F = 8
N_SCALARS = 12
WAIT_EVERY_S = 3.0          # one wait sample per side per 3s of no play
HOLD_TICKS = 60             # a play may wait this long for its card / elixir
REGEN_MILLI_PER_TICK = (1000 / 2.8) / TICKS_PER_S   # single elixir (x2 in the last minute; overtime ignored)

_norm = lambda s: re.sub(r"[^a-z]", "", s.lower())
ALIAS = {"thelog": "log", "archers": "archer", "dartgoblin": "blowdartgoblin", "magicarcher": "elitearcher",
         "bandit": "assassin", "royalghost": "ghost", "icegolem": "icegolemite", "giantsnowball": "snowball",
         "barbarianbarrel": "barblog", "elitebarbarians": "angrybarbarians", "executioner": "axeman",
         "guards": "skeletonwarriors", "sparky": "zapmachine", "skeletonbarrel": "skeletonballoon",
         "zappies": "minisparkys", "furnace": "firespirithut", "void": "darkmagic", "cannoncart": "movingcannon",
         "nightwitch": "darkwitch", "motherwitch": "witchmother", "firespirit": "firespirits",
         "icespirit": "icespirits", "lumberjack": "ragebarbarian", "runegiant": "giantbuffer",
         "healspirit": "heal", "spiritempress": "mergemaiden", "flyingmachine": "dartbarrell"}


class Mapper:
    def __init__(self, sim):
        self.ids = {_norm(row[0]): i for i, row in enumerate(sim.catalogue)}

    def __call__(self, key):
        form = 1 if key.endswith("-ev1") else 2 if key.endswith("-hero") else 0
        base = _norm(re.sub(r"-(ev1|hero)$", "", key))
        base = ALIAS.get(base, base)
        for cand in (base, base + "s", base.rstrip("s")):
            if cand in self.ids:
                return self.ids[cand], form
        return None, form


def own_frame(x, y, side):
    """Engine tiles -> the actor's frame (own king at the bottom = low y)."""
    return (x, y) if side == 0 else (W_TILES - x, H_TILES - y)


def observe(sim, st, side, seen, enemy_spent, F):
    """One sample's inputs from `side`'s point of view."""
    me, them = st["players"][side], st["players"][1 - side]
    tick = st["tick"]
    king = own_frame(9.0, 3.0, 0)
    bodies = []
    for e in st["entities"]:
        if e[F["tower_slot"]] >= 0 or e[F["hp"]] <= 0:
            continue
        x, y = own_frame(e[F["x"]] / TILE, e[F["y"]] / TILE, side)
        mx = max(1, e[F["max_hp"]])
        bodies.append((math.dist((x, y), king), e[F["card_id"]],
                       [float(e[F["team"]] == side), x / W_TILES, y / H_TILES, e[F["hp"]] / mx,
                        math.log1p(mx) / 10, e[F["radius"]] / TILE, float(e[F["flying"]]),
                        float(e[F["deploy_ticks"]] > 0)]))
    bodies.sort(key=lambda b: b[0])
    unit_ids = np.full(K_UNITS, -1, np.int16)
    units = np.zeros((K_UNITS, UNIT_F), np.float16)
    for i, (_, cid, f) in enumerate(bodies[:K_UNITS]):
        unit_ids[i], units[i] = cid, f
    towers = []
    for team in (side, 1 - side):
        hp, mx = st["players"][team]["tower_hp"], st["players"][team]["tower_max_hp"]
        towers += [h / max(1, m) for h, m in zip(hp, mx)]          # king, princess, princess
    double_from = 2 * 60 * TICKS_PER_S                               # x2 elixir in the last minute
    regen = REGEN_MILLI_PER_TICK * (min(tick, double_from) + 2 * max(0, tick - double_from))
    enemy_elixir = max(0.0, min(10.0, (5000 + regen - enemy_spent) / 1000))  # public count, approx.
    scalars = np.array([tick / (3 * 60 * TICKS_PER_S), me["elixir_milli"] / 10000, enemy_elixir / 10,
                        *towers, me["crowns"] / 3, them["crowns"] / 3, float(st["overtime"])],
                       np.float16)[:N_SCALARS]
    hand = np.array([c if c is not None else -1 for c in me["hand"]] + [me["next_card"] if me["next_card"] is not None else -1],
                    np.int16)
    enemy_seen = np.full(8, -1, np.int16)
    for i, c in enumerate(list(seen)[:8]):
        enemy_seen[i] = c
    return unit_ids, units, scalars, hand, enemy_seen


def build_replay(sim, mapper, payload, F):
    bt = payload["battle"]
    sides = ("team", "opponent")
    decks, forms, levels = [], [], []
    for s in sides:
        pl = bt[s]["players"][0]
        order = [re.sub(r"-(ev1|hero)$", "", e["card_key"]) for e in payload["events"]
                 if e["side"] == s and e["kind"] == "play_card"]
        first = list(dict.fromkeys(order))
        entries = sorted(pl["deck"], key=lambda d: first.index(re.sub(r"-(ev1|hero)$", "", d["card_key"]))
                         if re.sub(r"-(ev1|hero)$", "", d["card_key"]) in first else 99)
        d, f, lv = [], [], []
        for e in entries:
            cid, form = mapper(e["card_key"])
            if cid is None:
                return None, "unknown_card"
            d.append(cid); f.append(form); lv.append(e["level"])
        decks.append(d); forms.append(f); levels.append(lv)
    tl = [bt[s]["players"][0]["tower_card"]["level"] for s in sides]
    try:
        sim.b.reset(seed=0, decks=decks, shuffle=0, start_tick=0, elixir_milli=[5000, 5000], tower_hp=None,
                    spawns=[], forms=forms, levels=levels, tower_levels=tl)
    except Exception:
        return None, "reset_error"
    real = (bt["team"]["crowns"], bt["opponent"]["crowns"])
    result = [(real[0] > real[1]) - (real[0] < real[1]), (real[1] > real[0]) - (real[1] < real[0])]
    events = sorted([e for e in payload["events"] if e["kind"] == "play_card"], key=lambda e: e["replay_tick_20hz"])
    rows, pending, i = [], [], 0
    seen = [set(), set()]                # cards each side has seen the OTHER side play
    spent = [0, 0]                       # elixir (milli) each side has publicly spent
    last_play = [0, 0]
    rejected = accepted = 0
    while True:
        st = sim.state()
        if st["game_over"] or st["tick"] > 9000:
            break
        tick = st["tick"]
        while i < len(events) and events[i]["replay_tick_20hz"] <= tick:
            pending.append([events[i], tick]); i += 1
        cmds, keep = [], []
        for ev, t0 in pending:
            side = 0 if ev["side"] == "team" else 1
            cid, _ = mapper(ev["card_key"])
            hand = st["players"][side]["hand"]
            if cid in hand:
                c = ev["coordinates"]["native_world_units"]
                cmds.append((side, hand.index(cid), c["x"] * 18, c["y"] * 18, ev, t0, cid))
            elif tick - t0 < HOLD_TICKS:
                keep.append([ev, t0])
            else:
                rejected += 1
        # wait samples: a side that hasn't played for WAIT_EVERY_S and isn't about to
        for side in (0, 1):
            if tick - last_play[side] >= WAIT_EVERY_S * TICKS_PER_S and not any(c[0] == side for c in cmds) \
                    and not any((0 if e["side"] == "team" else 1) == side for e, _ in keep):
                rows.append((*observe(sim, st, side, seen[side], spent[1 - side], F), -1, -1.0, -1.0,
                             result[side], real[side], real[1 - side], side, tick, rejected))
                last_play[side] = tick
        for side, slot, x, y, ev, t0, cid in cmds:
            obs = observe(sim, st, side, seen[side], spent[1 - side], F)
            lx, ly = own_frame(x / TILE, y / TILE, side)
            rows.append((*obs, slot, lx / W_TILES, ly / H_TILES, result[side], real[side], real[1 - side],
                         side, tick, rejected))
        if cmds:
            res = sim.b.step([c[:4] for c in cmds], 1)
            for c, r in zip(cmds, res):
                if royalesim.DEPLOY_REASONS[r[1]] == "OK":
                    accepted += 1
                    seen[1 - c[0]].add(c[6])
                    spent[c[0]] += 1000 * sim.cost[c[6]]
                    last_play[c[0]] = tick
                else:
                    rejected += 1
        else:
            nxt = events[i]["replay_tick_20hz"] - tick if i < len(events) else 20
            sim.b.step([], int(max(1, min(20, nxt))))
        pending = keep
    return (rows, accepted, rejected), None


CHUNK = 1000                 # replays per output file: bounds each worker's memory (~9 GB RAM machine)
COLS = ("unit_ids", "units", "scalars", "hand", "enemy_seen", "label_slot", "label_x", "label_y", "result",
        "crowns_own", "crowns_opp", "side", "tick", "drift", "replay")


def build_shard(args):
    path, limit = args
    sim = Sim()
    mapper, F = Mapper(sim), {f: i for i, f in enumerate(royalesim.ENTITY_FIELDS)}
    table = pq.read_table(path, columns=["payload_json"])
    n = table.num_rows if limit is None else min(limit, table.num_rows)
    stem = Path(path).stem.split("-")[-1]
    skipped, acc_rates, total = {}, [], 0
    for c0 in range(0, n, CHUNK):
        dest = OUT / f"shard-{stem}-{c0 // CHUNK:02d}.npz"
        if dest.exists() and limit is None:          # resumable: finished chunks are kept
            total += len(np.load(dest)["side"])
            continue
        cols = {k: [] for k in COLS}
        for r in range(c0, min(n, c0 + CHUNK)):
            payload = json.loads(table.slice(r, 1).column(0)[0].as_py())
            out, why = build_replay(sim, mapper, payload, F)
            if out is None:
                skipped[why] = skipped.get(why, 0) + 1
                continue
            rows, acc, rej = out
            acc_rates.append(acc / max(1, acc + rej))
            for row in rows:
                for k, v in zip(COLS[:-1], row):
                    cols[k].append(v)
                cols["replay"].append(int(stem) * 10_000 + r)     # global replay id (shard * 10k + row)
        tmp = dest.with_suffix(".tmp.npz")
        np.savez_compressed(tmp, **{k: np.array(v) for k, v in cols.items()})
        tmp.rename(dest)                               # never leave a half-written chunk behind
        total += len(cols["side"])
    return Path(path).name, n, total, skipped, float(np.mean(acc_rates)) if acc_rates else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shards", default="0:1", help="range of shard indices, e.g. 0:4")
    ap.add_argument("--limit", type=int, default=None, help="replays per shard (testing)")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    lo, hi = (int(v) for v in a.shards.split(":"))
    files = sorted(SRC.glob("part-*.parquet"))[lo:hi]
    if not files:
        raise SystemExit(f"no shards in {SRC} for {a.shards}: run tools.fetch_replays first")
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with Pool(min(a.workers, len(files))) as pool:
        for name, n, rows, skipped, acc in pool.imap_unordered(build_shard, [(f, a.limit) for f in files]):
            print(f"{name}: {n} replays -> {rows} samples, plays accepted {acc:.1%}, skipped {skipped}", flush=True)
    print(f"done in {time.time() - t0:.0f}s -> {OUT}")


if __name__ == "__main__":
    main()

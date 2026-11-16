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
              crowns, overtime, own ability buttons (ready, cost...: ability_features)
  cards       own hand (4) + next card, own deck (8), enemy cards seen so far (up to 8)
  label       played card (index in hand 0-3, 4 = ability button, -1 = wait) and tile (x, y) in own
              frame (-1 for waits and ability presses)
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
import re
import signal
import sys
import time
from multiprocessing import Pool, Value
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
N_SCALARS = 21              # 12 game scalars + 9 ability scalars (see ability_features)
ABILITY_SLOT = 4            # label_slot 4 = "press the ability button" (0-3 = hand cards, -1 = wait)
MAX_ABILITIES = 2
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


class ElixirCount:
    """One side's elixir as the OTHER side can count it: 5 at the start, public regen (x2 from 2:00;
    overtime ignored), minus the cost of every play seen, CAPPED AT 10 AT EVERY MOMENT (elixir over 10
    is lost). The old count (5 + all regen - all spent, capped once at the end) said 10 for a player
    who waited a minute at full and then played a 4 (truth: 6) (AGENTS.md, 2026-11-15)."""
    DOUBLE_FROM = 2 * 60 * TICKS_PER_S

    def __init__(self):
        self.milli, self.tick = 5000.0, 0

    def _regen(self, t0, t1):
        d = self.DOUBLE_FROM
        return REGEN_MILLI_PER_TICK * (max(0, min(t1, d) - min(t0, d)) + 2 * max(0, max(t1, d) - max(t0, d)))

    def value(self, tick):
        """Elixir (milli) at `tick` (>= the last play). Regen only adds between plays, so capping
        at the end of each stretch is the same as capping continuously."""
        return min(10000.0, self.milli + self._regen(self.tick, tick))

    def spend(self, tick, milli):
        self.milli, self.tick = max(0.0, self.value(tick) - milli), tick


def own_frame(x, y, side):
    """Engine tiles -> the actor's frame (own king at the bottom = low y)."""
    return (x, y) if side == 0 else (W_TILES - x, H_TILES - y)


def ability_features(me):
    """Own champion / hero ability buttons: [ready, field1/10, cost/10, field4/100] for up to 2,
    plus how many buttons exist. RoyaleSim's per-button record is [ready, ?, cost, card id, ?];
    'ready' goes 1 when the unit is on the field and the ability can be pressed (2026-11-12)."""
    out = []
    abilities = me.get("abilities") or []
    for k in range(MAX_ABILITIES):
        a = abilities[k] if k < len(abilities) else [0, 0, 0, -1, 0]
        out += [float(a[0] > 0), a[1] / 10, a[2] / 10, a[4] / 100]
    return out + [len(abilities) / 3]


def observe(sim, st, side, seen, enemy_count, F):
    """One sample's inputs from `side`'s point of view. enemy_count: the enemy's ElixirCount."""
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
    enemy_elixir = enemy_count.value(tick) / 1000                    # public count (ElixirCount)
    scalars = np.array([tick / (3 * 60 * TICKS_PER_S), me["elixir_milli"] / 10000, enemy_elixir / 10,
                        *towers, me["crowns"] / 3, them["crowns"] / 3, float(st["overtime"]),
                        *ability_features(me)],
                       np.float16)[:N_SCALARS]
    hand = np.array([c if c is not None else -1 for c in me["hand"]] + [me["next_card"] if me["next_card"] is not None else -1],
                    np.int16)
    enemy_seen = np.full(8, -1, np.int16)
    for i, c in enumerate(list(seen)[:8]):
        enemy_seen[i] = c
    return unit_ids, units, scalars, hand, enemy_seen


def ability_button(mapper, player, ev):
    """Which ability button (0..2) this press is: a READY button, preferring the one whose card
    matches the event's candidate source card. None = nothing pressable right now."""
    abilities = player.get("abilities") or []
    want = {mapper(k)[0] for k in (ev.get("ability_source_candidates") or [])} - {None}
    ready = [k for k, a in enumerate(abilities) if a[0] > 0]
    match = [k for k in ready if abilities[k][3] in want]
    return (match or ready or [None])[0]


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
    # card plays AND ability presses (champions, heroes): 91% of pro replays press abilities; skipping
    # them left champions idle and elixir too high in the sim (2026-11-12)
    events = sorted([e for e in payload["events"] if e["kind"] in ("play_card", "activate_ability")],
                    key=lambda e: e["replay_tick_20hz"])
    rows, pending, i = [], [], 0
    seen = [set(), set()]                # cards each side has seen the OTHER side play
    counts = [ElixirCount(), ElixirCount()]   # each side's elixir as the other side can count it
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
            if ev["kind"] == "activate_ability":
                k = ability_button(mapper, st["players"][side], ev)
                if k is not None:
                    cost = st["players"][side]["abilities"][k][2]
                    cmds.append((side, ABILITY_SLOT + k, 0, 0, ev, t0, None, 1000 * cost))
                elif tick - t0 < HOLD_TICKS:
                    keep.append([ev, t0])
                else:
                    rejected += 1
                continue
            cid, _ = mapper(ev["card_key"])
            hand = st["players"][side]["hand"]
            if cid in hand:
                c = ev["coordinates"]["native_world_units"]
                cmds.append((side, hand.index(cid), c["x"] * 18, c["y"] * 18, ev, t0, cid, 1000 * sim.cost[cid]))
            elif tick - t0 < HOLD_TICKS:
                keep.append([ev, t0])
            else:
                rejected += 1
        # wait samples: a side that hasn't played for WAIT_EVERY_S and isn't about to
        for side in (0, 1):
            if tick - last_play[side] >= WAIT_EVERY_S * TICKS_PER_S and not any(c[0] == side for c in cmds) \
                    and not any((0 if e["side"] == "team" else 1) == side for e, _ in keep):
                rows.append((*observe(sim, st, side, seen[side], counts[1 - side], F), -1, -1.0, -1.0,
                             result[side], real[side], real[1 - side], side, tick, rejected))
                last_play[side] = tick
        for side, slot, x, y, ev, t0, cid, cost in cmds:
            obs = observe(sim, st, side, seen[side], counts[1 - side], F)
            if cid is None:                                     # ability press: no position
                rows.append((*obs, ABILITY_SLOT, -1.0, -1.0, result[side], real[side], real[1 - side],
                             side, tick, rejected))
                continue
            lx, ly = own_frame(x / TILE, y / TILE, side)
            rows.append((*obs, slot, lx / W_TILES, ly / H_TILES, result[side], real[side], real[1 - side],
                         side, tick, rejected))
        if cmds:
            res = sim.b.step([c[:4] for c in cmds], 1)
            for c, r in zip(cmds, res):
                if royalesim.DEPLOY_REASONS[r[1]] == "OK":
                    accepted += 1
                    if c[6] is not None:
                        seen[1 - c[0]].add(c[6])
                    counts[c[0]].spend(tick, c[7])
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
_done = None                 # shared counters for the progress bar: replays, samples, skipped, chunks


def _init(counters):
    global _done
    _done = counters
    signal.signal(signal.SIGINT, signal.SIG_IGN)       # Ctrl-C is handled once, by the main process


def _add(i, n):
    if _done is not None:
        with _done[i].get_lock():
            _done[i].value += n


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
            _add(0, 1)
            if out is None:
                skipped[why] = skipped.get(why, 0) + 1
                _add(2, 1)
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
        _add(1, len(cols["side"]))
        _add(3, 1)
    return Path(path).name, n, total, skipped, float(np.mean(acc_rates)) if acc_rates else 0.0


def main():
    signal.signal(signal.SIGINT, signal.default_int_handler)   # Ctrl-C works even if launched from a script
    ap = argparse.ArgumentParser()
    ap.add_argument("--shards", default="0:1", help="range of shard indices, e.g. 0:4")
    ap.add_argument("--limit", type=int, default=None, help="replays per shard (testing)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--status", action="store_true", help="only show how much is built, then exit")
    a = ap.parse_args()
    lo, hi = (int(v) for v in a.shards.split(":"))
    files = sorted(SRC.glob("part-*.parquet"))[lo:hi]
    if not files:
        raise SystemExit(f"no shards in {SRC} for {a.shards}: run tools.fetch_replays first")
    OUT.mkdir(parents=True, exist_ok=True)
    # how much is already built (finished chunks are skipped on resume)
    total = done = chunks_total = chunks_done = 0
    for f in files:
        n = pq.ParquetFile(f).metadata.num_rows if a.limit is None else min(a.limit, pq.ParquetFile(f).metadata.num_rows)
        stem = f.stem.split("-")[-1]
        for c0 in range(0, n, CHUNK):
            chunks_total += 1
            if a.limit is None and (OUT / f"shard-{stem}-{c0 // CHUNK:02d}.npz").exists():
                chunks_done += 1
                done += min(CHUNK, n - c0)
        total += n
    print(f"{len(files)} shards, {total:,} replays, {chunks_total} chunks; already built: "
          f"{chunks_done} chunks ({done:,} replays). Ctrl-C stops; finished chunks are kept.", flush=True)
    if a.status:
        size = sum(f.stat().st_size for f in OUT.glob("shard-*.npz")) / 1e9
        bar = "#" * int(30 * done / max(1, total))
        print(f"[{bar:<30}] {done / max(1, total):6.1%}  {done:,}/{total:,} replays  "
              f"{chunks_done}/{chunks_total} chunks  {size:.2f} GB on disk")
        return
    if chunks_done == chunks_total and a.limit is None:
        print("everything is already built, nothing to do. Next: ./train")
        return

    counters = [Value("q", 0) for _ in range(4)]       # replays, samples, skipped, chunks (this run)
    messages, results = [], []
    t0 = time.time()
    tty = sys.stdout.isatty()
    last_line = 0.0

    def draw(final=False):
        nonlocal last_line
        r, s, sk, ch = (c.value for c in counters)
        el = time.time() - t0
        rate = r / el if el > 0 else 0.0
        left = total - done - r
        eta = left / rate if rate > 0 else float("inf")
        frac = (done + r) / max(1, total)
        bar = "#" * int(frac * 30)
        line = (f"[{bar:<30}] {frac:6.1%}  {done + r:,}/{total:,} replays  chunks {chunks_done + ch}/{chunks_total}  "
                f"{s:,} samples  skipped {sk}  {rate:.1f} replays/s  elapsed {_hms(el)}  ETA {_hms(eta)}")
        if tty:
            print("\r\033[K" + line, end="\n" if final else "", flush=True)
        elif final or time.time() - last_line >= 30:   # piped to a file: one line every 30s
            print(line, flush=True)
            last_line = time.time()

    pool = Pool(min(a.workers, len(files)), initializer=_init, initargs=(counters,))
    try:
        for f in files:
            results.append(pool.apply_async(build_shard, ((f, a.limit),), callback=lambda res: messages.append(
                f"{res[0]}: {res[1]} replays -> {res[2]} samples, plays accepted {res[4]:.1%}, skipped {res[3]}")))
        pool.close()
        while not all(r.ready() for r in results):
            while messages:
                print(("\r\033[K" if tty else "") + messages.pop(0), flush=True)
            draw()
            time.sleep(0.5)
        for r in results:
            r.get()                                     # re-raise a worker's error here
        while messages:
            print(("\r\033[K" if tty else "") + messages.pop(0), flush=True)
        draw(final=True)
        pool.join()
    except KeyboardInterrupt:
        pool.terminate()
        pool.join()
        for tmp in OUT.glob("*.tmp.npz"):               # a chunk cut off mid-save
            tmp.unlink()
        draw(final=True)
        print("stopped: finished chunks are kept, run the same command again to resume")
        return
    print(f"done in {_hms(time.time() - t0)} -> {OUT}")


def _hms(s):
    if s == float("inf"):
        return "--:--:--"
    s = int(s)
    return f"{s // 3600:d}:{s % 3600 // 60:02d}:{s % 60:02d}"


if __name__ == "__main__":
    main()

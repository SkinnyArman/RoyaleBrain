"""SB: the simulator benchmark. Our deck, played by a PLAYER, against held-out real pro decks.

    ./bench rules                    # the rule brain (baseline) vs 200 held-out pro decks
    ./bench models/r3.pt             # the trained model, same 200 matches
    ./bench random                   # floor: random legal plays
    ./bench models/r3.pt --vs models/r3.pt     # opponents played by a model instead of replays
    ./bench models/r3.pt --matches 50 --video 3   # also render the first 3 matches to sims/

Levels: by default EVERY card and tower on both sides is level 14 (EQUAL_LEVEL), so the benchmark
measures how well a player plays, not whose cards are higher (owner, 2026-11-13). --real-levels
uses ours (bot/sim.OUR_LEVELS) vs the pro's real ones instead.

Every run plays the SAME matches (same opponent decks, levels, seeds, our deck order), so two players'
numbers compare directly, match by match. Results: runs/bench/<time>_<player>.json + a summary line.

Opponents (--vs):
  replay  (default) the pro's real moves from that held-out match, replayed at their time and spot
          (rotated to the red side). Fixed and reproducible, but blind: it does not react to us.
  random  random legal plays (sanity check)
  <.pt>   a model checkpoint plays the opponent's deck (reacts, but is only as good as that model)

Players see the board the way they would on the phone:
  model   the same observation as training (tools/build_dataset.observe): our units, enemy units with
          ids, hand, elixir, the PUBLIC enemy-elixir count, cards seen. It plays when the gate logit
          is above --gate (see GATE), its best card if affordable, at its best LEGAL tile (the engine's
          check_deploy masks illegal tiles).
  rules   bot/brain.Brain unchanged, fed from the sim instead of the screen: every unit as a track in
          screen pixels (PERFECT vision: all units seen, all enemy cards known, our troops visible),
          the same public enemy-elixir count, towers. Its pixel spot is mapped back to tiles.
"""
import argparse
import json
import math
import random
import signal
import subprocess
import sys
import time
from multiprocessing import Pool, Value
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import royalesim

from bot.sim import ENGINE_NAME, H_TILES, OUR_DECK, OUR_LEVELS, TICKS_PER_S, TILE, W_TILES, Sim
from tools.build_dataset import (ABILITY_SLOT, Mapper, ability_button, observe, own_frame, REGEN_MILLI_PER_TICK)

ROOT = Path(__file__).resolve().parent.parent
SRC, OUT = ROOT / "datasets" / "il_replay", ROOT / "runs" / "bench"
STEP = 5                       # ticks per loop (0.25 s); replay opponents act at this resolution
THINK = 10                     # model/rule players decide every 10 ticks (0.5 s), like the live bot
END_TICK = 5 * 60 * TICKS_PER_S + 100     # 3:00 + 2:00 overtime
OUR_TOWER_LEVEL = 14
EQUAL_LEVEL = 14                                     # default: both sides' cards and towers at this level
MIN_REAL_TICKS = 3 * 60 * TICKS_PER_S - 100          # benchmark matches: the real one lasted ~3:00+
# GATE: play when the gate logit is above this. Measured 2026-11-12 (r3 at 4k steps): at 0 the model
# plays ~24 cards in 2:36, the pros' rate (~26 per 3:00); at ln(15) = 2.7 (a prior correction for the
# 0.5 s decision rate vs the dataset's wait sampling) it never played. Tune with --gate.
GATE = 0.0
OK = royalesim.DEPLOY_REASONS.index("OK")


# ---------------------------------------------------------------- screen <-> tiles (rule brain only)
# Fitted to bot/layout.py anchors (towers, river) vs the engine's tower centres: x exact, y about
# +-50 px (1 tile), because layout's tower points are sprite centres, not footprints.
def to_px(tx, ty):
    return 16.4 + 58.2 * tx, 1739.8 - 46.95 * ty


def to_tile(px, py):
    return (px - 16.4) / 58.2, (1739.8 - py) / 46.95


class Match:
    """Shared, public per-match facts the players may use: cards each side has SEEN the other play,
    elixir each side has publicly spent (for the enemy-elixir count)."""
    def __init__(self):
        self.seen, self.spent = [set(), set()], [0, 0]

    def enemy_elixir(self, tick, side):
        double_from = 2 * 60 * TICKS_PER_S
        regen = REGEN_MILLI_PER_TICK * (min(tick, double_from) + 2 * max(0, tick - double_from))
        return max(0.0, min(10.0, (5000 + regen - self.spent[1 - side]) / 1000))


# ---------------------------------------------------------------- players
class RandomPlayer:
    name = "random"

    def __init__(self, rng):
        self.rng = rng

    def act(self, sim, st, side, match):
        if st["tick"] % THINK != (side * STEP) % THINK:
            return []
        pl = st["players"][side]
        if pl["elixir_milli"] < (6.5 + 3 * self.rng.random()) * 1000:
            return []
        slots = [i for i, c in enumerate(pl["hand"]) if c is not None and c >= 0
                 and sim.cost[c] * 1000 <= pl["elixir_milli"]]
        self.rng.shuffle(slots)
        for slot in slots:
            for _ in range(8):
                x, y = self.rng.uniform(0.5, 17.5), self.rng.uniform(0.5, 31.5)
                ex, ey = int(x * TILE), int(y * TILE)
                if sim.b.check_deploy(side, slot, ex, ey) == OK:
                    return [(side, slot, ex, ey)]
        return []


class ModelPlayer:
    def __init__(self, path, gate=GATE):
        import torch
        from bot.model import RoyaleBrain
        torch.set_num_threads(1)
        ck = torch.load(path, map_location="cpu", weights_only=False)
        self.model = RoyaleBrain(ck["card_table"], d=ck["args"]["d"], layers=ck["args"]["layers"])
        self.model.load_state_dict(ck["model"])
        self.model.eval()
        self.torch, self.gate, self.name = torch, gate, Path(path).stem
        self.F = {f: i for i, f in enumerate(royalesim.ENTITY_FIELDS)}

    def act(self, sim, st, side, match):
        if st["tick"] % THINK != (side * STEP) % THINK:
            return []
        torch, m = self.torch, self.model
        unit_ids, units, scalars, hand, seen = observe(sim, st, side, match.seen[side], match.spent[1 - side], self.F)
        t = lambda a, dt: torch.from_numpy(np.asarray(a).astype(dt))[None]
        ids, hd, sn = t(unit_ids, np.int64), t(hand, np.int64), t(seen, np.int64)
        for v in (ids, hd, sn):
            v[v < 0] = m.PAD
        with torch.no_grad():
            out = m(ids, t(units, np.float32), t(scalars, np.float32), hd, sn)
        if out["gate"].item() <= self.gate:
            return []
        slot = int(out["card"][0].argmax())
        pl = st["players"][side]
        if slot == ABILITY_SLOT:
            ready = [k for k, a in enumerate(pl.get("abilities") or []) if a[0] > 0 and a[2] * 1000 <= pl["elixir_milli"]]
            return [(side, ABILITY_SLOT + ready[0], 0, 0)] if ready else []
        card = pl["hand"][slot]
        if card is None or card < 0 or sim.cost[card] * 1000 > pl["elixir_milli"]:
            return []                                         # wants a card it can't afford yet: wait for it
        for cell in out["tile"][0].argsort(descending=True).tolist():   # best LEGAL tile
            x, y = own_frame((cell % W_TILES) + 0.5, (cell // W_TILES) + 0.5, side)
            ex, ey = int(x * TILE), int(y * TILE)
            if sim.b.check_deploy(side, slot, ex, ey) == OK:
                return [(side, slot, ex, ey)]
        return []


class ReplayPlayer:
    """Replays one side of a real match: each play at its tick (held up to 3 s for the card/elixir),
    at its spot rotated into `side`'s half. When the real match's moves run out (our match went
    longer), it plays randomly instead of standing idle."""
    HOLD = 60

    def __init__(self, payload, pro_side, mapper, rng):
        self.fallback = RandomPlayer(rng)
        self.events = sorted([e for e in payload["events"] if e["side"] == pro_side
                              and e["kind"] in ("play_card", "activate_ability")], key=lambda e: e["replay_tick_20hz"])
        self.flip = pro_side == "team"                        # the pro was blue in the replay, is red here
        self.mapper, self.i, self.pending, self.name = mapper, 0, [], "replay"

    def act(self, sim, st, side, match):
        tick, out, keep = st["tick"], [], []
        if self.i == len(self.events) and not self.pending:
            return self.fallback.act(sim, st, side, match)
        while self.i < len(self.events) and self.events[self.i]["replay_tick_20hz"] <= tick:
            self.pending.append((self.events[self.i], tick))
            self.i += 1
        pl = st["players"][side]
        for ev, t0 in self.pending:
            if ev["kind"] == "activate_ability":
                k = ability_button(self.mapper, pl, ev)
                if k is not None:
                    out.append((side, ABILITY_SLOT + k, 0, 0))
                elif tick - t0 < self.HOLD:
                    keep.append((ev, t0))
                continue
            cid, _ = self.mapper(ev["card_key"])
            c = ev["coordinates"]["native_world_units"]
            x, y = c["x"] * 18, c["y"] * 18
            if self.flip:
                x, y = W_TILES * TILE - x, H_TILES * TILE - y
            if cid in pl["hand"] and not any(o[1] == pl["hand"].index(cid) for o in out):
                out.append((side, pl["hand"].index(cid), x, y))
            elif tick - t0 < self.HOLD:
                keep.append((ev, t0))
        self.pending = keep
        return out[:1] + [o for o in out[1:] if o[1] >= ABILITY_SLOT]     # one card per step (+ ability)


class RulePlayer:
    """bot/brain.Brain on the sim (blue side only: the brain's screen has us at the bottom)."""
    name = "rules"

    def __init__(self, sim):
        from bot import tracker as trk
        from bot.brain import Brain
        from bot.opponent import Opponent
        self.trk, self.opp = trk, Opponent()
        self.brain = Brain(opponent=self.opp)
        self.own = trk.OwnDeploys()
        self.key = {sim.card_id(k)[0]: k for k in OUR_DECK}   # our card ids -> our keys
        self.enemy_key = {v: k for k, v in ENGINE_NAME.items() if not k.startswith(("evo_", "hero_"))}
        self.tracks, self.allies = {}, {}                     # sim uid -> tracker.Track
        self.F = {f: i for i, f in enumerate(royalesim.ENTITY_FIELDS)}

    def _sync(self, sim, st, side, now):
        F, new = self.F, {}
        live = {0: set(), 1: set()}
        for e in st["entities"]:
            if e[F["tower_slot"]] >= 0 or e[F["hp"]] <= 0:
                continue
            uid, team = e[F["uid"]], e[F["team"]]
            px, py = to_px(e[F["x"]] / TILE, e[F["y"]] / TILE)
            p = (px, py, max(40.0, 2 * 58.2 * e[F["radius"]] / TILE), e[F["hp"]] / max(1, e[F["max_hp"]]))
            store = self.allies if team == side else self.tracks
            live[team == side].add(uid)
            if uid in store:
                store[uid].update(p, now)
                continue
            t = self.trk.Track(p, now)
            name = sim.name(e[F["card_id"]])
            if team == side:
                t.label = self.key.get(e[F["card_id"]])
            else:
                t.card = self.enemy_key.get(name)
                new.setdefault(e[F["card_id"]], []).append(t)
            store[uid] = t
        for store, ids in ((self.tracks, live[False]), (self.allies, live[True])):
            for uid in [u for u in store if u not in ids]:
                del store[uid]
        return list(new.values())

    def act(self, sim, st, side, match):
        assert side == 0, "the rule brain plays blue (bottom of its screen)"
        tick = st["tick"]
        if tick % THINK != 0:
            return []
        now = tick / TICKS_PER_S
        plays = self._sync(sim, st, side, now)
        for g in plays:
            self.opp.played(g[0].card)
        enemies, allies = list(self.tracks.values()), list(self.allies.values())
        self.own.advance(now, enemies, allies)
        pl = st["players"][side]
        names = ("king", "left", "right")
        towers = {f"{who}_{names[k]}": hp / max(1, mx)
                  for who, team in (("our", side), ("enemy", 1 - side))
                  for k, (hp, mx) in enumerate(zip(st["players"][team]["tower_hp"], st["players"][team]["tower_max_hp"]))
                  if k > 0}
        self.trk.set_alive(towers)
        hand = [self.key.get(c) for c in pl["hand"]]
        ready = [k for k, a in enumerate(pl.get("abilities") or []) if a[0] > 0]
        act = self.brain.decide(pl["elixir_milli"] / 1000, hand, enemies, allies=allies, new_plays=plays,
                                enemy_elixir=match.enemy_elixir(tick, side), champion_ready=bool(ready),
                                towers=towers, gk_estimate=self.own.estimate("golden_knight", now),
                                own_last=self.own.last, supports=self.own.supports(now), now=now)
        if not act:
            return []
        card, slot, xy = act
        if card == "gk_ability":
            return [(side, ABILITY_SLOT + ready[0], 0, 0)] if ready else []
        self.own.played(card, xy, now)
        tx, ty = to_tile(*xy)
        return [(side, slot, int(tx * TILE), int(ty * TILE))]


def make_player(spec, seed, sim, gate=GATE):
    if spec == "random":
        return RandomPlayer(random.Random(seed))
    if spec == "rules":
        return RulePlayer(sim)
    return ModelPlayer(spec, gate)


# ---------------------------------------------------------------- one match
def play_match(job):
    """job: (index, payload_json, pro_side, player spec, opponent spec, gate, video path or None,
    real_levels)."""
    i, payload_json, pro_side, player_spec, vs_spec, gate, video, real_levels = job
    payload = json.loads(payload_json)
    sim, rng = Sim(), random.Random(i)
    mapper = Mapper(sim)
    pl = payload["battle"][pro_side]["players"][0]
    first = list(dict.fromkeys(e["card_key"].removesuffix("-ev1").removesuffix("-hero") for e in payload["events"]
                               if e["side"] == pro_side and e["kind"] == "play_card"))
    base = lambda k: k.removesuffix("-ev1").removesuffix("-hero")
    entries = sorted(pl["deck"], key=lambda d: first.index(base(d["card_key"])) if base(d["card_key"]) in first else 99)
    red = [mapper(e["card_key"]) for e in entries]
    our_keys = OUR_DECK[:]
    rng.shuffle(our_keys)                                     # our deck order varies per match (same for every player)
    blue = [sim.card_id(k) for k in our_keys]
    sim.b.reset(seed=i, decks=[[c for c, _ in blue], [c for c, _ in red]], shuffle=0, start_tick=0,
                elixir_milli=[5000, 5000], tower_hp=None, spawns=[],
                forms=[[f for _, f in blue], [f for _, f in red]],
                levels=[[OUR_LEVELS.get(k, 14) for k in our_keys], [e["level"] for e in entries]] if real_levels
                else [[EQUAL_LEVEL] * 8, [EQUAL_LEVEL] * 8],
                tower_levels=[OUR_TOWER_LEVEL, pl["tower_card"]["level"]] if real_levels else [EQUAL_LEVEL] * 2)
    ours = make_player(player_spec, i, sim, gate)
    if vs_spec == "replay":
        theirs = ReplayPlayer(payload, pro_side, mapper, random.Random(i + 10**6))
    else:
        theirs = make_player(vs_spec, i + 10**6, sim, gate)
    match = Match()
    plays, rejected = [0, 0], [0, 0]
    frames = None
    if video:
        from tools import sim_watch
        frames = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
                                   "-s", "468x902", "-r", "20", "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                                   str(video)], stdin=subprocess.PIPE)
        log = []
    st = sim.state()
    while not st["game_over"] and st["tick"] < END_TICK:
        cmds = ours.act(sim, st, 0, match) + theirs.act(sim, st, 1, match)
        hand = [p["hand"] for p in st["players"]]
        res = sim.b.step(cmds, 1) if cmds else []
        for c, r in zip(cmds, res):
            side, slot = c[0], c[1]
            if r[1] != OK:
                rejected[side] += 1
                continue
            plays[side] += 1
            if slot < ABILITY_SLOT:
                cid = hand[side][slot]
                match.seen[1 - side].add(cid)
                match.spent[side] += 1000 * sim.cost[cid]
                if frames:
                    log.append(f"{'blue' if side == 0 else 'red'}: {sim.name(cid)}")
            else:
                match.spent[side] += 1000                     # ability presses cost ~1 elixir (GK); public estimate
        n = STEP - (1 if cmds else 0)
        if frames:
            for _ in range(n):
                sim.step(1)
                frames.stdin.write(sim_watch.draw(sim, sim.state(), log).tobytes())
        elif n:
            sim.step(n)
        st = sim.state()
    if frames:
        frames.stdin.close()
        frames.wait()
    P = st["players"]
    lost = lambda team: sum(1 - h / max(1, m) for h, m in zip(P[team]["tower_hp"], P[team]["tower_max_hp"])) / 3
    return dict(i=i, deck=[sim.name(c) for c, _ in red], winner=st["winner"], crowns=[P[0]["crowns"], P[1]["crowns"]],
                dmg_dealt=round(lost(1), 4), dmg_taken=round(lost(0), 4), plays=plays, rejected=rejected,
                seconds=st["tick"] / TICKS_PER_S)


# ---------------------------------------------------------------- the benchmark set
def held_out(n):
    """The first n held-out matches (replay id % 50 == 0, never trained on) whose cards all load and
    that lasted 3 minutes or more (so a replayed opponent has moves for the whole regular time; a
    real 3-crown at 1:40 would leave it idle after that), alternating which side's deck we face.
    Same list every run."""
    sim = Sim()
    mapper = Mapper(sim)
    out = []
    for f in sorted(SRC.glob("part-*.parquet")):
        # batches of 50 rows: row 0 of each is a held-out one (shard * 10000 + r, r % 50 == 0).
        # Never the whole shard at once: its payload column is hundreds of MB (it pushed training into swap).
        for batch in pq.ParquetFile(f).iter_batches(batch_size=50, columns=["payload_json"]):
            payload_json = batch.column(0)[0].as_py()
            payload = json.loads(payload_json)
            pro_side = ("team", "opponent")[len(out) % 2]
            if max((e["replay_tick_20hz"] for e in payload["events"]), default=0) < MIN_REAL_TICKS:
                continue
            pl = payload["battle"][pro_side]["players"][0]
            if any(mapper(d["card_key"])[0] is None for d in pl["deck"]):
                continue
            if (pl.get("tower_card") or {}).get("level", 0) < 1 or any(d.get("level", 0) < 1 for d in pl["deck"]):
                continue                                      # level missing in the replay (engine refuses 0)
            out.append((payload_json, pro_side))
            if len(out) == n:
                return out
    return out


def _init(counter):
    global _counter
    _counter = counter
    signal.signal(signal.SIGINT, signal.SIG_IGN)


def _run(job):
    r = play_match(job)
    with _counter.get_lock():
        _counter.value += 1
    return r


def wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    c = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    mid = (p + z * z / (2 * n)) / (1 + z * z / n)
    return mid - c, mid + c


def main():
    signal.signal(signal.SIGINT, signal.default_int_handler)
    ap = argparse.ArgumentParser()
    ap.add_argument("player", help="rules | random | path to a model checkpoint (.pt)")
    ap.add_argument("--vs", default="replay", help="replay (default) | random | path to a model checkpoint")
    ap.add_argument("--matches", type=int, default=200)
    ap.add_argument("--workers", type=int, default=2, help="parallel matches (8 GB Mac: keep low while training)")
    ap.add_argument("--gate", type=float, default=GATE, help="model players: play when the gate logit is above this")
    ap.add_argument("--video", type=int, default=0, help="also render the first N matches to sims/")
    ap.add_argument("--real-levels", action="store_true", help=f"our real levels vs the pro's (default: all at {EQUAL_LEVEL})")
    a = ap.parse_args()
    for spec in (a.player, a.vs):
        if spec not in ("rules", "random", "replay") and not Path(spec).exists():
            raise SystemExit(f"{spec}: no such checkpoint")
    if a.vs == "rules":
        raise SystemExit("the rule brain only plays our deck: use it as the player, not --vs")
    print(f"loading {a.matches} held-out matches...", flush=True)
    games = held_out(a.matches)
    stamp, label = time.strftime("%Y%m%d-%H%M%S"), Path(a.player).stem + ("_real" if a.real_levels else "")
    jobs = []
    for i, (pj, side) in enumerate(games):
        video = ROOT / "sims" / f"bench_{stamp}_{label}_{i}.mp4" if i < a.video else None
        if video:
            video.parent.mkdir(exist_ok=True)
        jobs.append((i, pj, side, a.player, a.vs, a.gate, video, a.real_levels))
    counter, results, t0 = Value("q", 0), [], time.time()
    tty = sys.stdout.isatty()
    pool = Pool(a.workers, initializer=_init, initargs=(counter,))
    try:
        pending = [pool.apply_async(_run, (j,), callback=results.append) for j in jobs]
        pool.close()
        last = 0.0
        while not all(p.ready() for p in pending):
            time.sleep(0.5)
            done = counter.value
            wins = sum(r["winner"] == 0 for r in results)
            el = time.time() - t0
            eta = (len(jobs) - done) * el / done if done else float("inf")
            line = (f"[{'#' * int(30 * done / len(jobs)):<30}] {done}/{len(jobs)} matches  "
                    f"won {wins}/{len(results)}  elapsed {_hms(el)}  ETA {_hms(eta)}")
            if tty:
                print("\r\033[K" + line, end="", flush=True)
            elif time.time() - last > 30:
                print(line, flush=True)
                last = time.time()
        for p in pending:
            p.get()
    except KeyboardInterrupt:
        pool.terminate()
        print("\nstopped: nothing saved (a benchmark is only comparable when complete)")
        return
    pool.join()
    if tty:
        print()
    results.sort(key=lambda r: r["i"])
    n = len(results)
    w = sum(r["winner"] == 0 for r in results)
    d = sum(r["winner"] not in (0, 1) for r in results)
    lo, hi = wilson(w, n)
    mean = lambda k: sum(r[k] for r in results) / max(1, n)
    summary = dict(player=a.player, vs=a.vs, matches=n, wins=w, draws=d, losses=n - w - d,
                   win_rate=round(w / max(1, n), 4), win_ci95=[round(lo, 3), round(hi, 3)],
                   crowns_for=round(sum(r["crowns"][0] for r in results) / max(1, n), 3),
                   crowns_against=round(sum(r["crowns"][1] for r in results) / max(1, n), 3),
                   tower_dmg_dealt=round(mean("dmg_dealt"), 4), tower_dmg_taken=round(mean("dmg_taken"), 4),
                   plays=round(sum(r["plays"][0] for r in results) / max(1, n), 1),
                   rejected=round(sum(r["rejected"][0] for r in results) / max(1, n), 1),
                   gate=a.gate, levels="real" if a.real_levels else f"all {EQUAL_LEVEL}", minutes=round((time.time() - t0) / 60, 1))
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{stamp}_{label}_vs_{Path(a.vs).stem}.json"
    path.write_text(json.dumps(dict(summary=summary, matches=results), indent=1))
    print(f"{label} vs {Path(a.vs).stem}: won {w}/{n} = {w / max(1, n):.1%} (95% range {lo:.0%}-{hi:.0%}), "
          f"draws {d}  crowns {summary['crowns_for']:.2f}-{summary['crowns_against']:.2f}  "
          f"tower damage dealt {summary['tower_dmg_dealt']:.0%} taken {summary['tower_dmg_taken']:.0%}  "
          f"plays/match {summary['plays']}  rejected {summary['rejected']}")
    print(f"saved {path.relative_to(ROOT)}")


def _hms(s):
    if s == float("inf"):
        return "?"
    s = int(s)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}"


if __name__ == "__main__":
    main()

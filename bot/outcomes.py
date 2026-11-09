"""Outcome labels: what happened after each logged decision.

reward = (enemy tower HP lost - our tower HP lost over the next HORIZON_S seconds) / 1000
         - ELIXIR_VALUE_HP / 1000 * elixir the move cost

Tower HP comes from log.jsonl (every frame), so labels need no extra input. ELIXIR_VALUE_HP is a
prior (1 elixir ~ 80 tower HP, unverified): a move that costs elixir must earn more than waiting.
King tower damage isn't read yet, so a lost princess tower is the worst outcome we see.
"""
import json
from pathlib import Path

HORIZON_S = 10.0
ENEMY_TOWER_HP = 4032      # practice vs Devil (level 14); per-run values can be added to a meta file
OUR_TOWER_HP = 3668        # our level-13 towers
ELIXIR_VALUE_HP = 80.0
COST = {"hog": 4, "ram": 4, "golden_knight": 4, "witch": 5, "tombstone": 3, "minions": 3,
        "poison": 4, "log": 2, "gk_ability": 1}


def load_rows(path):
    return [json.loads(line) for line in open(path)]


def tower_series(log_rows):
    """[(t, towers dict)] with unknown readings filled from the previous value."""
    out, last = [], {}
    for r in log_rows:
        cur = dict(last)
        for k, v in (r.get("towers") or {}).items():
            if v is not None:
                cur[k] = v
        last = cur
        out.append((r["t"], cur))
    return out


def _at(series, t):
    """Towers at time t (first reading at or after t, else the last one)."""
    for ts, tw in series:
        if ts >= t:
            return tw
    return series[-1][1] if series else {}


KILL_VALUE_HP = 120.0   # 1 elixir of enemy troops destroyed ~ 120 tower HP (prior)


def deaths_fn(log_rows):
    """killed(t0, t1): elixir value of enemy units that died on OUR half between t0 and t1.

    A track that disappears while on our side of the river was killed by our defence (towers count
    too: they're part of defending). Owner: "a good play is sometimes only defending / neutralising"."""
    from .profiles import unit_value
    last = {}
    for r in log_rows:
        for tr in r.get("tracks", []):
            last[tr[0]] = (r["t"], tr[2], tr[6] if len(tr) > 6 else None)
    end = log_rows[-1]["t"] if log_rows else 0.0
    deaths = [(t, unit_value(card) if card else 1.0) for t, y, card in last.values()
              if y > 1080 and t < end - 1.0]

    def killed(t0, t1):
        return sum(v for t, v in deaths if t0 <= t <= t1)
    return killed


def label(decision, series, horizon=HORIZON_S, leak=None, killed=None):
    """Tower HP dealt - taken over the horizon, minus elixir WASTED at a full bar in that time.

    Spending elixir is not a cost by itself (it only matters through what it leads to). An earlier
    version charged every play its cost and waiting nothing, so the model learned "waiting is best"
    and the bot sat at 10 elixir for a whole Training Camp match (run 055851)."""
    s = decision["state"]
    before, after = _at(series, s["t"]), _at(series, s["t"] + horizon)
    dealt = sum(max(0.0, before.get(k, 1.0) - after.get(k, 1.0)) for k in ("enemy_left", "enemy_right"))
    taken = sum(max(0.0, before.get(k, 1.0) - after.get(k, 1.0)) for k in ("our_left", "our_right"))
    wasted = leak(s["t"], s["t"] + horizon) if leak else 0.0
    defended = killed(s["t"], s["t"] + horizon) if killed else 0.0
    return (dealt * ENEMY_TOWER_HP - taken * OUR_TOWER_HP - ELIXIR_VALUE_HP * wasted
            + KILL_VALUE_HP * defended) / 1000.0


def leak_fn(log_rows):
    """wasted(t0, t1): elixir lost to a full bar between t0 and t1 (regen ~1/2.8 per s, x2 late)."""
    full = [(r["t"], r.get("elixir", 0) >= 9.95, r.get("regen", 0.357) or 0.357) for r in log_rows]

    def wasted(t0, t1):
        total, prev = 0.0, None
        for t, is_full, regen in full:
            if t < t0 or t > t1:
                continue
            if prev is not None and is_full:
                total += (t - prev) * regen
            prev = t
        return total
    return wasted


NOTE_WINDOW_S = 2.0
NOTE_LABEL = {"bad": -1.5, "good": 1.5}     # owner verdicts outweigh tower-HP outcomes


def apply_notes(run_dir, decisions, rewards):
    """Owner notes (./note) override the label of decisions within NOTE_WINDOW_S of the moment.
    Only plays get the verdict (a note is about what was played), not the WAIT rows around it."""
    path = Path(run_dir) / "notes.jsonl"
    if not path.exists():
        return rewards
    notes = load_rows(path)
    out = list(rewards)
    for i, d in enumerate(decisions):
        if d["action"]["kind"] == "wait":
            continue
        for n in notes:
            if abs(d["state"]["t"] - n["t"]) <= NOTE_WINDOW_S:
                out[i] = NOTE_LABEL[n["verdict"]]
    return out


def run_dataset(run_dir, horizon=HORIZON_S):
    """(decisions, rewards) for one run; decisions too close to the end (no full horizon) are dropped."""
    run_dir = Path(run_dir)
    dec_path, log_path = run_dir / "decisions.jsonl", run_dir / "log.jsonl"
    if not dec_path.exists() or not log_path.exists():
        return [], []
    fixed = run_dir / "towers_fixed.jsonl"           # re-read towers (tools/backfill) beat the live log
    log_rows = load_rows(log_path)
    series = tower_series(load_rows(fixed) if fixed.exists() else log_rows)
    leak = leak_fn(log_rows)
    killed = deaths_fn(log_rows)
    if not series:
        return [], []
    end = series[-1][0]
    rows = load_rows(dec_path)
    backfill = run_dir / "decisions_backfill.jsonl"   # owner plays recovered after a detector fix
    if backfill.exists():
        rows += load_rows(backfill)
    decisions = [d for d in rows if d["state"]["t"] + horizon <= end]
    return decisions, apply_notes(run_dir, decisions, [label(d, series, horizon, leak, killed) for d in decisions])

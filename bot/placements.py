"""Learned placement spots: where each card is placed in each situation, from human plays (the owner's
watched matches now, TV Royale replays later). They give the policy candidate moves the hand-written
rules never propose (owner: "it could just place a Tombstone - why didn't it learn from my plays?").

Situation = which lane the most urgent enemy is in (left / right / none). Spots are grid cells; the
top cells per (card, situation) become extra shortlist candidates, and the model scores them.
"""
import collections
import json
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "data" / "placements.json"
TOP = 3


def situation(state):
    """state: dict or State. Lane of the enemy closest to arriving, or 'none'."""
    enemies = state["enemies"] if isinstance(state, dict) else [e.__dict__ for e in state.enemies]
    near = [u for u in enemies if u["eta_river"] <= 3.0]
    if not near:
        return "none"
    return min(near, key=lambda u: u["eta_river"])["lane"]


def build(decisions):
    """decisions: iterable of logged decision dicts. Counts human plays per (card, situation, cell)."""
    counts = collections.defaultdict(collections.Counter)
    for d in decisions:
        a = d["action"]
        if d.get("policy") != "human" or a["kind"] != "play":
            continue
        counts[f"{a['card']}|{situation(d['state'])}"][f"{a['x']},{a['y']}"] += 1
    out = {k: [[int(c.split(",")[0]), int(c.split(",")[1]), n] for c, n in v.most_common(TOP)]
           for k, v in counts.items()}
    PATH.write_text(json.dumps(out, indent=0))
    return out


_cache = {"mtime": None, "data": {}}


def spots(card, sit):
    """Top learned cells [(x, y, count)] for this card in this situation (reloaded when retrained)."""
    if not PATH.exists():
        return []
    m = PATH.stat().st_mtime
    if _cache["mtime"] != m:
        _cache["data"], _cache["mtime"] = json.loads(PATH.read_text()), m
    return _cache["data"].get(f"{card}|{sit}", [])

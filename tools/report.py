"""What happened over a set of matches and what the data says. Run: python -m tools.report [--since RUN]"""
import argparse
import collections
import json
from pathlib import Path

import numpy as np

from bot.outcomes import run_dataset

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="only runs after this run id")
    a = ap.parse_args()
    runs = sorted(p for p in (ROOT / "runs").iterdir() if p.is_dir() and p.name != "replays"
                  and (p / "summary.json").exists() and (not a.since or p.name > a.since))
    if not runs:
        raise SystemExit("no finished matches to report on")
    print(f"=== {len(runs)} match(es) ===")
    by_policy = collections.defaultdict(lambda: collections.defaultdict(list))
    for run in runs:
        s = json.loads((run / "summary.json").read_text())
        t = s.get("towers") or {}
        ours = sum(1 for k in ("our_left", "our_right") if t.get(k) == 0.0)
        theirs = sum(1 for k in ("enemy_left", "enemy_right") if t.get(k) == 0.0)
        cov = f", detection explains {s['detection_coverage']:.0%} of elixir spent" if s.get("detection_coverage") is not None else ""
        battle = json.loads((run / "battle.json").read_text()) if (run / "battle.json").exists() else None
        res = (f"{battle['result'].upper()} {battle['us']['crowns']}-{battle['them']['crowns']}" if battle
               else f"towers lost {ours} / taken {theirs} (no battle log)")
        print(f"{run.name}  {s['mode']:7s} {s['seconds']:5.0f}s  {res}  {len(s['plays'])} plays{cov}")
        if battle:
            print(f"    their deck: {', '.join(battle['them']['cards'])}")
        print(f"    their cards recognised: {', '.join(s.get('enemy_deck_seen') or []) or '(none)'}")
        decisions, rewards = run_dataset(run)
        for d, r in zip(decisions, rewards):
            if d["action"]["kind"] != "wait":
                by_policy[d["policy"]][d["action"]["card"] or "ability"].append(r)
    print("\naverage outcome after each move, 10s window (tower HP dealt - taken - elixir, in 1000s):")
    for pol, cards in by_policy.items():
        print(f"  {pol}:")
        for card, rs in sorted(cards.items(), key=lambda kv: -np.mean(kv[1])):
            print(f"    {card:14s} n={len(rs):3d}  {np.mean(rs):+.2f}")
    meta = ROOT / "models" / "q_meta.json"
    if meta.exists():
        m = json.loads(meta.read_text())
        print(f"\nmodel: {m['n_plays']} plays from {len(m['runs'])} matches; held-out rank correlation "
              f"{m.get('heldout_spearman_plays', float('nan')):+.2f} on plays (0 = no skill)")


if __name__ == "__main__":
    main()

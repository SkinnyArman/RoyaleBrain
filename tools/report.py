"""What happened over a set of matches and what the data says. Run: python -m tools.report [--since RUN]"""
import argparse
import json
from pathlib import Path


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


if __name__ == "__main__":
    main()

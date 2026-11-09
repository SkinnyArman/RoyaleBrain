"""Train the learned move scorer from every logged match.

    .venv/bin/python -m tools.train_policy

Reads runs/*/decisions.jsonl + log.jsonl (not runs/replays), labels each decision with its outcome
(bot/outcomes.py), trains a LightGBM regressor on (state, action) -> outcome, evaluates it on held-out
matches, prints what the data says, and saves models/q_lgbm.txt + models/q_meta.json.
"""
import collections
import json
import time
from pathlib import Path

import numpy as np

from bot.features import FEATURES, encode
from bot.outcomes import HORIZON_S, run_dataset

ROOT = Path(__file__).resolve().parent.parent
RUNS, MODELS = ROOT / "runs", ROOT / "models"


def load_all():
    X, y, groups, meta = [], [], [], []
    for run in sorted(p for p in RUNS.iterdir() if p.is_dir() and p.name != "replays"):
        decisions, rewards = run_dataset(run)
        for d, r in zip(decisions, rewards):
            X.append(encode(d["state"], d["action"]))
            y.append(r)
            groups.append(run.name)
            meta.append(d)
    return np.array(X, dtype=np.float32), np.array(y, dtype=np.float32), groups, meta


def learn_profiles():
    """Per enemy card, measured across all matches: walking speed (px/s), lifetime (s), times seen.
    Tracks carry their recognised card in log.jsonl ([id, x, y, w, vy, hp, card])."""
    import statistics
    tracks = {}                                         # (run, id) -> {"card", "t0", "t1", "vys"}
    for run in sorted(p for p in RUNS.iterdir() if p.is_dir() and p.name != "replays"):
        log = run / "log.jsonl"
        if not log.exists():
            continue
        for line in open(log):
            r = json.loads(line)
            for tr in r.get("tracks", []):
                if len(tr) < 7:
                    continue
                k = (run.name, tr[0])
                d = tracks.setdefault(k, {"card": None, "t0": r["t"], "t1": r["t"], "vys": []})
                d["t1"] = r["t"]
                d["card"] = tr[6] or d["card"]
                if tr[4] > 5:
                    d["vys"].append(tr[4])
    per_card = collections.defaultdict(lambda: {"speeds": [], "lifetimes": []})
    for d in tracks.values():
        if d["card"]:
            if len(d["vys"]) >= 5:
                per_card[d["card"]]["speeds"].append(statistics.median(d["vys"]))
            per_card[d["card"]]["lifetimes"].append(d["t1"] - d["t0"])
    out = {c: {"seen": len(v["lifetimes"]),
               "speed_px": round(statistics.median(v["speeds"]), 1) if len(v["speeds"]) >= 3 else None,
               "lifetime_s": round(statistics.median(v["lifetimes"]), 1)}
           for c, v in per_card.items()}
    (ROOT / "data" / "profiles_learned.json").write_text(json.dumps(out, indent=1, sort_keys=True))
    print("\nlearned troop profiles (across matches):")
    for c, v in sorted(out.items(), key=lambda kv: -kv[1]["seen"]):
        sp = f"{v['speed_px'] / 54:.2f} tiles/s" if v["speed_px"] else "speed n/a"
        print(f"  {c:15s} seen {v['seen']:3d}  {sp:16s} lives ~{v['lifetime_s']}s")


def spearman(a, b):
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1]) if len(a) > 2 else float("nan")


def main():
    import lightgbm as lgb
    learn_profiles()
    X, y, groups, meta = load_all()
    from bot import placements
    learned = placements.build(meta)
    print(f"learned placement spots for {len(learned)} (card, situation) pairs from human plays")
    runs = sorted(set(groups))
    plays = [i for i, d in enumerate(meta) if d["action"]["kind"] != "wait"]
    print(f"{len(y)} decisions ({len(plays)} plays) from {len(runs)} matches, horizon {HORIZON_S:.0f}s")
    if len(plays) < 10:
        raise SystemExit("not enough plays to learn from yet")

    # what the data says, before any model
    by_card = collections.defaultdict(list)
    for i in plays:
        a = meta[i]["action"]
        by_card[a["card"] or "ability"].append(y[i])
    print("\naverage outcome after each move (tower HP dealt - taken - elixir wasted at full bar, in 1000s):")
    for card, rs in sorted(by_card.items(), key=lambda kv: -np.mean(kv[1])):
        print(f"  {card:14s} n={len(rs):3d}  mean {np.mean(rs):+.2f}")
    waits = [y[i] for i, d in enumerate(meta) if d["action"]["kind"] == "wait"]
    print(f"  {'(wait)':14s} n={len(waits):3d}  mean {np.mean(waits):+.2f}")

    params = dict(objective="regression", num_leaves=15, min_data_in_leaf=10, learning_rate=0.05,
                  n_estimators=200, subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1)

    # held-out check: leave one match out (needs >= 2 matches)
    metrics = {}
    if len(runs) >= 2:
        preds = np.zeros_like(y)
        for r in runs:
            test = np.array([g == r for g in groups])
            m = lgb.LGBMRegressor(**params).fit(X[~test], y[~test])
            preds[test] = m.predict(X[test])
        metrics = {"heldout_spearman": spearman(preds, y),
                   "heldout_spearman_plays": spearman(preds[plays], y[plays])}
        print(f"\nleave-one-match-out: rank correlation {metrics['heldout_spearman']:+.2f} "
              f"(plays only {metrics['heldout_spearman_plays']:+.2f}); 0 = no skill, 1 = perfect")
    else:
        print("\nonly 1 match: no held-out check yet (need 2+)")

    model = lgb.LGBMRegressor(**params).fit(X, y)
    MODELS.mkdir(exist_ok=True)
    model.booster_.save_model(str(MODELS / "q_lgbm.txt"))
    imp = sorted(zip(FEATURES, model.booster_.feature_importance("gain")), key=lambda kv: -kv[1])[:10]
    info = {"trained": time.strftime("%Y-%m-%d %H:%M"), "n_decisions": int(len(y)), "n_plays": len(plays),
            "runs": runs, "features": FEATURES, "horizon_s": HORIZON_S, **metrics,
            "top_features": [k for k, _ in imp]}
    (MODELS / "q_meta.json").write_text(json.dumps(info, indent=2))
    print("\nmost useful features:", ", ".join(k for k, _ in imp))
    print(f"saved models/q_lgbm.txt ({len(plays)} plays)")


if __name__ == "__main__":
    main()

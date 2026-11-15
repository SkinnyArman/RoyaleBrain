"""Group one run's enemy crops for labelling with its true opponent deck (runs/<id>/battle.json).

    python -m tools.label_run runs/<id> [k]          -> writes a numbered montage + groups file
    python -m tools.label_run runs/<id> --apply 0=monk 3=firecracker 5=skip ...
    python -m tools.label_run runs/<id> --single --deck golden_knight,mega_knight,...   # no battle log
Only cards from that opponent's deck are accepted as labels (no guessing outside the 8). The deck
comes from runs/<id>/battle.json (battle log), or --deck for matches the battle log doesn't list
(Training Camp, friendly battles): it is then saved to runs/<id>/deck.json for the --apply step.
"""
import json
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
from sklearn.cluster import KMeans

from bot.recognizer import DATA, features, grass_fraction

OUT = Path("/tmp")


def groups(run, k):
    paths = [p for p in sorted((run / "enemy_units").glob("*.png"))
             if (im := cv2.imread(str(p))) is not None and im.shape[0] >= 100 and grass_fraction(im) <= 0.85]
    X = np.array([features(cv2.imread(str(p))) for p in paths])
    k = min(k, len(paths))
    km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(X)
    gs = {}
    for p, c in zip(paths, km.labels_):
        gs.setdefault(int(c), []).append(str(p))
    return gs


def montage(gs, path, per=8):
    rows = []
    for c in sorted(gs, key=lambda c: -len(gs[c])):
        tiles = [cv2.resize(cv2.imread(p), (96, 108)) for p in gs[c][:per]]
        tiles += [np.zeros((108, 96, 3), np.uint8)] * (per - len(tiles))
        lab = np.zeros((108, 56, 3), np.uint8)
        cv2.putText(lab, str(c), (4, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)
        cv2.putText(lab, f"n{len(gs[c])}", (4, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        rows.append(np.hstack([lab] + tiles))
    cv2.imwrite(str(path), np.vstack(rows))


def single(run):
    """Numbered montage of every usable crop (labelling one by one is safer than by group)."""
    paths = [p for p in sorted((run / "enemy_units").glob("*.png"))
             if (im := cv2.imread(str(p))) is not None and im.shape[0] >= 100 and grass_fraction(im) <= 0.85]
    tiles = []
    for i, p in enumerate(paths):
        t = cv2.resize(cv2.imread(str(p)), (110, 124))
        cv2.rectangle(t, (0, 0), (30, 15), (0, 0, 0), -1)
        cv2.putText(t, str(i), (2, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
        tiles.append(t)
    while len(tiles) % 10:
        tiles.append(np.zeros((124, 110, 3), np.uint8))
    cv2.imwrite(str(run / "label_single.png"), np.vstack([np.hstack(tiles[i:i + 10]) for i in range(0, len(tiles), 10)]))
    (run / "label_single.json").write_text(json.dumps([str(p) for p in paths]))
    return len(paths)


def their_deck(run):
    if "--deck" in sys.argv:
        deck = sys.argv[sys.argv.index("--deck") + 1].split(",")
        (run / "deck.json").write_text(json.dumps(deck))
        return deck
    if (run / "deck.json").exists():
        return json.loads((run / "deck.json").read_text())
    return json.loads((run / "battle.json").read_text())["them"]["cards"]


def main():
    run = Path(sys.argv[1])
    if "--single" in sys.argv:
        print(f"{single(run)} crops -> {run / 'label_single.png'}")
        print("their deck:", ", ".join(their_deck(run)))
        return
    if "--apply-single" in sys.argv:
        deck = their_deck(run)
        allowed = {c.removeprefix("evo_") for c in deck} | set(deck) | {"skeletons"}
        paths = json.loads((run / "label_single.json").read_text())
        n = 0
        for arg in sys.argv[sys.argv.index("--apply-single") + 1:]:
            card, idx = arg.split("=")
            if card not in allowed:
                raise SystemExit(f"{card} not in this opponent's deck: {deck}")
            d = DATA / card
            d.mkdir(parents=True, exist_ok=True)
            for i in idx.split(","):
                p = Path(paths[int(i)])
                shutil.copy(p, d / f"{run.name[-6:]}_{p.name}")
                n += 1
        print(f"added {n} crops from {run.name}")
        return
    deck = their_deck(run)
    gfile = run / "label_groups.json"
    if "--apply" in sys.argv:
        gs = json.loads(gfile.read_text())
        allowed = {c.removeprefix("evo_") for c in deck} | {c for c in deck}
        n = 0
        for arg in sys.argv[sys.argv.index("--apply") + 1:]:
            g, card = arg.split("=")
            if card == "skip":
                continue
            if card not in allowed:
                raise SystemExit(f"{card} is not in this opponent's deck: {deck}")
            d = DATA / card
            d.mkdir(parents=True, exist_ok=True)
            for p in gs[g]:
                shutil.copy(p, d / f"{run.name[-6:]}_{Path(p).name}")
                n += 1
        print(f"added {n} labelled crops from {run.name}")
        return
    k = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    gs = groups(run, k)
    gfile.write_text(json.dumps({str(c): v for c, v in gs.items()}))
    img = run / "label_groups.png"
    montage(gs, img)
    print(f"{run.name}: {sum(len(v) for v in gs.values())} crops in {len(gs)} groups -> {img}")
    print("their deck:", ", ".join(deck))


if __name__ == "__main__":
    main()

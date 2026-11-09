"""Leave-one-out accuracy of bot.recognizer on datasets/enemy_units. Run: python -m tools.eval_recognizer"""
import collections
from pathlib import Path

import cv2

from bot.recognizer import DATA, Recognizer


def main():
    r = Recognizer(max_dist=99)          # no rejection: see raw nearest-neighbour quality
    paths = [p for d in sorted(DATA.glob("*")) for p in d.glob("*.png")]
    right, conf = 0, collections.Counter()
    dists_ok, dists_bad = [], []
    for i, p in enumerate(paths):
        label, dist = r.predict(cv2.imread(str(p)), exclude=i)
        truth = p.parent.name
        conf[(truth, label)] += 1
        (dists_ok if label == truth else dists_bad).append(dist)
        right += label == truth
    print(f"leave-one-out: {right}/{len(paths)} = {right / len(paths):.0%}")
    for (t, l), n in sorted(conf.items()):
        print(f"  {t:15s} -> {l:15s} {n}{'' if t == l else '   <- wrong'}")
    if dists_ok and dists_bad:
        print(f"distance right: max {max(dists_ok):.2f}; wrong: min {min(dists_bad):.2f}")


if __name__ == "__main__":
    main()

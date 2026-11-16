"""bot/levels.py: badge level reading, leave-one-out on datasets/badge_levels (no phone)."""
import cv2

from bot.levels import DATA, LevelReader, feature


def test_level_reader_never_wrong():
    r = LevelReader()
    paths = [p for d in sorted(DATA.glob("*")) for p in sorted(d.glob("*.png"))
             if feature(cv2.cvtColor(cv2.imread(str(p)), cv2.COLOR_BGR2HSV)) is not None]
    right = wrong = 0
    for i, p in enumerate(paths):
        truth = None if p.parent.name == "none" else int(p.parent.name)
        got = r.read(cv2.cvtColor(cv2.imread(str(p)), cv2.COLOR_BGR2HSV), exclude=i)
        if got is not None:
            right += got == truth
            wrong += got != truth
    assert wrong == 0 and right >= 150, (right, wrong)       # #39: 190 right, 0 wrong, 88 unknown

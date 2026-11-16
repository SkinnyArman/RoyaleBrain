"""Read game state from a BGR screenshot: elixir, cards in hand, enemy troops."""
from pathlib import Path

import cv2
import numpy as np

from . import layout as L
from . import levels

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


def elixir(img):
    """Elixir 0-10, from how far the pink fill reaches along the bar."""
    row = cv2.cvtColor(img[L.ELIXIR_Y - 6:L.ELIXIR_Y + 6, :], cv2.COLOR_BGR2HSV)
    pink = (row[..., 0] > 140) & (row[..., 1] > 120) & (row[..., 2] > 150)
    cols = np.where(pink.mean(axis=0) > 0.5)[0]
    cols = cols[cols >= L.ELIXIR_X0]
    if len(cols) == 0:
        return 0.0
    frac = (cols.max() - L.ELIXIR_X0) / (L.ELIXIR_X1 - L.ELIXIR_X0)
    return round(min(max(frac, 0.0), 1.0) * 10, 1)


def _art(gray):
    """Middle of the card art: skips the frame, the cost badge (bottom) and the evo diamond (top)."""
    h, w = gray.shape
    return gray[int(h * 0.12):int(h * 0.68), int(w * 0.15):int(w * 0.85)]


def load_templates():
    """templates/<card_name>.png = full slot crops (layout.SLOT_BOXES); we match on the art part."""
    out = {}
    for p in TEMPLATE_DIR.glob("*.png"):
        out[p.stem] = _art(cv2.imread(str(p), cv2.IMREAD_GRAYSCALE))
    return out


def card_name(template_name):
    """'hog__grey2' -> 'hog' (extra templates for greyed/animating states share the card name)."""
    return template_name.split("__")[0]


HAND_SEARCH_PX = 24   # how far the card may be shifted from the calibrated box
EMPTY_SLOT_STD = 14   # art-area std-dev below this = empty slot (plain blue tray, right after a play)


class HandReader:
    """hand() with a per-slot cache: a slot is only re-matched when its pixels changed.
    Matching all templates on all 4 slots every frame cost ~80ms (run 2026-11-08-235339).

    A slot's card only changes when we play it: the card leaves (the slot shows the empty tray), the
    next one slides in. Greying out at low elixir also changes the pixels and the greyed art matched the
    wrong template: the same card in two slots in 11-23% of frames of every run (experiments #39). So
    a slot keeps its card unless we played from it (played(), or the empty tray seen), or the new read
    is the same for STABLE frames in a row while the card is in COLOUR (greyed art, with its refill
    sweep, is never trusted to change a card); a read that duplicates another slot is refused. A slot
    played from and not read since is unknown (None), never the card that left."""
    CHANGED = 4.0          # mean abs gray difference that counts as "the slot changed"
    STABLE = 3
    GREY_SAT = 60          # art saturation (75th pct): greyed 6-15, in colour 135+ (7 runs, #39)

    def __init__(self, templates):
        self.templates = templates
        self.last = [None] * 4          # (small gray crop, raw read)
        self.card = [None] * 4          # accepted card per slot
        self.emptied = [True] * 4       # slot seen empty since its card was accepted
        self.streak = [(None, 0)] * 4   # (raw read, consecutive frames)

    def read(self, img):
        gray = cv2.cvtColor(img[L.SLOT_BOXES[0][1]:L.SLOT_BOXES[0][3]], cv2.COLOR_BGR2GRAY)
        raw = []
        for i, (x0, y0, x1, y1) in enumerate(L.SLOT_BOXES):
            small = cv2.resize(gray[:, x0:x1], None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
            prev = self.last[i]
            if prev is not None and float(cv2.absdiff(small, prev[0]).mean()) < self.CHANGED:
                raw.append(prev[1])
                continue
            name = hand(img, self.templates, slots=[i])[0]
            self.last[i] = (small, name)
            raw.append(name)
        empty_now = [False] * 4
        for i, name in enumerate(raw):
            r, n = self.streak[i]
            self.streak[i] = (name, n + 1 if name == r else 1)
            if name is None:
                if self.last[i] is not None and float(_art(gray[:, L.SLOT_BOXES[i][0]:L.SLOT_BOXES[i][2]]).std()) < EMPTY_SLOT_STD:
                    self.emptied[i] = empty_now[i] = True   # the tray: a play left this slot
                continue
            if name == self.card[i] and not self.emptied[i]:
                continue
            others = [c for j, c in enumerate(self.card) if j != i]
            if name in others:
                continue                            # one deck card can't sit in two slots
            x0, _, x1, _ = L.SLOT_BOXES[i]
            colour = np.percentile(_art(cv2.cvtColor(img[L.SLOT_BOXES[i][1]:L.SLOT_BOXES[i][3], x0:x1],
                                                     cv2.COLOR_BGR2HSV)[:, :, 1]), 75) >= self.GREY_SAT
            stable = colour and self.streak[i][1] >= self.STABLE
            if name == self.card[i]:                # still the card we played from here: the play
                if stable:                          # didn't happen (missed tap); trust it again
                    self.emptied[i] = False
                continue
            if self.emptied[i] or self.card[i] is None or stable:
                self.card[i], self.emptied[i] = name, False
        # a slot played from and not re-read yet holds an unknown card (the greyed newcomer is often
        # misread as a card of another slot): unknown, not the card that left
        return [None if e or self.emptied[i] else c for i, (c, e) in enumerate(zip(self.card, empty_now))]

    def played(self, slot):
        """We just played from this slot: its next card may differ (the exact signal; the empty tray
        is the fallback, e.g. when the owner plays)."""
        if slot is not None and 0 <= slot < 4:
            self.emptied[slot] = True


def hand(img, templates, min_score=0.55, slots=(0, 1, 2, 3)):
    """Names of the 4 cards in hand, None if a slot is empty or unknown.

    Greyed (unaffordable) cards are still recognised: normalised correlation on grayscale ignores
    the brightness/contrast change of the grey-out. Affordability comes from the elixir reading.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    names = []
    for x0, y0, x1, y1 in (L.SLOT_BOXES[i] for i in slots):
        m = HAND_SEARCH_PX
        crop = gray[max(0, y0 - m):y1 + m, max(0, x0 - m):x1 + m]
        if float(_art(gray[y0:y1, x0:x1]).std()) < EMPTY_SLOT_STD:   # plain tray = empty slot
            names.append(None)
            continue
        best, score = None, min_score
        for name, t in templates.items():
            if t.shape[0] > crop.shape[0] or t.shape[1] > crop.shape[1]:
                continue
            s_ = float(cv2.matchTemplate(crop, t, cv2.TM_CCOEFF_NORMED).max())
            if s_ > score:
                best, score = name, s_
        names.append(card_name(best) if best else None)
    return names


# Health-bar colors (HSV), measured on calib/battle_7elixir.png. A bar = light fill + dark empty part,
# so damaged units are still found, and fill / (fill + empty) = the unit's HP fraction.
# Enemy troop colors are ASSUMED to match the enemy tower bar: verify on a live frame.
TEAM_COLORS = {
    "ally": {"fill": ((95, 108), (110, 200), (220, 255)), "empty": ((106, 116), (80, 140), (90, 135))},
    "enemy": {"fill": ((165, 180), (150, 255), (180, 255)), "empty": ((158, 172), (80, 150), (70, 120))},
}


def _in(hsv, rng):
    """uint8 mask (0/255) of pixels inside an HSV range; cv2.inRange runs in C++."""
    (h0, h1), (s0, s1), (v0, v1) = rng
    return cv2.inRange(hsv, (h0, s0, v0), (h1, s1, v1))


def arena_hsv(img, y0=L.ARENA_Y[0], y1=L.ARENA_Y[1]):
    """HSV of the arena rows, computed once per frame and shared by both teams."""
    return cv2.cvtColor(img[y0:y1], cv2.COLOR_BGR2HSV)


# Level badges: every troop/building has one (a small square with its level in white digits),
# red for the enemy, blue for us. Units at full HP show ONLY the badge (no health bar), so the
# badge is what we detect. Measured on 1v1 practice frames 2026-11-08 (half-res, upscaled):
# enemy badge HSV ~(171-172, 180-200, 135-170); ally badge ~(103, 150, 154) (fewer samples).
BADGE = {
    "enemy": ((165, 179), (130, 255), (95, 215)),
    "ally": ((94, 112), (90, 255), (95, 245)),     # measured on our Tombstone badge (10-90th pct)
}
BADGE_L15 = ((0, 13), (150, 255), (95, 245))    # badge sat ~200; bridge wood sat ~90-116
BADGE_PX = (16, 46)          # badge side length range at 1080x2400
# Digit color inside the badge: white on enemy badges, YELLOW on ours (verified on the Tombstone).
# Our units at full HP show no badge at all; only damaged ones do.
DIGITS = {"enemy": ((0, 179), (0, 70), (190, 255)), "ally": ((18, 42), (80, 255), (110, 255))}


def bars(img, team, y0=L.ARENA_Y[0], y1=L.ARENA_Y[1], hsv=None):
    """Units of one team, found by their level badge. Returns (x, y, w, hp) per unit.

    x, y = badge center (just above the unit), w = health-bar width if a bar is showing (else the
    badge width), hp = bar fill fraction, 1.0 when no bar is shown (full HP).
    Enemy badges come in two styles, searched separately (mixing them merged badges with sprites):
    pink-red + white digits, and level-15 orange-red + YELLOW digits (run 061201 was blind to them).
    """
    if hsv is None:
        hsv = arena_hsv(img, y0, y1)
    styles = [(BADGE[team], DIGITS[team])]
    if team == "enemy":
        styles.append((BADGE_L15, DIGITS["ally"]))
    out = []
    for badge, digits in styles:
        for p in _badges(hsv, team, badge, digits, y0):
            if all(abs(p[0] - q[0]) > 12 or abs(p[1] - q[1]) > 12 for q in out):
                out.append(p)
    return out


def _badges(hsv, team, badge, digits, y0):
    mask = _in(hsv, badge)
    white = _in(hsv, digits)
    # The white digits cover ~1/3 of the badge: count white pixels next to team color as badge,
    # then close small gaps, so each badge becomes one solid square.
    near = cv2.dilate(mask, np.ones((9, 9), np.uint8))
    solid = cv2.bitwise_or(mask, cv2.bitwise_and(white, near))
    solid = cv2.morphologyEx(solid, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, _, stats, cent = cv2.connectedComponentsWithStats(solid, connectivity=8)
    c = TEAM_COLORS[team]
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if not (BADGE_PX[0] <= h <= BADGE_PX[1] and w >= BADGE_PX[0]):
            continue
        if w > 1.6 * h:
            w = h                                           # a health bar is attached: keep the badge square
            area = cv2.countNonZero(solid[y:y + h, x:x + w])
        if not (w <= BADGE_PX[1] and 0.6 <= w / h <= 1.6 and area >= 0.5 * w * h):
            continue
        inside = cv2.countNonZero(white[y:y + h, x:x + w]) / float(w * h)
        team_px = cv2.countNonZero(mask[y:y + h, x:x + w]) / float(w * h)
        if not (0.08 <= inside <= 0.6 and team_px >= 0.2):  # digits + team-colored square
            continue
        cx, cy = x + w / 2.0, y + h / 2.0 + y0
        if any(bx0 <= cx <= bx1 and by0 <= cy <= by1 for bx0, by0, bx1, by1 in L.TOWER_BAR_MASKS):
            continue
        bodies = L.OUR_TOWER_BODIES if team == "ally" else L.ENEMY_TOWER_BODIES
        if any(bx0 <= cx <= bx1 and by0 <= cy <= by1 for bx0, by0, bx1, by1 in bodies):
            continue                                        # tower decorations look like badges
        # Level from the badge digits (bot/levels.py), enemies only: ours are known (sim.OUR_LEVELS).
        lv = levels.reader().read(hsv[max(0, y - 3):y + h + 3, max(0, x - 3):x + w + 3]) if team == "enemy" else None
        # Health bar (only when damaged) starts at the badge's right edge, same height.
        strip = hsv[y + h // 4:y + 3 * h // 4, x + w:min(x + w + 170, hsv.shape[1])]
        if strip.size == 0:                                 # badge at the screen edge: no room for a bar
            out.append((cx, cy, float(w), 1.0, lv))
            continue
        f = cv2.countNonZero(_in(strip, c["fill"]))
        if team == "enemy":
            f += cv2.countNonZero(_in(strip, ((0, 5), c["fill"][1], c["fill"][2])))
        e = cv2.countNonZero(_in(strip, c["empty"]))
        rows = max(1, strip.shape[0])
        bar_w = (f + e) / rows
        if bar_w >= 15:
            out.append((cx, cy, float(bar_w), round(f / (f + e), 2), lv))
        else:
            out.append((cx, cy, float(w), 1.0, lv))
    return out


class StaticFilter:
    """Learns arena decorations that look like bars (e.g. blue ornaments around our king tower).

    A detection that stays at the same spot (±STILL_PX) with the same HP for STATIC_AFTER seconds is
    scenery: real troops move, and buildings lose HP over their lifetime. Works on any arena skin.
    """
    STILL_PX = 6
    STATIC_AFTER = 8.0

    def __init__(self):
        self.candidates = []       # [x, y, hp, first seen]
        self.static = []           # (x, y)

    def update(self, points, now):
        """Candidates are matched by distance and HP within a tolerance (grid-cell keys reset on
        tiny jitter, so decorations at e.g. (100, 1068) were never learned; run 010052)."""
        kept = []
        for p in points:
            c = next((c for c in self.candidates if abs(c[0] - p[0]) <= self.STILL_PX * 2
                      and abs(c[1] - p[1]) <= self.STILL_PX * 2 and abs(c[2] - p[3]) <= 0.06), None)
            kept.append(c if c else [p[0], p[1], p[3], now])
            if c and now - c[3] >= self.STATIC_AFTER and not self.is_static(p):
                self.static.append((c[0], c[1]))
        self.candidates = kept
        return [p for p in points if not self.is_static(p)]

    def learn_now(self, points):
        """Everything visible right at match start is scenery: no troop exists yet (ladder arenas
        have tower/king decorations that look like badges; run 042916: ~1/4 of 'enemy units')."""
        for p in points:
            if not self.is_static(p):
                self.static.append((p[0], p[1]))

    def is_static(self, p):
        return any(abs(p[0] - x) <= self.STILL_PX * 2 and abs(p[1] - y) <= self.STILL_PX * 2 for x, y in self.static)


def enemies(img, hsv=None):
    return bars(img, "enemy", hsv=hsv)


def allies(img, hsv=None):
    return bars(img, "ally", hsv=hsv)


class TowerMemory:
    """A tower bar can be hidden by troops standing on it, which reads as None. Keep the last value;
    only call a tower destroyed (0.0) if it was already low and has been unreadable for a while."""
    DESTROYED_BELOW = 0.25    # run 000342: last reading 0.156 before the tower fell, never marked
    DESTROYED_AFTER = 2.0

    def __init__(self):
        self.value, self.missing_since = {}, {}

    def update(self, reading, now):
        out = {}
        for name, v in reading.items():
            if v is not None:
                self.value[name], self.missing_since[name] = v, None
                out[name] = v
                continue
            since = self.missing_since.get(name) or now
            self.missing_since[name] = since
            last = self.value.get(name)
            if last is not None and last <= self.DESTROYED_BELOW and now - since >= self.DESTROYED_AFTER:
                self.value[name] = 0.0
            out[name] = self.value.get(name)
        return out


def unit_crop(img, x, y):
    """The area under a unit's badge where its sprite is (also what the recogniser was trained on)."""
    h, w = img.shape[:2]
    return img[int(max(0, y - 30)):int(min(h, y + 150)), int(max(0, x - 80)):int(min(w, x + 80))]


DROP_OFFSET = (15, 55)      # placement = drop + offset; calibrated on 64 of our own logged plays
                            # (2026-11-09): spread ~±40px, i.e. within one tile


def cost_drops(img):
    """Pink elixir-cost drops ("-4") the game draws just above a fresh placement: (x, y) list."""
    hsv = cv2.cvtColor(img[150:1800], cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, (140, 110, 140), (172, 255, 255))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, _, st, cen = cv2.connectedComponentsWithStats(m)
    return [(float(cen[i][0]), float(cen[i][1]) + 150) for i in range(1, n)
            if 18 <= st[i][2] <= 70 and 18 <= st[i][3] <= 80 and 0.5 <= st[i][2] / st[i][3] <= 1.6
            and st[i][4] >= 0.35 * st[i][2] * st[i][3]]


TOWER_BAR_SEARCH = (-30, 46)   # rows around the calibrated bar row to search: arena skins differ
                               # (ladder arena: enemy bars ~25px lower than Training Camp)


def tower_hp(img):
    """HP fraction of each princess tower from its bar (None = no bar = destroyed or hidden).

    The bar row is searched within TOWER_BAR_SEARCH of the calibrated row (best = the row where the
    bar's fill + empty colors cover most of its width). Verified in Training Camp against on-screen
    numbers; ladder arena checked 2026-11-09 (bars 20-30px lower)."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    out = {}
    for name, (team, y0, x0, x1) in L.TOWER_BARS.items():
        c = TEAM_COLORS[team]
        best_cov, best_frac = 0, None
        for y in range(y0 + TOWER_BAR_SEARCH[0], y0 + TOWER_BAR_SEARCH[1], 3):
            row = hsv[y - 2:y + 3, x0:x1]
            fill = _in(row, c["fill"])
            if team == "enemy":
                fill = cv2.bitwise_or(fill, _in(row, ((0, 5), c["fill"][1], c["fill"][2])))
            empty = _in(row, c["empty"])
            f, e = int((fill > 0).any(axis=0).sum()), int((empty > 0).any(axis=0).sum())
            if f + e > best_cov:
                best_cov, best_frac = f + e, f / float(x1 - x0)
        out[name] = round(min(best_frac, 1.0), 3) if best_cov > 0.5 * (x1 - x0) else None
    return out


def champion_ready(img, template, min_score=0.7):
    """True when the champion ability button (Golden Knight's sword, 1 elixir) is on screen."""
    if template is None:
        return False
    x0, y0, x1, y1 = L.CHAMPION_BOX
    crop = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    return float(cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED).max()) >= min_score


def in_match(img, template, min_score=0.8):
    """True while a battle is running: the 'Next:' label left of the hand is only shown in a match.

    Scores on the 2026-11-08 practice run: 1.00 during the match, 0.37-0.48 on result screens/menus.
    """
    if template is None:
        return True
    x0, y0, x1, y1 = L.NEXT_LABEL_BOX
    crop = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    return float(cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED).max()) >= min_score


def load_next_template():
    p = TEMPLATE_DIR.parent / "templates_ui" / "next_label.png"
    return cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) if p.exists() else None


def load_champion_template():
    p = TEMPLATE_DIR.parent / "templates_ui" / "champion_ability.png"
    return cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) if p.exists() else None

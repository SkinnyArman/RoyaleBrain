"""Spell value in elixir, and the best place to cast one.

value = sum over enemy units hit:
          unit_value            if the spell kills it (remaining HP <= damage, or <= damage + what our
                                troops next to it will deal: owner's "half-HP Barbarians next to our
                                Witch are easy to kill")
          unit_value * dmg/HP * PARTIAL   otherwise (chip damage on survivors is worth little)
      + tower damage / ELIXIR_HP if an enemy princess tower is inside (owner: "if it hits the tower,
        even better")
A spell is worth casting when value >= its cost + MARGIN. This is what stops a Log on a full-HP
Wizard + Valkyrie (run 010908, 135s) and a Poison on full-HP Barbarians.
"""
import math

from . import layout as L
from .profiles import SPELLS, remaining_hp, unit_value

ELIXIR_HP = 80.0            # 1 elixir ~ 80 tower HP (prior)
PARTIAL = 0.35              # value of damage that doesn't kill, relative to a kill
SUPPORT_REACH_PX = 5 * 54   # our troops this close add their damage over the next few seconds
SUPPORT_EXTRA_DMG = 350.0   # damage one nearby troop of ours adds before the unit escapes (unverified)
MARGIN = 0.5
COST = {"poison": 4, "log": 2}


def _inside(card, xy, p):
    if card == "poison":
        return math.dist(xy, p) <= SPELLS["poison"]["radius_px"]
    s = SPELLS["log"]                     # Log rolls up-screen from xy for length_px, width_px wide
    return abs(p[0] - xy[0]) <= s["width_px"] / 2 and xy[1] - s["length_px"] <= p[1] <= xy[1] + 20


def touches_enemy_king(card, xy):
    """Would this spell hit their king tower? That ACTIVATES it (owner, run 061822: a Poison next to
    their tower woke the king). Only allowed once both princess towers are down - never, for now."""
    kx, ky = L.ENEMY_KING
    if card == "poison":
        return math.dist(xy, (kx, ky)) <= SPELLS["poison"]["radius_px"] + L.KING_HALF_PX
    s = SPELLS["log"]
    return abs(kx - xy[0]) <= s["width_px"] / 2 + L.KING_HALF_PX and xy[1] - s["length_px"] <= ky + L.KING_HALF_PX


def spell_value(card, xy, tracks, helpers=(), lead_s=1.0):
    """Elixir value of casting `card` at `xy`. helpers: positions of our troops near the fight."""
    if touches_enemy_king(card, xy):
        return 0.0
    dmg = SPELLS[card]["damage"]
    value = 0.0
    for t in tracks:
        p = t.at(lead_s) if card == "poison" else (t.x, t.y)
        if not _inside(card, xy, p):
            continue
        hp = remaining_hp(t)
        extra = SUPPORT_EXTRA_DMG * sum(1 for h in helpers if math.dist(h, p) <= SUPPORT_REACH_PX)
        if hp <= dmg * 0.95 or hp <= (dmg + extra) * 0.95:
            value += unit_value(t.card) if t.card else (1.0 if t.y0 >= L.RIVER_Y + 200 else unit_value(None))
        else:
            value += unit_value(t.card) * PARTIAL * dmg / hp
    if value <= 0.0:
        return 0.0          # tower chip alone never justifies a spell (owner: "it could just place a Tombstone")
    for name in ("enemy_left", "enemy_right"):
        tx, ty = L.TOWERS[name]
        if _inside(card, xy, (tx, ty)) or (card == "log" and _inside(card, xy, (tx, ty + 60))):
            value += dmg * SPELLS[card]["tower_factor"] / ELIXIR_HP
    return value


def best_spell(card, tracks, helpers=(), lead_s=1.0):
    """(xy, value) of the best cast. Candidates: every unit's (predicted) spot, group centers, and
    for the Log a start just below each unit so it rolls through what's above it."""
    if not tracks:
        return None, 0.0
    pts = [t.at(lead_s) if card == "poison" else (t.x, t.y) for t in tracks]
    cands = list(pts)
    r = SPELLS["poison"]["radius_px"] if card == "poison" else SPELLS["log"]["width_px"]
    for cx, cy in pts:
        group = [p for p in pts if math.dist((cx, cy), p) <= r]
        cands.append((sum(p[0] for p in group) / len(group), sum(p[1] for p in group) / len(group)))
    if card == "log":
        cands = [(x, y + 80) for x, y in cands]
    best, best_v = None, 0.0
    for c in cands:
        v = spell_value(card, c, tracks, helpers, lead_s)
        if v > best_v:
            best, best_v = c, v
    return best, best_v


def worth_it(card, value):
    return value >= COST[card] + MARGIN

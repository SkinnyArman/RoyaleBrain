"""Every move available at one moment: play a card on a grid cell, use the champion ability, or wait.

The grid is fixed (one cell per tile on our side for troops/buildings, a coarser 2-tile grid over the
whole arena for spells) so a learned scorer always sees the same action space, and any placement
(from a rule, a human replay...) can be snapped to its cell for training labels.
"""
from dataclasses import dataclass

from . import layout as L
from .cards import CARDS

T = L.TILE_PX


def _range(lo, hi, step):
    v, out = lo + step / 2, []
    while v < hi:
        out.append(int(v))
        v += step
    return out


TROOP_GRID = [(x, y) for y in _range(L.OUR_DEPLOY_Y[0], L.OUR_DEPLOY_Y[1], T)
              for x in _range(L.DEPLOY_X[0], L.DEPLOY_X[1], T)]
SPELL_GRID = [(x, y) for y in _range(L.ARENA_Y[0] + 40, L.OUR_DEPLOY_Y[1], 2 * T)
              for x in _range(L.DEPLOY_X[0], L.DEPLOY_X[1], 2 * T)]


@dataclass(frozen=True)
class Action:
    kind: str                 # "play" / "ability" / "wait"
    card: str | None = None
    slot: int | None = None
    x: int | None = None
    y: int | None = None

    def to_dict(self):
        return {"kind": self.kind, "card": self.card, "slot": self.slot, "x": self.x, "y": self.y}


WAIT = Action("wait")
ABILITY = Action("ability", card="gk_ability")


def grid_for(card):
    return SPELL_GRID if CARDS.get(card, {}).get("kind") == "spell" else TROOP_GRID


def candidates(state):
    """All legal actions for this state. Unaffordable cards are left out."""
    out = [WAIT]
    if state.champion_ready and state.elixir >= 1:
        out.append(ABILITY)
    for slot, card in enumerate(state.hand):
        if not card or CARDS.get(card, {}).get("cost", 99) > state.elixir:
            continue
        out.extend(Action("play", card, slot, x, y) for x, y in grid_for(card))
    return out


def snap(card, slot, xy):
    """The grid cell action closest to a free placement (for labelling rule/human moves)."""
    gx, gy = min(grid_for(card), key=lambda c: (c[0] - xy[0]) ** 2 + (c[1] - xy[1]) ** 2)
    return Action("play", card, slot, gx, gy)

"""What we know about the opponent's deck, and how it changes our placements.

Sources of card knowledge (most to least reliable):
1. The owner tells us (`--enemy-deck rocket,golem,...`), e.g. after watching a Training Camp opponent.
2. Later: a detector that names enemy units/spells from the frames.
Without names, plays are still counted for the cycle (each play moves their queue by one).

Cycle rule (Clash Royale, unverified): 4 cards in hand, a played card goes to the back of a
4-card queue, so it cannot be played again until 4 other cards have been played after it.
"""
import math

from . import layout as L
from .cards import prop

T = L.TILE_PX
# Spell radii in px (unverified, community values in tiles x TILE_PX). Used to keep our troops
# out of spots where one spell would hit them AND our tower.
SPELL_RADIUS = {
    "rocket": 2.0 * T, "fireball": 2.5 * T, "poison": 3.5 * T, "lightning": 3.5 * T,
    "arrows": 4.0 * T, "earthquake": 3.5 * T, "zap": 2.5 * T, "giant_snowball": 2.5 * T,
    "barbarian_barrel": 1.3 * T, "log": 2.0 * T,
}


class Opponent:
    def __init__(self, known_deck=()):
        self.deck = set(known_deck)            # cards we know they have
        self.plays = []                        # card name or None (unknown), oldest first
        self.responses = {}                    # our card -> [their card that answered it]

    def played(self, card=None):
        self.plays.append(card)
        if card:
            self.deck.add(card)

    # --- how this opponent answers our attacks, learned during the match (owner: "they defended the
    #     Hog with Skeletons once: next time attack with the Poison ready") ---
    def note_response(self, our_card, their_card):
        self.responses.setdefault(our_card, []).append(their_card)

    def response_prob(self, our_card, prop_name):
        """Share of their answers to `our_card` that had the property (e.g. "swarm"). 0 if unseen."""
        seen = self.responses.get(our_card, [])
        return sum(1 for c in seen if prop(c, prop_name)) / len(seen) if seen else 0.0

    def identify(self, index, card):
        """A play counted as unknown was recognised later: fill in its card."""
        if 0 <= index < len(self.plays) and self.plays[index] is None:
            self.plays[index] = card
            self.deck.add(card)
            return True
        return False

    def may_have_in_hand(self, card):
        """False only if we know they played it within their last 4 plays."""
        if card not in self.deck:
            return False
        return card not in self.plays[-4:]

    def hand_estimate(self):
        """Cards they can hold now: their deck minus what they played in their last 4 plays.
        Exact once all 8 cards are known and every play is identified (owner: "predict what they
        play next"). Unknown plays (None) still move the cycle."""
        return [c for c in self.deck if self.may_have_in_hand(c)]

    def may_have_any(self, prop_name):
        """Could any card currently possible in their hand have this property? With an unknown
        deck, assume yes (safe default)."""
        if not self.deck:
            return True
        return any(prop(c, prop_name) for c in self.hand_estimate())

    def threatening_spells(self):
        return [c for c in SPELL_RADIUS if self.may_have_in_hand(c)]

    def safe_spot(self, xy, protect=None):
        """Move a troop placement so no single known spell can hit it and one of our towers.

        A spell of radius r hits both if they are within 2r of each other. If too close, push the
        troop straight away from the nearest tower until the gap is 2r + margin, staying on our side.
        """
        spells = self.threatening_spells()
        if not spells:
            return xy
        r = max(SPELL_RADIUS[s] for s in spells)
        x, y = xy
        towers = protect or [L.TOWERS["our_left"], L.TOWERS["our_right"]]
        tx, ty = min(towers, key=lambda t: math.dist(t, (x, y)))
        d = math.dist((tx, ty), (x, y))
        need = 2 * r + 0.5 * T
        if d >= need:
            return xy
        if d < 1:                               # on top of the tower: move toward the river
            ux, uy = 0.0, -1.0
        else:
            ux, uy = (x - tx) / d, (y - ty) / d
        nx, ny = tx + ux * need, ty + uy * need
        return nx, max(min(ny, 1700), L.RIVER_Y + 60)

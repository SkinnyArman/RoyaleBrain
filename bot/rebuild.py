"""Live board -> a RoyaleSim battle, so search (bot/search.py) can try moves on the phone (R6 on R2).

Everything comes from what the phone saw (AGENTS.md "train on what the phone can see"):
  units     enemy tracks seen in 3+ frames, by recognised card; an unnamed one stands in by the size of
            the play it came with (STAND_IN: 1 unit a Knight, 2 an Archer, 3+ a Goblin; v1 copied their
            most-played card, and with only a Golden Knight named every enemy became one, #38), our troops from vision
            (labelled tracks) + dead-reckoned estimates at full HP. Positions screen px -> tiles
            (bot/sim.to_tile); a ground unit on water (the river) moves to the nearest land.
            One track = one unit (a Skeleton Army seen as 4 bars is 4 Skeletons).
  towers    HP fraction from vision x the tower's max HP (king 1.0: not read); a fallen princess
            wakes that side's king
  elixir    ours from the bar, theirs from economy.EnemyElixir (counted, capped at 10)
  hands     ours: the 4 cards on screen + our own cycle (queue = our last 4 plays); theirs:
            Opponent.sample over the plays seen (exact once all 8 are seen, unseen cards guessed
            uniformly over the catalogue). Deck order = hand + queue (reset shuffle=0 deals in order).
  levels    ours from sim.OUR_LEVELS; theirs READ from each unit's badge (bot/levels.py, vote over
            frames); a unit not read yet: the level read most often on this opponent so far (a
            deck card: the level read on that card), THEIR_LEVEL before anything is read; towers
            TOWER_LEVEL.
Not rebuilt (v1): spells and projectiles in flight, stuns, buildings' lifetime, units mid-deploy.
"""
import json
import random
from collections import Counter

import numpy as np
import royalesim

from .sim import OUR_DECK, OUR_LEVELS, TICKS_PER_S, TILE, Sim, to_tile
from tools.build_dataset import ElixirCount

THEIR_LEVEL, TOWER_LEVEL = 14, 14              # their level until a badge is read (match 6-7 badges: 13-15)
STAND_IN = {1: "Knight", 2: "Archer", 3: "Goblins"}    # units in the play -> neutral stand-in card
TOWER_KEYS = [("our_left", "our_right"), ("enemy_left", "enemy_right")]   # engine k 1, 2 per team


class Rebuild:
    def __init__(self, cid, seed=0):
        """cid: our card key -> engine catalogue id (live_model.ModelPolicy.cid)."""
        self.sim, self.cid = Sim(), cid
        self.b = royalesim.Battle(card_names=None, slot_of_k=[[0, 1, 2], [0, 1, 2]])
        self.rng = random.Random(seed)
        cat = self.sim.catalogue
        self.flying = {i: bool(r[5]) for i, r in enumerate(cat)}
        self.pool = self._deck_cards()
        self.our = [cid(k) for k in OUR_DECK]
        self.our_level = {cid(k): OUR_LEVELS.get(k, 14) for k in OUR_DECK}
        self.key_of = {cid(k): k for k in OUR_DECK}
        self.unit_name, self.kind = {}, {}
        self.seen_levels, self.card_levels = Counter(), {}   # badge levels read this match
        self._counted = set()                                 # track ids already counted
        grid = np.array(self.b.passable_half_cells(), bool)          # [hy][hx], half-tile cells
        self.land = np.argwhere(grid)                                  # (hy, hx) of passable cells
        self.grid = grid
        self.b.reset(seed=0, decks=[self.our, self.our], shuffle=0, start_tick=0, elixir_milli=[5000, 5000],
                     tower_hp=None, spawns=[], tower_levels=[TOWER_LEVEL, TOWER_LEVEL])
        self.tower_max = json.loads(self.b.state_json())["players"][0]["tower_max_hp"]

    def _deck_cards(self):
        """Catalogue ids that can be a deck card (guesses for their unseen cards)."""
        from .search import Hidden
        return sorted(Hidden._internal_ids(self.sim))

    def name_of(self, cid, level):
        """A card's own unit record name ('SkeletonArmy' -> 'Skeleton'); None for a spell."""
        if (cid, level) not in self.unit_name:
            try:
                rows = self.b.unit_hitpoints(cid, level)
            except ValueError:
                rows = self.b.unit_hitpoints(cid, 14)
            self.unit_name[cid, level] = rows[0][1] if rows else None
        return self.unit_name[cid, level]

    def _on_land(self, tx, ty):
        hx, hy = int(np.clip(tx * 2, 0, self.grid.shape[1] - 1)), int(np.clip(ty * 2, 0, self.grid.shape[0] - 1))
        if self.grid[hy, hx]:
            return tx, ty
        hy, hx = self.land[np.argmin((self.land[:, 0] - hy) ** 2 + (self.land[:, 1] - hx) ** 2)]
        return (hx + 0.5) / 2, (hy + 0.5) / 2

    def spawnable(self, cid, form, level):
        """(record name, form) the engine accepts for this card's unit, or None: an evolution is named
        by its unit record ('Witch', 1) or, where that has no form, the card ('Barbarians', 1); else
        the base unit stands in."""
        key = (cid, form, level)
        if key not in self.kind:
            unit = self.name_of(cid, level)
            self.kind[key] = None
            tries = [(unit, form), (self.sim.name(cid), form), (unit, 0)] if form else [(unit, 0)]
            for name, f in tries:
                try:
                    if name and self.b.unit_spawn_kind(name, f) in ("stands", "fresh"):
                        self.kind[key] = (name, f)
                        break
                except ValueError:
                    continue
        return self.kind[key]

    def _spawn(self, team, cid, form, level, px, py, hp_frac):
        got = self.spawnable(cid, form, level)
        if got is None:
            return None
        name, form = got
        tx, ty = to_tile(px, py)
        tx, ty = float(np.clip(tx, 0.3, 17.7)), float(np.clip(ty, 0.3, 31.7))
        if not self.flying.get(cid):
            tx, ty = self._on_land(tx, ty)
        hp = -1 if hp_frac >= 0.99 else max(1, int(hp_frac * self.b.unit_hitpoints(cid, level)[0][2]))
        return (name, team, int(tx * TILE), int(ty * TILE), hp, level, form)

    # ------------------------------------------------------------- hands
    def our_order(self, hand_keys, our_cycle):
        """Our 8 deck ids as hand (4, screen order) + queue (4, next first)."""
        hand = [self.cid(k) if k else None for k in hand_keys]
        hand = [c if c in self.our else None for c in hand]
        queue = [c for c in our_cycle.queue() if c is not None and c not in hand]
        rest = [c for c in self.our if c not in hand and c not in queue]
        hand = [c if c is not None else rest.pop(0) for c in hand]
        queue = queue[-4:]
        queue = rest[:4 - len(queue)] + queue                  # unknown front: cards not played lately
        return hand + queue

    def their_order(self, opponent):
        """Their 8 deck ids (hand + queue) and forms, from the cycle tracker, unknowns sampled."""
        form = {}
        tr = type(opponent)()
        for k in opponent.plays:
            c = self.cid(k) if k else None
            tr.played(c)
            if c is not None and k.startswith("evo_"):
                form[c] = 1
        for k in opponent.deck:
            c = self.cid(k)
            if c is not None:
                tr.deck.add(c)
                form[c] = form.get(c, 0) | (1 if k.startswith("evo_") else 0)
        hand, queue = tr.sample(self.rng, self.pool)
        deck = hand + queue
        return deck, [form.get(c, 0) for c in deck]

    # ------------------------------------------------------------- board
    def build(self, state, enemies, opponent, our_cycle):
        """-> (royalesim.Battle with the live board, its state dict, seen, counts) for Search.choose."""
        tick = int(state.t * TICKS_PER_S)
        ours = self.our_order(state.hand, our_cycle)
        theirs, their_forms = self.their_order(opponent)
        groups = Counter(getattr(u, "play_index", None) for u in enemies)
        for u in enemies:
            lv = getattr(u, "level", None)
            if lv and getattr(u, "id", None) not in self._counted:
                self._counted.add(getattr(u, "id", None))
                self.seen_levels[lv] += 1
                if u.card:
                    self.card_levels[self.cid(u.card)] = lv
        usual = self.seen_levels.most_common(1)[0][0] if self.seen_levels else THEIR_LEVEL
        spawns = []
        for u in enemies:
            c = self.cid(u.card) if u.card else None
            form = 1 if u.card and u.card.startswith("evo_") else 0
            if c is None:                                  # no play index on a live track: a spawn
                pi = getattr(u, "play_index", -1)           # (skeletons, goblins); no attribute: unknown
                size = 1 if pi == -1 else 3 if pi is None else min(3, groups[pi])
                c = self.sim.ids[STAND_IN[size]]
            spawns.append(self._spawn(1, c, form, getattr(u, "level", None) or usual, u.x, u.y, u.hp))
        visible = {u.card for u in state.allies if u.card}
        for u in state.allies:
            c = self.cid(u.card)
            if c in self.our_level:
                spawns.append(self._spawn(0, c, 0, self.our_level[c], u.x, u.y, u.hp))
        for k, x, y in state.our_units:
            c = self.cid(k)
            if k not in visible and c in self.our_level:
                spawns.append(self._spawn(0, c, 0, self.our_level[c], x, y, 1.0))
        spawns = [s for s in spawns if s]
        tw = state.towers or {}
        frac = lambda k: 1.0 if tw.get(k) is None else max(0.0, float(tw[k]))
        tower_hp = [[self.tower_max[0]] + [int(frac(k) * self.tower_max[i + 1]) for i, k in enumerate(keys)]
                    for keys in TOWER_KEYS]
        wake = [5000 if 0 in hp[1:] else -1 for hp in tower_hp]
        kw = dict(seed=tick, decks=[ours, theirs], shuffle=0, start_tick=tick,
                  elixir_milli=[int(min(10, state.elixir) * 1000), int(min(10, state.enemy_elixir) * 1000)],
                  tower_hp=tower_hp, spawns=[], forms=[[0] * 8, their_forms],
                  levels=[[self.our_level[c] for c in ours], [self.card_levels.get(c, usual) for c in theirs]],
                  tower_levels=[TOWER_LEVEL, TOWER_LEVEL], king_wake_ms=wake)
        for _ in range(len(spawns) + 1):                       # a refused unit is left out, the rest kept
            try:
                self.b.reset(unit_spawns=spawns, **kw)
                break
            except ValueError as e:
                bad = [s for s in spawns if f"spawn {s[0]} at ({s[2]}, {s[3]})" in str(e)]
                if not bad:                                    # not tied to one unit: keep none
                    self.last_error = str(e)
                    spawns = []
                else:
                    spawns.remove(bad[0])
        st = json.loads(self.b.state_json())
        seen = {0: {c for c in theirs if c in self._their_seen(opponent)}, 1: set(our_cycle.deck)}
        counts = [ElixirCount(), ElixirCount()]
        for cnt, v in zip(counts, (state.elixir, state.enemy_elixir)):
            cnt.milli, cnt.tick = min(10, v) * 1000.0, tick
        return self.b, st, seen, counts, len(spawns)

    def _their_seen(self, opponent):
        return {c for k in opponent.deck if (c := self.cid(k)) is not None}

    def our_key(self, cid):
        return self.key_of.get(cid)

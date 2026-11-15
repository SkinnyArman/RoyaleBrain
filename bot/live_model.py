"""R2 v1: the trained model (r3) plays on the phone.

    ./play --model models/r3.pt            # the model decides; vision, taps, logs as before
    ./play --model models/r3.pt --dry-run  # decide and log, never tap

Each 0.5 s (and not within 1 s of our last play, while the elixir bar catches up), the live State is
turned into exactly the input the model was trained on (tools/build_dataset.observe):
  units     enemy tracks (card from the recogniser, else UNKNOWN: training hid 50% of enemy ids
            for this) + our troops (labelled tracks and dead-reckoned estimates), positions mapped
            from screen pixels to tiles (bot/sim.to_tile), HP fraction, size/flying from the card
  scalars   time, our elixir (vision), their elixir (economy.EnemyElixir), princess towers (king
            tower HP is not read: 1.0 while alive), crowns from towers down, Golden Knight button
  hand      the 4 cards read on screen + our next card from our own cycle (known after 4 plays)
  seen      enemy cards recognised so far
Then: play if the gate says so, the best card if affordable, at its best LEGAL tile (the engine's
check_deploy on a board with the real tower state, so pockets open when a tower falls), mapped back
to screen pixels. Search (R6) is not used yet: it needs the whole board rebuilt in the simulator.
"""
import math

import numpy as np
import royalesim
import torch

from . import layout as L
from .actions import ABILITY, WAIT, Action
from .cards import CARDS
from .model import RoyaleBrain
from .opponent import Opponent
from .policy import Policy
from .sim import H_TILES, OUR_DECK, TILE, W_TILES, Sim, to_px, to_tile

K_UNITS, UNIT_F, N_SCALARS = 48, 8, 21
GK_ABILITY = [0.0, 0.1, 0.70]           # engine record [ready, 0, cost 1, card 70, 0] -> features (see below)
OK = royalesim.DEPLOY_REASONS.index("OK")
SEEN_FRAMES = 3                         # an enemy track counts once seen in this many frames (no 1-frame ghosts)
SPELL_REACH_PX = {"poison": 3.5 * L.TILE_PX, "fireball": 2.5 * L.TILE_PX, "arrows": 4.0 * L.TILE_PX,
                  "zap": 2.5 * L.TILE_PX, "giant_snowball": 2.5 * L.TILE_PX}
LOG_PATH_PX = (1.5 * L.TILE_PX, 11 * L.TILE_PX)    # half-width, length: the Log rolls up its lane
FINISH_TOWER_BELOW = 0.3                # an enemy tower is a spell target only this low (a finish), else chip
SPELL_TOP_TILES = 12                    # spells: among the model's top tiles, the one hitting the most enemies
KEYS = {"our_left": 1, "our_right": 2, "enemy_left": 1, "enemy_right": 2}   # engine tower k (0 = king)


class ModelPolicy(Policy):
    name = "model"
    THINK_S, AFTER_PLAY_S = 0.5, 1.0

    def __init__(self, path, opponent, gate=0.0):
        from tools.build_dataset import Mapper
        torch.set_num_threads(2)
        ck = torch.load(path, map_location="cpu", weights_only=False)
        self.model = RoyaleBrain(ck["card_table"], d=ck["args"]["d"], layers=ck["args"]["layers"])
        self.model.load_state_dict(ck["model"])
        self.model.eval()
        self.sim, self.opponent, self.gate = Sim(), opponent, gate
        self.mapper = Mapper(self.sim)
        cat = self.sim.catalogue
        self.hp = {i: r[6] or 0 for i, r in enumerate(cat)}
        self.radius = {i: (r[4] or 0) / TILE for i, r in enumerate(cat)}
        self.flying = {i: bool(r[5]) for i, r in enumerate(cat)}
        self.median_hp = float(np.median([h for h in self.hp.values() if h]))
        self.ours = Opponent()                  # our own cycle -> our next card
        self.board = royalesim.Battle(card_names=None, slot_of_k=[[0, 1, 2], [0, 1, 2]])
        self.legal_cache = {}
        self.last_think = self.last_play = -math.inf
        self.last_exact, self.last_info = None, {}

    # ------------------------------------------------------------- cards
    def cid(self, key):
        """Our card key ('evo_witch', 'mega_knight', ...) -> engine catalogue id, or None."""
        if not key:
            return None
        try:
            return self.sim.card_id(key)[0]               # our keys: bot/sim.ENGINE_NAME ('ram' -> BattleRam)
        except KeyError:
            return self.mapper(key.removeprefix("evo_").removeprefix("hero_"))[0]   # other names, normalised

    # ------------------------------------------------------------- observation
    def _unit(self, mine, card, px, py, hp):
        cid = self.cid(card)
        tx, ty = to_tile(px, py)
        tx, ty = min(max(tx, 0.0), W_TILES), min(max(ty, 0.0), H_TILES)
        max_hp = self.hp.get(cid) or self.median_hp
        f = [float(mine), tx / W_TILES, ty / H_TILES, hp, math.log1p(max_hp) / 10,
             self.radius.get(cid, 0.5), float(self.flying.get(cid, False)), 0.0]
        return math.dist((tx, ty), (9.0, 3.0)), (cid if cid is not None else self.model.UNK), f

    def enemies(self, state, ctx):
        """Confirmed enemy units: seen in SEEN_FRAMES+ frames (a spell flash tracked for one frame
        drew a Log to an empty lane, run 20261115-114941)."""
        if ctx is not None and ctx.tracks:
            return [t for t in ctx.tracks if t.hits >= SEEN_FRAMES]
        return state.enemies

    def observe(self, state, ctx=None):
        bodies = [self._unit(False, u.card, u.x, u.y, u.hp) for u in self.enemies(state, ctx)]
        visible = {u.card for u in state.allies if u.card}
        bodies += [self._unit(True, u.card, u.x, u.y, u.hp) for u in state.allies]
        bodies += [self._unit(True, c, x, y, 1.0) for c, x, y in state.our_units if c not in visible]
        bodies.sort(key=lambda b: b[0])
        unit_ids = np.full(K_UNITS, self.model.PAD, np.int64)
        units = np.zeros((K_UNITS, UNIT_F), np.float32)
        for i, (_, cid, f) in enumerate(bodies[:K_UNITS]):
            unit_ids[i], units[i] = cid, f
        tw = state.towers or {}
        frac = lambda k: 1.0 if tw.get(k) is None else float(tw[k])
        towers = [1.0, frac("our_left"), frac("our_right"), 1.0, frac("enemy_left"), frac("enemy_right")]
        crowns_us = sum(frac(k) <= 0 for k in ("enemy_left", "enemy_right"))
        crowns_them = sum(frac(k) <= 0 for k in ("our_left", "our_right"))
        ability = [float(state.champion_ready), 0.0, GK_ABILITY[1], 0.0] + [0.0] * 4 + [1 / 3]
        scalars = np.array([state.t * 20 / 3600, state.elixir / 10, state.enemy_elixir / 10, *towers,
                            crowns_us / 3, crowns_them / 3, float(state.t > 180), *ability], np.float32)[:N_SCALARS]
        hand = [self.cid(c) for c in state.hand]
        nxt = self.ours.next_card()
        hand = np.array([c if c is not None else self.model.PAD for c in hand + [nxt]], np.int64)
        seen = [self.cid(c) for c in sorted(self.opponent.deck)]
        seen = [c for c in seen if c is not None][:8]
        seen = np.array(seen + [self.model.PAD] * (8 - len(seen)), np.int64)
        return unit_ids, units, scalars, hand, seen

    # ------------------------------------------------------------- legality
    def legal(self, card, towers):
        """576 bools: tiles where `card` may be played now, from the engine on a board with the
        real tower state (destroyed princess towers open the pocket)."""
        down = tuple(towers.get(k) is not None and towers[k] <= 0 for k in ("our_left", "our_right", "enemy_left", "enemy_right"))
        key = (card, down)
        if key not in self.legal_cache:
            cid = self.cid(card)
            deck = [cid] + [self.cid(k) for k in OUR_DECK if self.cid(k) != cid][:7]
            hp = lambda team_down: [1000, 0 if team_down[0] else 1000, 0 if team_down[1] else 1000]
            self.board.reset(seed=0, decks=[deck, deck], shuffle=0, start_tick=200, elixir_milli=[10000, 10000],
                             tower_hp=[hp(down[:2]), hp(down[2:])], spawns=[])
            self.legal_cache[key] = np.array([self.board.check_deploy(0, 0, int((c % W_TILES + 0.5) * TILE),
                                                                      int((c // W_TILES + 0.5) * TILE)) == OK
                                              for c in range(W_TILES * H_TILES)])
        return self.legal_cache[key]

    def spell_count(self, card, state, ctx):
        """576 ints: how many targets this spell would hit per tile: confirmed enemy units (+1 for an
        enemy princess tower below FINISH_TOWER_BELOW, for area spells). Safety check until search runs on
        the phone (it would see a Poison on our own Witch does nothing): r3 Poisoned our own tower
        at 0:14 with no enemy there (run 20261115-114941)."""
        foes = [(u.x, u.y) for u in self.enemies(state, ctx)
                if not (card == "log" and CARDS.get(u.card or "", {}).get("air"))]   # the Log rolls under flyers
        towers = []
        if card != "log":
            tw = state.towers or {}
            towers = [(L.TOWERS[k], tw.get(k) is not None and 0 < tw[k] < FINISH_TOWER_BELOW)
                      for k in ("enemy_left", "enemy_right") if tw.get(k) is None or tw[k] > 0]
        ok = np.zeros(W_TILES * H_TILES, int)
        for c in range(W_TILES * H_TILES):
            px, py = to_px(c % W_TILES + 0.5, c // W_TILES + 0.5)
            if card == "log":
                w, length = LOG_PATH_PX
                ok[c] = sum(abs(fx - px) <= w and py - length <= fy <= py + 0.5 * L.TILE_PX for fx, fy in foes)
            else:
                r = SPELL_REACH_PX.get(card, 2.5 * L.TILE_PX)
                units = sum(math.dist((fx, fy), (px, py)) <= r for fx, fy in foes)
                # a standing tower in reach is one more target when troops are hit too (owner: Poison on
                # troops + a healthy tower is good); on its own only when low enough to finish
                tower = sum(math.dist(xy, (px, py)) <= r and (units or low) for xy, low in towers)
                ok[c] = units + tower
        return ok

    # ------------------------------------------------------------- decide
    def choose(self, state, ctx):
        now = ctx.now
        if now - self.last_think < self.THINK_S or now - self.last_play < self.AFTER_PLAY_S:
            return WAIT, None, None
        self.last_think = now
        x = [torch.from_numpy(a)[None] for a in self.observe(state, ctx)]
        with torch.no_grad():
            out = self.model(*x)
        gate = out["gate"].item()
        self.last_info = {"gate": round(gate, 2)}
        if gate <= self.gate:
            return WAIT, None, None
        slot = int(out["card"][0].argmax())
        if slot == 4:                                     # the Golden Knight's ability button
            if state.champion_ready and state.elixir >= 1:
                self.last_play = now
                return ABILITY, None, None
            return WAIT, None, None
        card = state.hand[slot]
        if not card or CARDS.get(card.removeprefix("evo_"), CARDS.get(card, {})).get("cost", 99) > state.elixir:
            return WAIT, None, None                       # wants a card it can't afford yet: wait for it
        logits = out["tile"][0].numpy().copy()
        logits[~self.legal(card, state.towers or {})] = -np.inf
        wanted = float(np.max(logits))                    # its favourite legal tile, before the spell check
        if CARDS.get(card, {}).get("kind") == "spell":
            hits = self.spell_count(card, state, ctx)
            logits[hits == 0] = -np.inf
            top = [c for c in np.argsort(-logits)[:SPELL_TOP_TILES] if np.isfinite(logits[c])]
            if top:                                       # of the tiles it likes, the one hitting the most
                best = max(top, key=lambda c: (hits[c], logits[c]))   # (Log on 1 unit over a Witch + skeletons)
                logits[[c for c in range(len(logits)) if c != best]] = -np.inf
        cell = int(np.argmax(logits))
        if not np.isfinite(logits[cell]) or logits[cell] < wanted - math.log(4):
            return WAIT, None, None                       # what it wanted hits nothing; the rest it barely wanted
        px, py = to_px(cell % W_TILES + 0.5, cell // W_TILES + 0.5)
        self.last_exact = (int(px), int(py))
        self.last_play = now
        self.ours.played(self.cid(card))
        self.last_info.update(card=card, tile=[cell % W_TILES, cell // W_TILES])
        return Action("play", card, slot, int(px), int(py)), None, None

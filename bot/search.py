"""R6: decision-time search. Before a move, try the best few in the simulator and keep the one that
leads to the best position a few seconds later.

    candidates  WAIT + the model's top cards (by the card head), each at its top LEGAL tiles
    rollout     every candidate in its own copy of the battle (engine save/load: an exact copy),
                then HORIZON seconds with the model playing BOTH sides (greedy, every 0.5 s)
    score       "value": the model's value head (win probability) for us at the end; a finished
                match scores 1 / 0.5 / 0. "outcome": what actually happened (see outcome()).
    choose      the best score (WAIT on ties: it is listed first)
    timing      "search": WAIT is a candidate, search decides when AND what. "model": the model's
                gate decides WHEN (as without search); search only picks WHICH play.

Why it helps: the imitation model decides in one glance and is weakest at timing (play/wait 70%,
docs/experiments.md #27). Search checks "what happens if I play this now vs wait" instead of guessing.

The engine is deterministic and both rollout players are greedy, so one rollout per candidate gives
the same answer as many. By default the copy is exact, including the opponent's hand and elixir.
With `hidden` (Hidden below) the copy holds only what a player could know: the opponent's elixir as
COUNTED and their hand/queue as TRACKED through the cycle, unseen cards guessed (AGENTS.md, #33).
"""
import copy
import json
import re

import numpy as np
import royalesim
import torch

from bot.sim import TICKS_PER_S, TILE, W_TILES, Sim
from tools.build_dataset import ABILITY_SLOT, observe, own_frame

OK = royalesim.DEPLOY_REASONS.index("OK")
FIELDS = {f: i for i, f in enumerate(royalesim.ENTITY_FIELDS)}


class Policy:
    """The trained model as a player: batched observations -> greedy commands."""

    def __init__(self, model, cost, gate=0.0, rng=None):
        """rng: None = greedy (always the top card and tile). A numpy Generator = SAMPLE the card and
        the tile from the model's probabilities (a less predictable opponent, docs/experiments.md #29)."""
        self.model, self.cost, self.gate, self.rng = model, cost, gate, rng

    def forward(self, items, chosen_slot=None):
        """items: [(state, side, cards seen by side, the enemy's ElixirCount)]. One batched call."""
        obs = [observe(None, st, side, seen, count, FIELDS) for st, side, seen, count in items]
        m = self.model
        cols = [torch.from_numpy(np.stack([o[k] for o in obs]).astype(dt))
                for k, dt in enumerate((np.int64, np.float32, np.float32, np.int64, np.int64))]
        unit_ids, units, scalars, hand, seen = cols
        for v in (unit_ids, hand, seen):
            v[v < 0] = m.PAD
        with torch.no_grad():
            out = m(unit_ids, units, scalars, hand, seen, chosen_slot=chosen_slot)
        out["_items"] = items
        return out

    def affordable(self, pl, slot):
        if slot == ABILITY_SLOT:
            ready = [k for k, a in enumerate(pl.get("abilities") or []) if a[0] > 0 and a[2] * 1000 <= pl["elixir_milli"]]
            return ready[0] if ready else None
        card = pl["hand"][slot]
        return card if card is not None and card >= 0 and self.cost[card] * 1000 <= pl["elixir_milli"] else None

    def tiles(self, battle, side, slot, logits, n):
        """The n best LEGAL tiles for this slot, as engine commands."""
        out = []
        for cell in logits.argsort(descending=True).tolist():
            x, y = own_frame((cell % W_TILES) + 0.5, (cell // W_TILES) + 0.5, side)
            ex, ey = int(x * TILE), int(y * TILE)
            if battle.check_deploy(side, slot, ex, ey) == OK:
                out.append((side, slot, ex, ey))
                if len(out) == n:
                    break
        return out

    def greedy(self, battle, st, side, out, i):
        """Row i of a forward pass -> one command or None: play when gate > threshold, the best card
        if affordable (else wait for it), at its best legal tile."""
        if out["gate"][i].item() <= self.gate:
            return None
        slot = int(out["card"][i].argmax()) if self.rng is None else self._sample(out["card"][i])
        got = self.affordable(st["players"][side], slot)
        if got is None:
            return None
        if slot == ABILITY_SLOT:
            return (side, ABILITY_SLOT + got, 0, 0)
        if self.rng is None:
            best = self.tiles(battle, side, slot, out["tile"][i], 1)
            return best[0] if best else None
        # the tile head was conditioned on the argmax card: re-run it for the sampled one
        if slot != int(out["card"][i].argmax()):
            return None if out.get("_resampled") else self._resample(battle, st, side, out, i, slot)
        legal = self.tiles(battle, side, slot, out["tile"][i], 5)
        if not legal:
            return None
        logits = torch.stack([out["tile"][i][self._cell(c, side)] for c in legal])
        return legal[self._sample(logits)]

    def _sample(self, logits):
        p = torch.softmax(logits.float(), -1).numpy().astype(np.float64)
        return int(self.rng.choice(len(p), p=p / p.sum()))

    @staticmethod
    def _cell(c, side):
        x, y = own_frame(c[2] / TILE, c[3] / TILE, side)
        return int(y) * W_TILES + int(x)

    def _resample(self, battle, st, side, out, i, slot):
        o = self.forward([out["_items"][i]], chosen_slot=torch.tensor([slot]))
        o["_resampled"] = True
        legal = self.tiles(battle, side, slot, o["tile"][0], 5)
        if not legal:
            return None
        logits = torch.stack([o["tile"][0][self._cell(c, side)] for c in legal])
        return legal[self._sample(logits)]


def _load_edited(battle, d):
    """Load an edited snapshot. A snapshot stores its own state hash and load() refuses a mismatch;
    the refusal names the hash the engine rebuilt, so a deliberate edit loads on the second try (the
    engine still rebuilds and checks the whole state; we only confirm the edit was intended)."""
    try:
        battle.load(json.dumps(d).encode())
    except ValueError as e:
        m = re.search(r"rebuilt (0x[0-9a-f]+)", str(e))
        if not m:
            raise
        d["state_hash"] = int(m.group(1), 16)
        battle.load(json.dumps(d).encode())


class Hidden:
    """Rewrites a battle copy so the opponent holds only what we could know about them:
      elixir     their ElixirCount (5 + public regen - plays seen, capped at 10 at every moment)
      hand/queue Opponent.sample(): exact once all 8 cards are seen and no recent play was missed;
                 otherwise unknown slots get cards they haven't shown (uniform over the catalogue)
      deck       the guessed cards replace the unseen ones (level: their known cards' median; base form)
    Everything on the board stays as it is (the phone sees it)."""

    def __init__(self, sim):
        self.name = {i: row[0] for i, row in enumerate(sim.catalogue)}
        self.pool = list(self.name)
        self.internal = self._internal_ids(sim)
        self.base = royalesim.Battle(card_names=None, slot_of_k=[[0, 1, 2], [0, 1, 2]])

    @staticmethod
    def _internal_ids(sim):
        """Catalogue id -> the id the snapshot uses for hands and queues (they differ for some cards).
        With shuffle=0 the first deck card is the first hand card."""
        b, out = royalesim.Battle(card_names=None, slot_of_k=[[0, 1, 2], [0, 1, 2]]), {}
        fill = [sim.card_id(k)[0] for k in ("knight", "archers", "giant", "musketeer", "fireball", "arrows",
                                             "skeletons", "goblin_barrel", "valkyrie")]
        for cid in range(len(sim.catalogue)):
            deck = [cid] + [f for f in fill if f != cid][:7]
            try:
                b.reset(seed=0, decks=[deck, deck], shuffle=0, start_tick=0, elixir_milli=[5000, 5000],
                        tower_hp=None, spawns=[])
            except Exception:
                continue                                  # not a deck card on its own
            out[cid] = json.loads(b.save())["players"][0]["hand"][0]
        return out

    def snapshot(self, battle, opp, tracker, count, tick, rng):
        d = json.loads(battle.save())
        hand, queue = tracker.sample(rng, [c for c in self.pool if c in self.internal])
        names = [self.name[c] for c in hand + queue]
        deck, levels, forms = d["decks"][opp], d["deck_levels"][opp], d["forms"][opp]
        guesses = [n for n in names if n not in deck]
        level = sorted(levels)[len(levels) // 2]
        for i, n in enumerate(deck):
            if n not in names:                            # a card we haven't seen: replaced by a guess
                deck[i], levels[i], forms[i] = guesses.pop(), level, 0
        p = d["players"][opp]
        p["hand"] = [self.internal[c] for c in hand]
        p["queue"] = [self.internal[c] for c in queue]
        p["mana"] = int(count.value(tick) * d["mana_unit"] / 1000)
        _load_edited(self.base, d)
        return self.base.save()


class Search:
    TOWER_W, MATERIAL_W, END_W = 1.0, 0.1, 3.0       # outcome(): 10 elixir of material ~ one tower

    def __init__(self, policy, cards=2, tiles=2, horizon_s=6.0, think=10, score="value", timing="search"):
        assert score in ("value", "outcome") and timing in ("search", "model")
        self.p, self.cards, self.n_tiles, self.score, self.timing = policy, cards, tiles, score, timing
        self.count = {i: (row[3] or 1) for i, row in enumerate(Sim().catalogue)}
        self.horizon, self.think = int(horizon_s * TICKS_PER_S), think
        self.clones = []
        self.calls = self.ms = 0.0
        self.fallbacks = 0

    def candidates(self, battle, st, side, seen, count, wait=True):
        pl = st["players"][side]
        out = self.p.forward([(st, side, seen, count)] * 4, chosen_slot=torch.arange(4))
        cands, n = [None] if wait else [], 0
        for slot in out["card"][0].argsort(descending=True).tolist():
            if n == self.cards:
                break
            got = self.p.affordable(pl, slot)
            if got is None:
                continue
            if slot == ABILITY_SLOT:
                cands.append((side, ABILITY_SLOT + got, 0, 0))
            else:
                cands += self.p.tiles(battle, side, slot, out["tile"][slot], self.n_tiles)
            n += 1
        return cands

    def choose(self, battle, st, side, seen, counts, hidden=None, decided=False):
        """battle: the live royalesim.Battle (not modified). seen: {side: set} cards each side saw
        the other play; counts: [ElixirCount, ElixirCount], each side's elixir as the other counts it.
        hidden: None (the copy is exact) or (Hidden, the opponent's Opponent tracker, rng): the copy
        then holds only what we could know about the opponent. decided: the caller's gate already
        said play now (the phone: bot/live_model.py); only pick which play."""
        if decided:
            cands = self.candidates(battle, st, side, seen[side], counts[1 - side], wait=False)
        elif self.timing == "model":
            out = self.p.forward([(st, side, seen[side], counts[1 - side])])
            if self.p.greedy(battle, st, side, out, 0) is None:      # the model says: not now
                return None
            cands = self.candidates(battle, st, side, seen[side], counts[1 - side], wait=False)
        else:
            cands = self.candidates(battle, st, side, seen[side], counts[1 - side])
        if len(cands) <= 1:
            return cands[0] if cands else None
        if hidden:
            h, tracker, rng = hidden
            snap = h.snapshot(battle, 1 - side, tracker, counts[1 - side], st["tick"], rng)
        else:
            snap = battle.save()
        while len(self.clones) < len(cands):
            self.clones.append(royalesim.Battle(card_names=None, slot_of_k=[[0, 1, 2], [0, 1, 2]]))
        runs = []
        for c, b in zip(cands, self.clones):
            b.load(snap)
            r = {"b": b, "seen": {0: set(seen[0]), 1: set(seen[1])}, "count": copy.deepcopy(counts), "ok": True}
            hand = [p["hand"] for p in st["players"]]
            res = b.step([c] if c else [], 1)
            if c:
                r["ok"] = res[0][1] == OK
                self._note(r, c, res[0], hand)
            runs.append(r)
        for _ in range(0, self.horizon, self.think):
            live = [r for r in runs if r["ok"] and not r.get("over")]
            if not live:
                break
            sts = [json.loads(r["b"].state_json()) for r in live]
            items = [(s, sd, r["seen"][sd], r["count"][1 - sd]) for r, s in zip(live, sts) for sd in (0, 1)]
            out = self.p.forward(items)
            for j, (r, s) in enumerate(zip(live, sts)):
                if s["game_over"]:
                    r["over"] = s
                    continue
                cmds = [c for sd in (0, 1) if (c := self.p.greedy(r["b"], s, sd, out, 2 * j + sd))]
                hand = [p["hand"] for p in s["players"]]
                res = r["b"].step(cmds, self.think)
                for c, rr in zip(cmds, res):
                    self._note(r, c, rr, hand)
        scores = []
        ends = [(r, r.get("over") or json.loads(r["b"].state_json())) for r in runs if r["ok"]]
        if self.score == "outcome":
            it = iter(ends)
            scores = [self.outcome(st, next(it)[1], side) if r["ok"] else -1e9 for r in runs]
            return cands[int(np.argmax(scores))]
        values = self.p.forward([(s, side, r["seen"][side], r["count"][1 - side]) for r, s in ends])["value"] if ends else []
        k = 0
        for r in runs:
            if not r["ok"]:
                scores.append(-1.0)
                continue
            s = ends[k][1]
            if s["game_over"]:
                scores.append(1.0 if s["winner"] == side else 0.0 if s["winner"] in (0, 1) else 0.5)
            else:
                scores.append(torch.sigmoid(values[k]).item())
            k += 1
        return cands[int(np.argmax(scores))]

    def material(self, st, team):
        """Elixir in the bank + the elixir worth of the team's living units (card cost shared by the
        card's units, times the HP fraction left)."""
        F, total = FIELDS, st["players"][team]["elixir_milli"] / 1000
        for e in st["entities"]:
            if e[F["team"]] != team or e[F["tower_slot"]] >= 0 or e[F["hp"]] <= 0:
                continue
            cid = e[F["card_id"]]
            total += self.p.cost.get(cid, 0) / self.count.get(cid, 1) * e[F["hp"]] / max(1, e[F["max_hp"]])
        return total

    def outcome(self, st0, st1, side):
        """What happened between st0 and st1, for `side`: tower HP dealt - taken (1 = a whole tower)
        + MATERIAL_W x the material lead at the end; a finished match is +-END_W (draw 0)."""
        if st1["game_over"]:
            return self.END_W if st1["winner"] == side else -self.END_W if st1["winner"] in (0, 1) else 0.0
        lost = lambda team: sum((a - b) / max(1, m) for a, b, m in zip(
            st0["players"][team]["tower_hp"], st1["players"][team]["tower_hp"], st1["players"][team]["tower_max_hp"]))
        return (self.TOWER_W * (lost(1 - side) - lost(side))
                + self.MATERIAL_W * (self.material(st1, side) - self.material(st1, 1 - side)))

    def _note(self, r, c, res, hand):
        """Public bookkeeping after an accepted play: the other side saw the card, elixir spent."""
        if res[1] != OK:
            return
        side, slot = c[0], c[1]
        if slot < ABILITY_SLOT:
            card = hand[side][slot]
            r["seen"][1 - side].add(card)
            r["count"][side].spend(res[2], 1000 * self.p.cost[card])
        else:
            r["count"][side].spend(res[2], 1000)

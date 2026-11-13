"""R6: decision-time search. Before a move, try the best few in the simulator and keep the one that
leads to the best position a few seconds later.

    candidates  WAIT + the model's top cards (by the card head), each at its top LEGAL tiles
    rollout     every candidate in its own copy of the battle (engine save/load: an exact copy),
                then HORIZON seconds with the model playing BOTH sides (greedy, every 0.5 s)
    score       the model's value head (win probability) for us at the end; a finished match
                scores 1 / 0.5 / 0
    choose      the best score (WAIT on ties: it is listed first)

Why it helps: the imitation model decides in one glance and is weakest at timing (play/wait 70%,
docs/experiments.md #27). Search checks "what happens if I play this now vs wait" instead of guessing.

The engine is deterministic and both rollout players are greedy, so one rollout per candidate gives
the same answer as many. The copy is exact, including the opponent's hand and elixir: in the
simulator the search knows what the phone could not (docs/experiments.md #29).
"""
import json

import numpy as np
import royalesim
import torch

from bot.sim import TICKS_PER_S, TILE, W_TILES
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
        """items: [(state, side, cards seen by side, elixir the enemy spent)]. One batched call."""
        obs = [observe(None, st, side, seen, spent, FIELDS) for st, side, seen, spent in items]
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


class Search:
    def __init__(self, policy, cards=2, tiles=2, horizon_s=6.0, think=10):
        self.p, self.cards, self.n_tiles = policy, cards, tiles
        self.horizon, self.think = int(horizon_s * TICKS_PER_S), think
        self.clones = []
        self.calls = self.ms = 0.0
        self.fallbacks = 0

    def candidates(self, battle, st, side, seen, spent):
        pl = st["players"][side]
        out = self.p.forward([(st, side, seen, spent)] * 4, chosen_slot=torch.arange(4))
        cands, n = [None], 0
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

    def choose(self, battle, st, side, seen, spent_by):
        """battle: the live royalesim.Battle (not modified). seen: {side: set} cards each side saw
        the other play; spent_by: [milli, milli] elixir each side publicly spent."""
        cands = self.candidates(battle, st, side, seen[side], spent_by[1 - side])
        if len(cands) == 1:
            return None
        snap = battle.save()
        while len(self.clones) < len(cands):
            self.clones.append(royalesim.Battle(card_names=None, slot_of_k=[[0, 1, 2], [0, 1, 2]]))
        runs = []
        for c, b in zip(cands, self.clones):
            b.load(snap)
            r = {"b": b, "seen": {0: set(seen[0]), 1: set(seen[1])}, "spent": list(spent_by), "ok": True}
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
            items = [(s, sd, r["seen"][sd], r["spent"][1 - sd]) for r, s in zip(live, sts) for sd in (0, 1)]
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
        values = self.p.forward([(s, side, r["seen"][side], r["spent"][1 - side]) for r, s in ends])["value"] if ends else []
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

    def _note(self, r, c, res, hand):
        """Public bookkeeping after an accepted play: the other side saw the card, elixir spent."""
        if res[1] != OK:
            return
        side, slot = c[0], c[1]
        if slot < ABILITY_SLOT:
            card = hand[side][slot]
            r["seen"][1 - side].add(card)
            r["spent"][side] += 1000 * self.p.cost[card]
        else:
            r["spent"][side] += 1000

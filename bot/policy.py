"""Decision makers. Every policy answers the same question: given the state and the candidate
actions, how good is each one? `choose` plays the best.

    RulePolicy     today's hand-written brain, expressed as scores (the prior / baseline)
    (next)         LearnedPolicy: a model trained on logged outcomes and human replays
    (next)         BlendPolicy: learned score + rule prior, with exploration in practice matches

Rules see the live tracker objects (they need ETA/prediction helpers); learned models only ever see
the serializable State, so whatever they learn from logs is exactly what they get live.
"""
import json
import random
from dataclasses import dataclass, field

import numpy as np

from .actions import ABILITY, WAIT, Action, candidates, grid_for, snap
from .cards import CARDS
from . import placements
from .features import encode_many


@dataclass
class Context:
    """Live objects the rule brain needs, alongside the State."""
    tracks: list = field(default_factory=list)
    allies: list = field(default_factory=list)
    new_plays: list = field(default_factory=list)
    gk_estimate: tuple | None = None
    own_last: dict = field(default_factory=dict)
    supports: list = field(default_factory=list)
    now: float = 0.0


class Policy:
    name = "base"

    def score(self, state, cands, ctx):
        """One score per candidate; higher = better."""
        raise NotImplementedError

    def choose(self, state, ctx):
        """(action, candidates, scores). Returns WAIT when nothing beats waiting."""
        cands = candidates(state)
        scores = self.score(state, cands, ctx)
        best = max(range(len(cands)), key=lambda i: scores[i])
        return cands[best], cands, scores


class RulePolicy(Policy):
    """The rule brain as a policy: its chosen move scores 1, everything else 0 (WAIT 0.5 when the
    rules play nothing). Its exact placement is kept for execution; the grid snap is the label."""
    name = "rules"

    def __init__(self, brain):
        self.brain = brain
        self.last_exact = None          # exact (x, y) the rules asked for, for execution

    def _rule_action(self, state, ctx):
        act = self.brain.decide(state.elixir, state.hand, ctx.tracks, allies=ctx.allies,
                                new_plays=ctx.new_plays, enemy_elixir=state.enemy_elixir,
                                champion_ready=state.champion_ready, towers=state.towers,
                                gk_estimate=ctx.gk_estimate, own_last=ctx.own_last,
                                supports=ctx.supports, now=ctx.now)
        if act is None:
            return None, None
        card, slot, xy = act
        if card == "gk_ability":
            return ABILITY, None
        return snap(card, slot, xy), xy

    def score(self, state, cands, ctx):
        rule, exact = self._rule_action(state, ctx)
        self.last_exact = exact
        return [1.0 if c == rule else (0.5 if c == WAIT and rule is None else 0.0) for c in cands]

    def choose(self, state, ctx):
        rule, exact = self._rule_action(state, ctx)
        self.last_exact = exact
        return (rule or WAIT), None, None     # rules don't need the full candidate list live


Q_SCALE = 0.5          # a predicted outcome gap of 500 tower HP = 1 point of prior
NO_VETO_AT = 9.0       # elixir at which WAIT can't override a rule move


def is_spell(card):
    return CARDS.get(card, {}).get("kind") == "spell"


class BlendPolicy(Policy):
    """Rule prior + learned outcome model, with optional exploration.

    At each decision point it builds a shortlist: WAIT, the rule move, the rule card on the
    neighbouring cells, and the other playable cards on the rule's cell. Score = prior + beta * z(Q),
    where Q is the model's predicted outcome. beta grows with the number of plays the model was
    trained on (BETA_FULL_AT), so a model trained on one match can only nudge, not override.
    explore: probability of playing a random shortlist move instead (practice matches only), so
    the data contains alternatives, not just what the rules would do.
    """
    name = "blend"
    BETA_MAX = 1.5
    BETA_FULL_AT = 400          # trained plays for full weight
    DECIDE_EVERY = 0.5          # seconds between checks while the rules wait
    EXPLORE_COOLDOWN_S = 10.0   # at most one exploration roll per 10s

    def __init__(self, brain, model_path, meta, explore=0.0, rng=None):
        import lightgbm as lgb          # optional dependency: only needed for the blended policy
        self.rule = RulePolicy(brain)
        self.brain = brain
        self.model = lgb.Booster(model_file=str(model_path))
        self.beta = self.BETA_MAX * min(1.0, meta.get("n_plays", 0) / self.BETA_FULL_AT)
        self.explore = explore
        self.rng = rng or random.Random()
        self.last_exact = None
        self.last_explored = False
        self._last_check = -1e9
        self._last_explore = -1e9

    def _learned_spots(self, state):
        """Each playable troop/building at the spots humans used in this situation."""
        sit = placements.situation(state.to_dict())
        out = []
        for slot, card in enumerate(state.hand):
            if card and not is_spell(card) and CARDS.get(card, {}).get("cost", 99) <= state.elixir:
                out += [Action("play", card, slot, x, y) for x, y, _ in placements.spots(card, sit)]
        return out

    def _shortlist(self, state, rule):
        out = [WAIT]
        pressure = any(u.eta_river <= 3.0 for u in state.enemies) or state.elixir >= 9.0
        if rule is None or rule.kind != "play":
            out += ([rule] if rule else [])
            return out + (self._learned_spots(state) if pressure else [])
        out.append(rule)
        out += [c for c in self._learned_spots(state) if c not in out]
        if is_spell(rule.card):
            return out                     # a spell goes to its value-computed spot or not at all
        cells = set(grid_for(rule.card))
        step = 54
        for dx in (-step, 0, step):
            for dy in (-step, 0, step):
                if (dx or dy) and (rule.x + dx, rule.y + dy) in cells:
                    out.append(Action("play", rule.card, rule.slot, rule.x + dx, rule.y + dy))
        for slot, card in enumerate(state.hand):
            # other troops at the rule's spot; never spells (run 040133: random spells on grid
            # cells at the screen edge, on targets the value check had rejected)
            if card and card != rule.card and not is_spell(card) and CARDS.get(card, {}).get("cost", 99) <= state.elixir:
                cell = min(grid_for(card), key=lambda g: (g[0] - rule.x) ** 2 + (g[1] - rule.y) ** 2)
                out.append(Action("play", card, slot, cell[0], cell[1]))
        return out

    def choose(self, state, ctx):
        snap = self.brain.snapshot()
        rule, exact = self.rule._rule_action(state, ctx)
        if rule is None and ctx.now - self._last_check < self.DECIDE_EVERY:
            self.last_exact, self.last_explored = None, False
            return WAIT, None, None
        self._last_check = ctx.now
        cands = self._shortlist(state, rule)
        if len(cands) == 1:
            self.last_exact, self.last_explored = None, False
            return WAIT, cands, [0.0]
        q = self.model.predict(encode_many(state.to_dict(), [c.to_dict() for c in cands]))
        prior = np.array([1.0 if c == rule else (1.0 if c == WAIT and rule is None else
                          (0.5 if c == WAIT else 0.6)) for c in cands])
        # Raw predicted outcome differences (in 1000s of tower HP), not z-scores: z-scoring blew tiny
        # noisy differences up to +-2 and let the model flip every decision (run 055851).
        scores = prior + self.beta * (q - q.max()) / Q_SCALE
        if rule is not None and rule.kind != "wait" and state.elixir >= NO_VETO_AT:
            scores[cands.index(WAIT)] = -np.inf          # at a full bar the model may re-aim, not veto
        best = int(np.argmax(scores))
        self.last_explored = False
        # Explore: one roll per proposed move, then a cooldown. Rolling every frame (run 040133)
        # turned 15% into ~100%: an explored WAIT made the rules propose again next frame, re-roll...
        calm = not any(u.eta_river <= 1.0 for u in state.enemies)   # no experiments under pressure
        alternatives = [i for i, c in enumerate(cands) if c.kind == "play" and c != rule]
        if (self.explore and calm and alternatives and rule is not None and not is_spell(rule.card)
                and ctx.now - self._last_explore >= self.EXPLORE_COOLDOWN_S):
            self._last_explore = ctx.now                         # rolled for this move: no re-roll
            if self.rng.random() < self.explore:
                best = self.rng.choice(alternatives)
                self.last_explored = True
        chosen = cands[best]
        if chosen == rule:
            self.last_exact = exact                  # rules keep their exact pixel spot
        else:
            self.brain.restore(snap)                 # undo the rules' bookkeeping for their proposal
            self.last_exact = None
            if chosen.kind != "wait":
                self.brain.commit(chosen.card if chosen.kind == "play" else "gk_ability", state.elixir, ctx.now)
        return chosen, cands, list(scores)


class DecisionLog:
    """decisions.jsonl: one line per decision point = full State + what was played + by which policy.

    Decision points: every action, plus the state every WAIT_EVERY seconds while waiting, so the data
    also shows when *not* playing was the choice. Candidates aren't stored: they are rebuilt
    deterministically from the State (actions.candidates) when training.
    """
    WAIT_EVERY = 0.5

    def __init__(self, run_dir):
        self._json = json
        self.f = open(run_dir / "decisions.jsonl", "a")
        self._last_wait = -1e9

    def record(self, state, action: Action, policy_name, now, explored=False):
        if action.kind == "wait":
            if now - self._last_wait < self.WAIT_EVERY:
                return
            self._last_wait = now
        self.f.write(self._json.dumps({"state": state.to_dict(), "action": action.to_dict(),
                                       "policy": policy_name, "explored": explored}) + "\n")

    def close(self):
        self.f.close()

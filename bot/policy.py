"""Decision makers. Every policy answers the same question: given the state and the candidate
actions, how good is each one? `choose` plays the best.

    RulePolicy     today's hand-written brain, expressed as scores (the prior / baseline)
    (next)         LearnedPolicy: a model trained on logged outcomes and human replays
    (next)         BlendPolicy: learned score + rule prior, with exploration in practice matches

Rules see the live tracker objects (they need ETA/prediction helpers); learned models only ever see
the serializable State, so whatever they learn from logs is exactly what they get live.
"""
import json
from dataclasses import dataclass, field

from .actions import ABILITY, WAIT, Action, candidates, snap


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

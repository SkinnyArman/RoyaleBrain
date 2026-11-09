"""The game state at one moment: everything the bot knows, in one serializable record.

This is the input to every policy (rules now, learned models later) and what gets logged at each
decision point. Keep it complete and stable: training data is only as good as this record.
"""
from dataclasses import asdict, dataclass, field

from . import layout as L


@dataclass
class Unit:
    id: int
    team: str                  # "enemy" / "ally"
    card: str | None           # recognised card, or our own label
    x: float
    y: float
    vx: float
    vy: float                  # px/s, + = moving down the screen (toward us)
    hp: float                  # fraction of the unit's own HP
    w: float                   # bar/badge width (rough size signal)
    lane: str
    eta_river: float           # seconds until it reaches the river line (enemies); inf if not coming

    @classmethod
    def from_track(cls, t, team):
        eta = t.eta(L.RIVER_Y)
        return cls(t.id, team, t.card if team == "enemy" else t.label, round(t.x, 1), round(t.y, 1),
                   round(t.vx, 1), round(t.vy, 1), t.hp, round(t.w, 1), t.lane,
                   round(eta, 2) if eta != float("inf") else 99.0)


@dataclass
class State:
    t: float                               # seconds since the match started
    elixir: float
    regen: float                           # elixir/s we observe (doubles in double elixir)
    enemy_elixir: float                    # estimate
    hand: list                             # 4 card names or None
    enemy_hand: list                       # cards they can hold (cycle estimate)
    enemy_deck: list                       # cards seen / told
    enemies: list = field(default_factory=list)   # [Unit]
    allies: list = field(default_factory=list)    # [Unit]
    towers: dict = field(default_factory=dict)    # name -> HP fraction (None = unknown)
    champion_ready: bool = False
    own_last: dict = field(default_factory=dict)  # card -> [x, y, seconds ago]
    gk_estimate: list | None = None
    responses: dict = field(default_factory=dict)  # our card -> P(they answered it with a swarm)
    our_units: list = field(default_factory=list)  # [card, x, y]: our troops now (seen or estimated)

    def to_dict(self):
        return asdict(self)

    @property
    def double_elixir(self):
        return self.regen > 0.5


def build_state(t, elixir, enemy_elixir, hand, opponent, tracker, ally_tracker, towers,
                champion_ready, own, now):
    gk = own.estimate("golden_knight", now)
    return State(
        t=round(t, 2), elixir=elixir, regen=round(enemy_elixir.rate, 3),
        enemy_elixir=round(enemy_elixir.value, 2), hand=list(hand),
        enemy_hand=sorted(opponent.hand_estimate()), enemy_deck=sorted(opponent.deck),
        enemies=[Unit.from_track(tr, "enemy") for tr in tracker.tracks],
        allies=[Unit.from_track(tr, "ally") for tr in ally_tracker.tracks],
        towers=dict(towers), champion_ready=champion_ready,
        own_last={c: [round(x), round(y), round(now - t0, 2)] for c, (x, y, t0) in own.last.items()},
        gk_estimate=[round(gk[0]), round(gk[1])] if gk else None,
        responses={c: round(opponent.response_prob(c, "swarm"), 2) for c in ("hog", "ram")},
        our_units=_our_units(own, ally_tracker, now),
    )


def _our_units(own, ally_tracker, now):
    """Our troops on the field: visible (labelled) ones, plus dead-reckoned supports and our last
    win condition while it should still be alive."""
    out = [[a.label, round(a.x), round(a.y)] for a in ally_tracker.tracks if a.label]
    seen = {u[0] for u in out}
    for card, _, (x, y) in own.supports(now):
        if card not in seen:
            out.append([card, round(x), round(y)])
    for card in ("hog", "ram"):
        pos = own.estimate(card, now, max_age=8.0)
        if pos and card not in seen:
            out.append([card, round(pos[0]), round(pos[1])])
    return out

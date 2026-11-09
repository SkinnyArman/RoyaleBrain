"""Opponent elixir estimate: the core economic signal.

The opponent's elixir is never shown. We start them at 5 (same as us), regenerate at the same
rate we observe on our own bar (so double/triple elixir is picked up automatically, no timers),
and subtract the cost of every enemy play we detect.

Limitations (v1, see docs/game-knowledge.md):
- Enemy card identity is unknown until we have a detector, so a play costs UNKNOWN_COST.
- Spells leave no health bar, so they are not seen yet.
"""

BASE_RATE = 1 / 2.8      # elixir per second, single elixir (unverified, refined from our own bar)
UNKNOWN_COST = 3.5       # rough average card cost until enemy cards can be identified
START = 5.0


class EnemyElixir:
    def __init__(self):
        self.value = START
        self.rate = BASE_RATE
        self._t = None
        self._ours = None
        self.plays = []          # (time, cost, note)

    def update(self, now, our_elixir, we_spent=0.0):
        """Call once per frame with our own elixir reading and what we just spent."""
        if self._t is not None:
            dt = now - self._t
            # Learn the current regen rate from our bar while it is filling and we didn't spend.
            if dt > 0 and self._ours is not None and we_spent == 0 and 0.5 < our_elixir < 9.5:
                observed = (our_elixir - self._ours) / dt
                if 0.2 < observed < 1.5:   # ignore noise and spends
                    self.rate = 0.8 * self.rate + 0.2 * observed
            self.value = min(10.0, self.value + self.rate * dt)
        self._t, self._ours = now, our_elixir

    def enemy_played(self, now, cost=UNKNOWN_COST, note=""):
        self.value = max(0.0, self.value - cost)
        self.plays.append((now, cost, note))

    def advantage(self, our_elixir):
        """Positive = we have more elixir than they do."""
        return our_elixir - self.value

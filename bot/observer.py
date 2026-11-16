"""Watch the owner play: detect their plays from the screen and log them as training data.

The bot never taps in this mode. A play = a card leaves the hand AND elixir drops by about its
cost. Its spot = the pink cost drop the game draws above a fresh placement (vision.cost_drops) +
DROP_OFFSET. Each play is logged like the bot's own decisions, with policy "human", using the state
from just before the play, so the outcome labels and the model treat it exactly like ours.
"""
from collections import deque

from . import vision
from .actions import Action, snap
from .cards import CARDS


def coverage(detector):
    """Self-check: share of the elixir we saw spent that detected plays account for (1.0 = all)."""
    return detector.spent_detected / detector.spent_seen if detector.spent_seen else 1.0


class HumanPlayDetector:
    LOOKBACK_S = 1.2           # elixir before the play = max over this window
    FIND_DROP_S = 1.5          # look for the new cost drop this long after the card left the hand
    PEAK_BEFORE_S = 0.6        # elixir before the play = max over this window before the slot emptied
    CONFIRM_S = 1.0            # the elixir drop must follow the empty slot within this
    DEDUPE_S = 1.5             # the same card can't be played twice within this

    def __init__(self):
        self.prev_hand = None
        self.elixir_hist = deque()           # (t, elixir)
        self.pending = []                    # (card, slot, t, state_before, drops_before)
        self.last_state = None
        self.last_drops = []
        self.candidates = []                 # [card, slot, t, elixir peak, state, drops] awaiting the drop
        self.confirmed = []                  # every (card, t) confirmed as a play this match
        self.recent = []                     # (card, t) of detected plays
        self.spent_seen = 0.0                # elixir drops we saw (self-check)
        self.spent_detected = 0.0            # cost of detected plays (self-check)
        self._prev_elixir = None

    def update(self, now, img, hand, elixir, state):
        """Feed one frame. Returns [(state_before, Action)] for plays whose spot was found."""
        self.elixir_hist.append((now, elixir))
        while self.elixir_hist and now - self.elixir_hist[0][0] > self.LOOKBACK_S:
            self.elixir_hist.popleft()
        drops = vision.cost_drops(img)
        out = []
        if self._prev_elixir is not None and elixir < self._prev_elixir - 0.6:
            self.spent_seen += self._prev_elixir - elixir
        self._prev_elixir = elixir
        if self.prev_hand is not None:
            # A play = a slot goes EMPTY; the elixir bar drops 0.1-0.4s later (measured on the owner's
            # 5 ladder matches, 2026-11-09). Checking the drop at the same instant missed most plays.
            recent_peak = max(e for t, e in self.elixir_hist if now - t <= self.PEAK_BEFORE_S)
            for slot, (old, new) in enumerate(zip(self.prev_hand, hand)):
                if old and new is None and not any(c[1] == slot for c in self.candidates):
                    self.candidates.append([old, slot, now, recent_peak, self.last_state or state,
                                            list(self.last_drops)])
            still = []
            for card, slot, t0, peak, st, before in self.candidates:
                cost = CARDS.get(card, {}).get("cost", 99)
                dup = any(c == card and t0 - t < self.DEDUPE_S for c, t in self.recent)
                if not dup and peak - elixir >= cost - 0.8:          # confirmed: the elixir went
                    self.pending.append((card, slot, t0, st, before))
                    self.recent = [r for r in self.recent if t0 - r[1] < 5] + [(card, t0)]
                    self.confirmed.append((card, t0))
                elif now - t0 <= self.CONFIRM_S and not dup:
                    still.append([card, slot, t0, peak, st, before])
            self.candidates = still
        keep = []
        for card, slot, t, st, before in self.pending:
            fresh = [d for d in drops if all(abs(d[0] - b[0]) + abs(d[1] - b[1]) > 40 for b in before)]
            if fresh:
                dx, dy = vision.DROP_OFFSET
                x, y = fresh[0][0] + dx, fresh[0][1] + dy
                out.append((st, snap(card, slot, (x, y)), (x, y)))
                self.spent_detected += CARDS.get(card, {}).get("cost", 0)
            elif now - t < self.FIND_DROP_S:
                keep.append((card, slot, t, st, before))
        self.pending = keep
        self.prev_hand, self.last_state, self.last_drops = list(hand), state, drops
        return out

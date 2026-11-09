"""Rule-based decisions on tracked units.

Per frame inputs: our elixir, hand, enemy tracks, our own (labelled) tracks, new enemy plays,
the opponent's estimated elixir, the opponent model, princess tower HP, champion button state.
Output: one action or None:
  (card, slot, (x, y))           play a card
  ("gk_ability", None, None)      press the Golden Knight's ability

Principles (docs/game-knowledge.md):
- Respond to *arrival time*, not position (LEAD_S before the push reaches the river).
- Elixir economy: cheapest answer that fits; attack from a full bar or when they are low.
- A big deploy at their back is an elixir signal: punish the other lane.
- Never place a troop where one known enemy spell can hit it and our tower together.
- Spell-finish a low tower only when the timing is safe and the elixir allows it.
"""
import copy
import math
import time

from . import layout as L
from .cards import CARDS, prop
from .profiles import profile
from .spells import best_spell, worth_it

COST = {"hog": 4, "ram": 4, "golden_knight": 4, "witch": 5,
        "tombstone": 3, "minions": 3, "poison": 4, "log": 2}
GK_ABILITY_COST = 1
ACTION_GAP_S = 0.8    # min time between our plays (hand/elixir UI lags a few frames behind taps)

# Ram defends too (owner): enemies hit it on the way, its 2 Barbarians fight, and if it survives it
# counter-attacks the tower.
SINGLE_DEFENSE = ["tombstone", "ram", "minions", "golden_knight", "witch"]
# Spells are never placed by default: they go through spells.best_spell + a value check.
SUPPORT = ["golden_knight", "minions", "witch"]     # troops that go WITH the Hog/Ram (owner: no dry attacks)
WIN_CONDITIONS = ["hog", "ram"]
PUSH_JOIN_PX = 330     # our support this close to its bridge = time to add the win condition
RESPONSE_PREPARE = 0.5  # they answered this attack with a swarm this often: keep the spell ready
RESPONSE_PRECAST = 0.75 # this often: cast it early where their answer will be
PRECAST_AFTER_S = 2.0   # Hog reaches their side ~2s after the bridge
URGENT = 3.0           # lane urgency (threat / seconds to arrival) that still beats joining a push
GROWTH_REDEFEND = 1.5  # defend a lane again inside the cooldown if its threat grew this much
SURVIVOR_PX = 300      # our troops this close to a bridge, walking up = a counter-push to join
SWARM_DEFENSE = ["golden_knight", "witch", "tombstone"]       # GK dash chains through swarms
SWARM_SIZE = 3        # this many enemies close together = a swarm
SWARM_PX = 260
LEAD_S = 2.0          # answer when the push is this many seconds from the river (deploy ~1s + walk)
PUNISH_BELOW = None   # attack when the opponent's estimated elixir is at or below this. OFF: the estimate
                      # isn't trustworthy until enemy cards are recognised (run 2026-11-08-235339)
DEFENSE_RESERVE = 4   # never attack if it leaves less than this for the next defence (same run: we
                      # attacked down to 0 and had nothing when the real push came)
TOWER_HANDLES_HP = 0.4  # a lone enemy below this HP fraction is left to the tower
LEAK_AT = 9.0         # at or above this, playing *something* beats wasting regen
FINISH_HP = 0.35      # a damaged support unit at or below this is worth a cheap spell (owner: "hit the
                      # low-HP backup first", e.g. a low Musketeer behind fresh Barbarians)
SPLASH_REACH_PX = 320 # keep swarm/air-swarm cards this far from known splash units (owner)
FRAGILE = {"minions"} # our cards that one splash hit wipes out
TOWER_RANGE_PX = 7.5 * 54     # princess tower range (unverified, 7.5 tiles)
TOWER_HALF_PX = 1.5 * 54      # half the tower's footprint
EVO_CYCLES = {"ram": 2, "witch": 1}   # owner: Evo Ram needs 2 cycles, Evo Witch 1
TANK_BAR_W = 110      # bar width that suggests a big unit (unverified: calibrate from runs/ logs)
GK_CHAIN_PX = 330     # enemies this close to each other can be chained by the dash (~5.5 tiles, unverified)
GK_REACH_PX = 330     # the first dash target must be this close to our GK (unverified)

# Spell finish (unverified level-11 crown-tower damage: Poison ~27.5/s x 8s, Log ~58).
PRINCESS_MAX_HP = 4032        # ENEMY princess tower max HP; 4032 = level 14 (practice vs Devil's deck); set per match with --tower-hp
SPELL_TOWER_DMG = {"log": 58, "poison": 220}
FINISH_SAFE_ETA = 3.0         # no enemy may reach the river within this many seconds
FINISH_KEEP = 2               # elixir we must keep after the finish, unless they are low too


def clamp(card, xy):
    """Keep placements on screen and, for troops/buildings, on our side. Run 000342 placed a Golden
    Knight at x=1120 (predicted position ran off the 1080px screen): the card stayed selected."""
    x = min(max(xy[0], L.DEPLOY_X[0]), L.DEPLOY_X[1])
    if CARDS.get(card, {}).get("kind") == "spell":
        y = min(max(xy[1], L.ARENA_Y[0] + 40), L.OUR_DEPLOY_Y[1])
    else:
        y = min(max(xy[1], L.OUR_DEPLOY_Y[0]), L.OUR_DEPLOY_Y[1])
    return x, y


def lane_threat(ts):
    """How dangerous a group is: remaining HP, weighted up for tanks/splash/chargers/champions
    when the card is known, and for wide bars (big units) when it isn't."""
    total = 0.0
    for t in ts:
        w = 1.0
        if t.card:
            w += sum(0.5 for p in ("tank", "splash", "charge", "champion") if prop(t.card, p))
        elif t.w >= TANK_BAR_W:
            w += 1.0
        total += t.hp * w
    return total


def is_key(t):
    """A troop worth spending the GK ability on: ranged support, splash, or expensive (5+)."""
    return t.card is not None and (prop(t.card, "ranged") or prop(t.card, "splash")
                                   or CARDS.get(t.card, {}).get("cost", 0) >= 5)


def chain_reach(start, tracks):
    """Enemies the Golden Knight's dash chain can reach from `start`: first hop within GK_REACH_PX,
    then hops of GK_CHAIN_PX between enemies."""
    reached, frontier = [], [start]
    left = list(tracks)
    while frontier:
        fx, fy = frontier.pop()
        hop = GK_REACH_PX if (fx, fy) == start else GK_CHAIN_PX
        nxt = [t for t in left if math.dist((fx, fy), (t.x, t.y)) <= hop]
        for t in nxt:
            left.remove(t)
            reached.append(t)
            frontier.append((t.x, t.y))
    return reached


def other(lane_name):
    return "left" if lane_name == "right" else "right"


class Brain:
    def __init__(self, opponent=None):
        self.opponent = opponent
        self.last_defend = {"left": float("-inf"), "right": float("-inf")}
        self.last_ability = float("-inf")
        self.defend_cooldown = 3.0
        self.push_lane = "right"
        self.queue = []                 # planned follow-ups: (card, xy, not_before, until)
        self.defended_threat = {"left": 0.0, "right": 0.0}
        self.since_evo = {}             # card -> plays since its last evolved play
        self.towers = None
        self.last_action = float("-inf")
        self.recent_spends = []         # (time, cost, elixir shown before): bar lags behind taps

    def decide(self, elixir, hand, tracks, allies=(), new_plays=(), enemy_elixir=None,
               champion_ready=False, towers=None, gk_estimate=None, own_last=None, supports=None,
               now=None):
        """gk_estimate: dead-reckoned (x, y) of our Golden Knight when no badge is visible.
        own_last: {card: (x, y, time)} of our latest plays (tracker.OwnDeploys.last)."""
        now = now if now is not None else time.monotonic()
        # The elixir bar and the hand update a few frames after a tap. Until then, assume the
        # spend already happened, and don't fire again (that caused double plays on 2026-11-08).
        if now - self.last_action < ACTION_GAP_S:
            return None
        self.recent_spends = [s for s in self.recent_spends if now - s[0] < 1.5]
        for t0, cost, before in self.recent_spends:
            elixir = min(elixir, before - cost + (now - t0) / 2.8)
        playable = {c: i for i, c in enumerate(hand) if c and COST.get(c, 99) <= elixir}
        action = self._decide(elixir, hand, playable, tracks, allies, new_plays, enemy_elixir,
                              champion_ready, towers, gk_estimate, own_last or {}, supports or [], now)
        if action and action[2] is not None:
            action = (action[0], action[1], clamp(action[0], action[2]))
        if action:
            self.last_action = now
            self.note_played(action[0])
            cost = GK_ABILITY_COST if action[0] == "gk_ability" else COST[action[0]]
            self.recent_spends.append((now, cost, elixir))
        return action

    def _decide(self, elixir, hand, playable, tracks, allies, new_plays, enemy_elixir,
                champion_ready, towers, gk_estimate, own_last, supports, now):
        threats = [t for t in tracks if t.eta(L.RIVER_Y) <= LEAD_S]
        self.towers = towers

        # 0) Planned follow-up (second half of a spell finish).
        if self.queue:
            card, xy, not_before, until = self.queue[0]
            if now > until:
                self.queue.pop(0)
            elif now >= not_before and card in playable and not (threats and card in WIN_CONDITIONS):
                self.queue.pop(0)
                return card, playable[card], xy

        # 1) Golden Knight ability: chain-dash through a clump the GK can reach.
        gk = next((a for a in allies if a.label == "golden_knight"), None)
        gk_xy = (gk.x, gk.y) if gk else gk_estimate
        if gk_xy and champion_ready and elixir >= GK_ABILITY_COST and now - self.last_ability > 3.0:
            for t in tracks:
                if math.dist(gk_xy, (t.x, t.y)) > GK_REACH_PX:
                    continue
                clump = [o for o in tracks if math.dist((o.x, o.y), (t.x, t.y)) < GK_CHAIN_PX]
                if len(clump) >= SWARM_SIZE:
                    self.last_ability = now
                    return "gk_ability", None, None
            # Owner: use the ability to take out a key troop (e.g. the Wizard hiding behind its tank)
            # when the dash chain can reach it, even without a big clump.
            if any(is_key(k) for k in chain_reach(gk_xy, tracks)):
                self.last_ability = now
                return "gk_ability", None, None

        # 1b) Our support troop (Witch/GK/Minions) is walking to a bridge: put the win condition in
        #     front of it (owner: "you let your Witch go to waste... and played a dumb Tombstone").
        #     If we can't afford it yet, save elixir for it instead of spending on a non-urgent threat.
        push = self._join_support(elixir, playable, hand, supports, now)
        by_lane_u = {}
        for t in threats:
            by_lane_u.setdefault(t.lane, []).append(t)
        urgent = any(lane_threat(ts) / max(min(t.eta(L.RIVER_Y) for t in ts), 0.5) >= URGENT
                     for ts in by_lane_u.values())
        if push and push != "save" and not urgent:
            return push
        if push == "save" and not urgent:
            return None

        # 2) Defend. Both lanes can be under attack (owner: "bad at multitasking"): rank lanes by
        #    urgency = threat size / time to arrival, and re-defend a lane if its push grew.
        by_lane = {}
        for t in threats:
            by_lane.setdefault(t.lane, []).append(t)
        def urgency(kv):
            return lane_threat(kv[1]) / max(min(t.eta(L.RIVER_Y) for t in kv[1]), 0.5)
        for lane_name, ts in sorted(by_lane.items(), key=urgency, reverse=True):
            threat = lane_threat(ts)
            recent = now - self.last_defend[lane_name] < self.defend_cooldown
            grew = threat >= GROWTH_REDEFEND * max(self.defended_threat[lane_name], 0.5)
            if recent and not grew:
                continue
            if self._tower_handles(ts):
                continue
            front = min(ts, key=lambda t: t.eta(L.RIVER_Y))

            # Spells only when they're worth their cost: kills (incl. units our troops will finish),
            # tower damage. Covers "kill the low-HP backline first" and "Poison the half-HP Barbs
            # next to our Witch" without separate rules (owner, rounds 3 and 6).
            spell = self._best_spell_play(playable, tracks, self._helpers(allies, supports), elixir)
            if spell:
                self._defended(lane_name, threat, now)
                return spell

            # A charging unit (Prince, Dark Prince, Ram...) close to our tower: Log knocks it back
            # and resets the charge.
            if prop(front.card, "charge") and front.eta(L.RIVER_Y) <= 0.5 and "log" in playable:
                self._defended(lane_name, threat, now)
                return "log", playable["log"], (front.x, min(front.y + 80, 1650))

            clump = [t for t in ts if abs(t.x - front.x) + abs(t.y - front.y) < SWARM_PX]
            swarm = len(clump) >= SWARM_SIZE

            order = SWARM_DEFENSE if swarm else SINGLE_DEFENSE
            pf = profile(front.card)
            if front.card and not pf["hits_air"] and "minions" in order:
                order = ["minions"] + [c for c in order if c != "minions"]       # it can't touch air
            if pf["big_shot"]:
                order = ["tombstone"] + [c for c in order if c != "tombstone"]   # eat the charged shot
            if prop(front.card, "charge"):
                order = ["tombstone"] + [c for c in order if c != "tombstone"]   # absorbs the charge hit
            if self.evo_ready("ram"):
                order = [c for c in order if c != "ram"] + ["ram"]              # keep the Evo Ram for attack
            for card in order:
                if card not in playable:
                    continue
                xy = self._where(card, lane_name, front, clump)
                if card in FRAGILE and self._air_splash_risk(xy, tracks):
                    continue                                   # one splash hit would wipe it out
                self._defended(lane_name, threat, now)
                return card, playable[card], xy
            # nothing affordable: wait rather than overspend

        # 3) Spell finish on a low princess tower.
        finish = self._spell_finish(elixir, playable, tracks, enemy_elixir, towers, now)
        if finish:
            return finish

        # 4) Punish a big deploy at their back: they just spent a lot and it is far from us.
        if not threats:
            for g in new_plays:
                big = max(t.w for t in g) >= TANK_BAR_W
                at_back = all(t.y < L.RIVER_Y - 300 for t in g)
                if big and at_back:
                    for card in ("hog", "ram"):
                        if card in playable and elixir - COST[card] >= DEFENSE_RESERVE - 1:
                            return card, playable[card], L.BRIDGE[other(g[0].lane)]

        # 5) Help our attack: defenders gathering around our Hog/Ram at their tower get spelled.
        if not threats:
            helped = self._support_spell(elixir, playable, tracks, own_last, now)
            if helped:
                return helped

        # 6) Counter-push with survivors (owner): our troops that survived a defence and walk to
        #    the bridge are free support. Add a win condition in front of them.
        if not threats:
            for a in allies:
                for lane_name, (bx, by) in L.BRIDGE.items():
                    if a.y > L.RIVER_Y and math.dist((a.x, a.y), (bx, by)) < SURVIVOR_PX and a.vy < -5:
                        for card in WIN_CONDITIONS:
                            if card in playable and elixir - COST[card] >= 1:
                                return card, playable[card], (bx, by)

        # 7) Attack from a full bar or when they are low, never dry (owner: "your Hog is always alone").
        punish = (PUNISH_BELOW is not None and enemy_elixir is not None
                  and enemy_elixir <= PUNISH_BELOW)
        if not threats and (elixir >= 9 or punish):
            push = self._supported_push(elixir, playable, now)
            if push:
                return push
        if not threats and elixir >= LEAK_AT:
            return self._dont_leak(elixir, playable, tracks, towers)
        return None

    def _attack_ready(self, win, elixir, playable):
        """Can we attack with `win` given how this opponent answered it before? If they usually answer
        it with a swarm, attack only with Log/Poison affordable too. Returns (ok, pre_cast_spell)."""
        if not self.opponent:
            return True, None
        p = self.opponent.response_prob(win, "swarm")
        if p < RESPONSE_PREPARE:
            return True, None
        spell = next((c for c in ("log", "poison") if c in playable), None)
        if not spell or elixir < COST[win] + COST[spell]:
            return False, None                     # attack when the answer to their answer is ready
        return True, (spell if p >= RESPONSE_PRECAST else None)

    def _queue_precast(self, spell, lane_name, now):
        """Their usual swarm answer appears in front of their tower: be there when it does."""
        tx, ty = L.TOWERS["enemy_" + lane_name]
        xy = (tx, ty + 170) if spell == "poison" else (tx, ty + 420)
        self.queue.append((spell, xy, now + PRECAST_AFTER_S, now + 6.0))

    def _join_support(self, elixir, playable, hand, supports, now):
        """A win condition for a support troop near its bridge: the play, "save", or None."""
        wins = (["ram", "hog"] if self.evo_ready("ram") else WIN_CONDITIONS)
        win_in_hand = next((c for c in wins if c in hand), None)
        if not win_in_hand:
            return None
        for card, lane_name, (sx, sy) in supports:
            bx, by = L.BRIDGE[lane_name]
            if sy < L.RIVER_Y - 150 or math.dist((sx, sy), (bx, by)) > PUSH_JOIN_PX:
                continue                              # not near its bridge (yet), or already across
            if win_in_hand in playable:
                ok, precast = self._attack_ready(win_in_hand, elixir, playable)
                if not ok:
                    return "save"
                self.push_lane = lane_name
                if precast:
                    self._queue_precast(precast, lane_name, now)
                return win_in_hand, playable[win_in_hand], (bx, by - 20)   # just ahead of the support
            return "save"
        return None

    def _supported_push(self, elixir, playable, now):
        """Support troop first, then the win condition right behind it at the same bridge, so they
        reach the tower together. Golden Knight first: he survives splash and his dash clears the
        defenders. Minions only when no splash card can be in their hand."""
        wins = (["ram", "hog"] if self.evo_ready("ram") else WIN_CONDITIONS)
        win = next((c for c in wins if c in playable), None)
        if not win:
            return None
        lane_name = other(self.push_lane)
        bx, by = L.BRIDGE[lane_name]
        ok, precast = self._attack_ready(win, elixir, playable)
        if not ok:
            return None
        if precast:
            self._queue_precast(precast, lane_name, now)
        for sup in SUPPORT:
            if sup not in playable or elixir - COST[sup] - COST[win] < 1:
                continue
            if sup in FRAGILE and self._air_splash_risk((bx, by), []):
                continue
            self.push_lane = lane_name
            # win condition one action-gap later, at the bridge in front of the support
            self.queue.append((win, (bx, by), now + ACTION_GAP_S, now + 4.0))
            return sup, playable[sup], (bx, by + 70)
        # no support affordable: only go alone from a full bar, and keep the defence reserve
        if elixir >= 9.5 and elixir - COST[win] >= DEFENSE_RESERVE:
            self.push_lane = lane_name
            return win, playable[win], (bx, by)
        return None

    def _support_spell(self, elixir, playable, tracks, own_last, now):
        """Our Hog/Ram reached their tower: spell the defenders around it so it keeps hitting."""
        for card in WIN_CONDITIONS:
            if card not in own_last:
                continue
            x, y, t0 = own_last[card]
            if not 2.0 <= now - t0 <= 8.0:
                continue
            tower = min(("enemy_left", "enemy_right"), key=lambda n: abs(L.TOWERS[n][0] - x))
            tx, ty = L.TOWERS[tower]
            defenders = [t for t in tracks if math.dist((t.x, t.y), (tx, ty + 120)) < 330]
            spell = self._best_spell_play(playable, defenders, [(tx, ty + 120)], elixir)
            if spell:
                return spell
        return None

    def _helpers(self, allies, supports):
        """Positions of our troops that will add damage next to a spell (visible or dead-reckoned)."""
        return [(a.x, a.y) for a in allies] + [xy for _, _, xy in supports]

    def _best_spell_play(self, playable, tracks, helpers, elixir, min_value=None):
        """The best Log/Poison cast if it's worth its cost (spells.worth_it), else None."""
        best = None
        for card in ("poison", "log"):
            if card not in playable:
                continue
            xy, value = best_spell(card, tracks, helpers)
            ok = value >= min_value if min_value is not None else worth_it(card, value)
            if xy and ok and (best is None or value - COST[card] > best[0]):
                best = (value - COST[card], card, xy)
        return (best[1], playable[best[1]], best[2]) if best else None

    def _dont_leak(self, elixir, playable, tracks, towers):
        """At a full bar, regen is wasted every second. Run 000342 sat at 9-10 elixir for ~40s with
        Poison and Ram stuck in hand. Use a stuck card for value instead."""
        # No "dump a spell at a full bar" any more (run 061822: Poison on one unknown unit next to their
        # tower, woke their king). Spells only through the normal value check; a full bar builds a push.
        if elixir >= 9.8:
            # build a push from the back: biggest troop behind our king tower
            for card in ("witch", "golden_knight", "ram", "hog", "minions"):
                if card in playable:
                    self.push_lane = other(self.push_lane)
                    return card, playable[card], L.BACK[self.push_lane]
        return None

    def _defended(self, lane_name, threat, now):
        self.last_defend[lane_name] = now
        self.defended_threat[lane_name] = threat

    def _air_splash_risk(self, xy, tracks):
        """Minions get cooked by one splash that hits air (owner: Wizard vs Minions). Risky if such a
        unit is near the spot, or if the opponent can have one in hand (cycle estimate)."""
        near = any(prop(t.card, "splash") and prop(t.card, "hits_air")
                   and math.dist(xy, (t.x, t.y)) < SPLASH_REACH_PX for t in tracks)
        in_hand = bool(self.opponent) and any(
            prop(c, "splash") and prop(c, "hits_air") for c in self.opponent.hand_estimate())
        return near or in_hand

    # --- evolutions: count our own plays (owner: Evo Ram every 2 cycles, Evo Witch every 1) ---
    # --- snapshot/restore: a blended policy may override the rules' proposal. Proposing must then
    #     leave no trace (cooldowns, queue, evo counts); only the executed move is committed. ---
    _STATE = ("last_defend", "defended_threat", "last_ability", "push_lane", "queue", "last_action",
              "recent_spends", "since_evo")

    def snapshot(self):
        return {k: copy.deepcopy(getattr(self, k)) for k in self._STATE}

    def restore(self, snap):
        for k, v in snap.items():
            setattr(self, k, v)

    def commit(self, card, elixir, now):
        """Book-keeping for a move chosen by another policy (what decide() does for its own)."""
        self.last_action = now
        self.note_played(card)
        cost = GK_ABILITY_COST if card == "gk_ability" else COST.get(card, 0)
        self.recent_spends.append((now, cost, elixir))

    def evo_ready(self, card):
        return card in EVO_CYCLES and self.since_evo.get(card, 0) >= EVO_CYCLES[card]

    def note_played(self, card):
        if card not in EVO_CYCLES:
            return
        if self.evo_ready(card):
            self.since_evo[card] = 0          # this play was the evolved one
        else:
            self.since_evo[card] = self.since_evo.get(card, 0) + 1

    @staticmethod
    def _tower_handles(ts):
        """Small threats the princess tower kills alone: spending on them leaves us empty for the
        push that matters (2026-11-08: a Tombstone on 2 weak units, then the right tower fell)."""
        if len(ts) == 1 and ts[0].hp <= TOWER_HANDLES_HP:
            return True
        return len(ts) <= 2 and all(t.hp <= TOWER_HANDLES_HP / 2 for t in ts)

    def _spell_finish(self, elixir, playable, tracks, enemy_elixir, towers, now):
        if not towers:
            return None
        if any(t.eta(L.RIVER_Y) < FINISH_SAFE_ETA for t in tracks):
            return None
        for name in ("enemy_left", "enemy_right"):
            frac = towers.get(name)
            if not frac:                                   # destroyed or unreadable
                continue
            hp = frac * PRINCESS_MAX_HP
            tx, ty = L.TOWERS[name]
            log_xy = (tx, ty + 4 * L.TILE_PX)              # Log starts in front and rolls into it
            options = [(["log"], SPELL_TOWER_DMG["log"]),
                       (["poison"], SPELL_TOWER_DMG["poison"]),
                       (["poison", "log"], SPELL_TOWER_DMG["poison"] + SPELL_TOWER_DMG["log"])]
            for cards, dmg in options:                     # cheapest combo that kills
                cost = sum(COST[c] for c in cards)
                if hp > dmg * 0.95 or cost > elixir or not all(c in playable for c in cards):
                    continue
                they_are_low = enemy_elixir is not None and enemy_elixir <= 3
                if elixir - cost < FINISH_KEEP and not they_are_low:
                    continue
                first = cards[0]
                if len(cards) == 2:
                    self.queue.append(("log", log_xy, now, now + 3.0))
                xy = log_xy if first == "log" else (tx, ty)
                return first, playable[first], xy
        return None

    def _defend_spot(self, lane_name, front, tracks_all):
        """Where a defending troop should stand (owner, round 6):
        - luring: the enemy should fight it *inside* our tower's range, so the tower helps (a GK met a
          Musketeer at the river, out of range). Ranged enemies stop at their range from our troop, so
          our troop must be close enough to the tower that the enemy is still in tower range.
        - splash: never so close to our tower that one splash hit (Wizard...) hits both."""
        tower = self._our_tower(lane_name)
        ex, ey = front.at(1.0)
        d_enemy = math.dist(tower, (ex, ey)) or 1.0
        ux, uy = (ex - tower[0]) / d_enemy, (ey - tower[1]) / d_enemy
        pf = profile(front.card)
        if pf["range_px"] > 2 * L.TILE_PX:                      # ranged: keep them in tower range
            d = max(60.0, TOWER_RANGE_PX - pf["range_px"] - 30)
        else:                                                   # melee: meet them in front of the tower
            d = min(d_enemy - 40, 260.0)
        splash = max([profile(t.card)["splash_px"] for t in tracks_all if t.card] + [0.0])
        if self.opponent:
            splash = max([splash] + [profile(c)["splash_px"] for c in self.opponent.hand_estimate()
                                     if CARDS.get(c, {}).get("kind") == "troop"])
        if splash:
            d = max(d, TOWER_HALF_PX + splash + 30)             # one splash can't reach troop and tower
        return tower[0] + ux * d, tower[1] + uy * d

    def _our_tower(self, lane_name):
        v = (self.towers or {}).get("our_" + lane_name)
        return L.TOWERS["our_" + lane_name] if v is None or v > 0 else L.OUR_KING

    def _where(self, card, lane_name, t, group=None):
        # Aim where the enemy will be when our card lands (~1s deploy).
        ex, ey = t.at(1.0)
        if card in ("log", "poison"):
            spot, _ = best_spell(card, group or [t])
            return spot or (ex, ey)
        if card in ("golden_knight", "ram", "minions"):
            return self._defend_spot(lane_name, t, tracks_all=group or [t])
        ey = max(ey, L.RIVER_Y + 60)                      # troops/buildings only on our side
        if card == "tombstone":
            return L.CENTER_PULL[lane_name]               # pulls building-targeters to the middle
        if card == "witch":
            xy = (ex, min(ey + 350, 1650))                # behind the threat, out of melee range
            return self.opponent.safe_spot(xy) if self.opponent else xy
        return ex, min(ey + 150, 1650)                    # melee/air: just in front of the threat

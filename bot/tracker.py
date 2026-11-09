"""Unit tracking over time: IDs, velocity, arrival-time prediction, and new-unit (deploy) events.

Used twice: once for enemy bars (red) and once for our own bars (blue). Our own tracks get a
`label` (the card we played), so we know where e.g. our Golden Knight actually is.
"""
import itertools
import math

from . import layout as L
from .cards import CARDS

MATCH_PX = 90        # max movement between frames to count as the same unit
GROUP_PX = 260       # new bars this close together on the same frame = one play
LOST_AFTER = 0.6     # seconds without a match before a track is dropped
REAPPEAR_S = 2.0     # a new unit near a track lost this recently is the same unit coming back
REAPPEAR_PX = 160


class Track:
    _ids = itertools.count(1)

    def __init__(self, p, now):
        self.id = next(self._ids)
        self.x, self.y, self.w = p[0], p[1], p[2]
        self.hp = p[3] if len(p) > 3 else 1.0      # fraction of the unit's own HP left
        self.vx = self.vy = 0.0                    # px/s, smoothed; +vy = moving down the screen
        self.born = self.seen = now
        self.hits = 1
        self.label = None                          # our card name, for our own tracks
        self.card = None                           # enemy card name, once the recogniser knows it
        self.cropped = False                       # recorder saved a crop of this unit
        self.x0, self.y0 = self.x, self.y          # where it first appeared
        self.travelled = 0.0                       # max distance from where it appeared
        self.play_index = None                     # index of the enemy play this unit came from

    def update(self, p, now):
        dt = now - self.seen
        if dt > 0:
            a = 0.4                                # smoothing: bars jitter a few px every frame
            self.vx = (1 - a) * self.vx + a * (p[0] - self.x) / dt
            self.vy = (1 - a) * self.vy + a * (p[1] - self.y) / dt
        self.x, self.y, self.w, self.seen = p[0], p[1], max(self.w, p[2]), now
        self.travelled = max(self.travelled, math.dist((self.x, self.y), (self.x0, self.y0)))
        if len(p) > 3:
            self.hp = p[3]
        self.hits += 1

    @property
    def lane(self):
        return "left" if self.x < L.MID_X else "right"

    def eta(self, target_y):
        """Seconds until a unit moving down the screen reaches target_y (0 if past, inf if not coming)."""
        if self.y >= target_y:
            return 0.0
        if self.vy <= 5:                           # standing still or moving away (e.g. not walked yet)
            return float("inf")
        return (target_y - self.y) / self.vy

    MAX_VX = 60.0     # px/s: troops walk lanes mostly vertically; badge jitter made vx swing to
                      # 300 px/s and threw a Log off the screen edge (run 004519, 26s)

    def at(self, seconds):
        """Predicted position after `seconds`, following the walking path: an enemy above the river
        walks to its lane's bridge, then down to our tower in that lane. A straight-line guess with
        jittery sideways speed put a Poison and a Log off target (runs 004519, 010052)."""
        speed = min(math.hypot(max(-self.MAX_VX, min(self.MAX_VX, self.vx)), self.vy), 160.0)
        if self.vy <= 5 or speed < 8:                # not walking toward us: stays (or moving away)
            vx = max(-self.MAX_VX, min(self.MAX_VX, self.vx))
            return self.x + vx * seconds, min(self.y + self.vy * seconds, L.ARENA_Y[1])
        return walk_path(self.x, self.y, self.lane, speed * seconds)


OUR_ALIVE = {"left": True, "right": True}       # set each frame from tower HP (set_alive)


def set_alive(towers):
    for lane in ("left", "right"):
        v = (towers or {}).get("our_" + lane)
        OUR_ALIVE[lane] = v is None or v > 0


def walk_path(x, y, lane, dist):
    """Move `dist` px along an enemy troop's path: to the lane bridge, then to our lane tower, or to
    our king tower once that lane tower is down (run 010908: Barbarians turned to the king and walked
    out of a Poison aimed at the dead tower's path)."""
    bx, by = L.BRIDGE[lane]
    target = L.TOWERS["our_" + lane] if OUR_ALIVE[lane] else L.OUR_KING
    waypoints = ([(bx, L.RIVER_Y)] if y < L.RIVER_Y else []) + [target]
    for wx, wy in waypoints:
        leg = math.dist((x, y), (wx, wy))
        if dist <= leg:
            f = dist / leg if leg else 1.0
            return x + (wx - x) * f, y + (wy - y) * f
        dist -= leg
        x, y = wx, wy
    return x, y


class Tracker:
    def __init__(self):
        self.tracks = []
        self.pending = []                          # new groups waiting one frame for confirmation
        self.recently_lost = []                    # (x, y, time) of tracks dropped recently

    def _reappeared(self, group):
        """A 'new' unit near where a unit just vanished is the same unit whose badge was hidden
        for a moment (another troop on top, a spell effect), not a new play. Seen 2026-11-08: these
        fake plays drove the opponent-elixir estimate to 0."""
        return any(abs(t.x - x) + abs(t.y - y) < REAPPEAR_PX for t in group for x, y, _ in self.recently_lost)


    def update(self, points, now):
        """points: (x, y, w[, hp]) per bar. Returns confirmed groups of new tracks (= new plays)."""
        free = list(points)
        for t in sorted(self.tracks, key=lambda t: -t.hits):     # established tracks pick first
            best = min(free, key=lambda p: abs(p[0] - t.x) + abs(p[1] - t.y), default=None)
            if best and abs(best[0] - t.x) + abs(best[1] - t.y) < MATCH_PX:
                t.update(best, now)
                free.remove(best)
        dropped = [t for t in self.tracks if now - t.seen >= LOST_AFTER]
        self.recently_lost = [(t.x, t.y, now) for t in dropped] + [
            r for r in self.recently_lost if now - r[2] < REAPPEAR_S]
        self.tracks = [t for t in self.tracks if now - t.seen < LOST_AFTER]

        confirmed = [g for g in self.pending if all(t in self.tracks and t.seen == now for t in g)]
        confirmed = [g for g in confirmed if not self._reappeared(g)]

        groups = []
        for p in free:
            t = Track(p, now)
            self.tracks.append(t)
            for g in groups:
                if any(abs(p[0] - o.x) + abs(p[1] - o.y) < GROUP_PX for o in g):
                    g.append(t)
                    break
            else:
                groups.append([t])
        self.pending = groups
        return confirmed

    def labelled(self, label):
        return [t for t in self.tracks if t.label == label]


class OwnDeploys:
    """Matches our own plays to the blue bars that appear ~1s later, and labels those tracks."""
    WINDOW_S = 2.5
    NEAR_PX = 260

    MEDIUM_SPEED_PX = 54        # px/s: "medium" speed = 1 tile/s (unverified)
    DEPLOY_S = 1.0              # deploy time before a troop starts walking (unverified)

    FIGHT_PX = 300              # an enemy this close: our troop stops to fight (doesn't walk on)

    def __init__(self):
        self.waiting = []                          # (card, x, y, time)
        self.last = {}                             # card -> (x, y, time) of our latest play
        self.pos = {}                              # card -> [x, y, time]: walked estimate

    def played(self, card, xy, now):
        self.waiting.append((card, xy[0], xy[1], now))
        self.last[card] = (xy[0], xy[1], now)
        self.pos[card] = [xy[0], xy[1], now]

    def advance(self, now, enemies, allies=()):
        """Walk our troops' estimates forward one frame. A troop that has an enemy near it is fighting
        and doesn't walk on (run 010908: the Witch stopped to fight at our tower while the estimate
        said she was at the bridge, so the Hog went alone). A visible badge replaces the estimate."""
        for card, p in self.pos.items():
            x, y, t = p
            seen = next((a for a in allies if a.label == card), None)
            if seen:
                p[:] = [seen.x, seen.y, now]
                continue
            age = now - self.last[card][2]
            fighting = any(math.dist((x, y), (e.x, e.y)) <= self.FIGHT_PX for e in enemies)
            if age > self.DEPLOY_S and not fighting:
                step = CARDS.get(card, {}).get("speed", 1.0) * L.TILE_PX * (now - t)
                x, y = self._walk(x, y, step)
            p[:] = [x, y, now]

    @staticmethod
    def _walk(x, y, dist):
        """Our troop's path: to its lane's bridge, then up toward the enemy tower."""
        bx, by = L.BRIDGE["left" if x < L.MID_X else "right"]
        to_bridge = math.dist((x, y), (bx, by))
        if y > by and dist <= to_bridge:
            f = dist / to_bridge if to_bridge else 1.0
            return x + (bx - x) * f, y + (by - y) * f
        if y > by:
            dist -= to_bridge
            x, y = bx, by
        return x, y - dist

    SUPPORT_CARDS = ("witch", "golden_knight", "minions")
    SUPPORT_ALIVE_S = 14.0       # assume a support troop is still alive this long (unverified)

    def supports(self, now):
        """Our support troops that should still be walking: (card, lane, (x, y)). Our units at full
        HP show no badge, so this is how the bot 'sees' its own Witch (run 010052: she walked to the
        bridge alone while the bot spent its elixir elsewhere)."""
        out = []
        for card in self.SUPPORT_CARDS:
            pos = self.estimate(card, now, max_age=self.SUPPORT_ALIVE_S)
            if pos:
                out.append((card, "left" if self.last[card][0] < L.MID_X else "right", pos))
        return out

    def estimate(self, card, now, max_age=12.0):
        """Dead-reckoned position of a troop we played, for when its badge isn't shown
        (our units at full HP have no badge). It walks to its lane's bridge, then up the lane."""
        if card not in self.last:
            return None
        x, y, t = self.last[card]
        age = now - t
        if age > max_age:
            return None
        p = self.pos.get(card)
        if p and p[2] > t:                         # advanced by advance(): fight-aware estimate
            return p[0], p[1]
        tiles_per_s = CARDS.get(card, {}).get("speed", 1.0)
        walk = max(0.0, age - self.DEPLOY_S) * tiles_per_s * L.TILE_PX
        bx, by = L.BRIDGE["left" if x < L.MID_X else "right"]
        to_bridge = math.dist((x, y), (bx, by))
        if walk <= to_bridge:
            f = walk / to_bridge if to_bridge else 1.0
            return x + (bx - x) * f, y + (by - y) * f
        return bx, by - (walk - to_bridge)

    def update(self, new_groups, now):
        self.waiting = [w for w in self.waiting if now - w[3] < self.WINDOW_S]
        for g in new_groups:
            for w in list(self.waiting):
                card, x, y, _ = w
                if any(abs(t.x - x) + abs(t.y - y) < self.NEAR_PX for t in g):
                    for t in g:
                        t.label = card
                    self.waiting.remove(w)
                    break

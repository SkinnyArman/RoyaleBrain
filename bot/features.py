"""(state, action) -> feature vector for learned scorers.

Cards are encoded as NUMBERS (their profiles), never as names: our move, our hand, our troops around
the move and the enemies it meets are all HP / DPS / range / splash / cost / targets. So what the
model learns about "Hog in front of a Witch" transfers to "Ram in front of a Wizard" or any card
it hasn't seen, and the model's size doesn't grow with the number of cards (owner, 2026-11-09:
"I can't give you every variation... the model is going to be gigantic with lots of cards").

Works on the State as a dict (what decisions.jsonl holds), so training and live scoring use the
exact same encoding. Model files store the feature list they were trained with.
"""
import math

import numpy as np

from .cards import CARDS, prop
from .profiles import SPELLS, profile

TILE = 54.0
RIVER_Y = 1080.0
NEAR_PX = 4 * TILE          # what a move "meets"
ARMY_PX = 6 * TILE          # our troops that fight together with a move


def _tower(v):
    return -1.0 if v is None else float(v)


def card_vector(card):
    """A card as numbers. Same 11 numbers for any card, ours or theirs."""
    kind = CARDS.get(card, {}).get("kind", "troop")
    p = profile(card, ours=True)
    spell = SPELLS.get(card, {})
    return [p["cost"] / 10.0, p["hp"] * p["count"] / 3000.0, p["dps"] * p["count"] / 1000.0,
            p["range_px"] / (6 * TILE), p["splash_px"] / (2 * TILE), float(p["buildings"]),
            float(kind == "spell"), float(kind == "building"), spell.get("damage", 0.0) / 1000.0,
            float(prop(card, "air")), float(p["hits_air"])]


CARD_FEATURES = ["cost", "hp", "dps", "range", "splash", "targets_buildings", "is_spell", "is_building",
                 "spell_damage", "air", "hits_air"]


def _army(units, ours):
    """Profile totals of a group: remaining HP, DPS, ranged, splash, anti-air, building-targeters."""
    hp = dps = ranged = splash = anti_air = buildings = 0.0
    for u in units:
        card = u["card"] if isinstance(u, dict) else u[0]
        frac = u["hp"] if isinstance(u, dict) else 1.0
        p = profile(card, ours=ours)
        hp += frac * p["hp"] * (1 if isinstance(u, dict) else p["count"])
        dps += p["dps"] * (1 if isinstance(u, dict) else p["count"])
        ranged += p["range_px"] > 2 * TILE
        splash += p["splash_px"] > 0
        anti_air += p["hits_air"]
        buildings += p["buildings"]
    return [hp / 3000.0, dps / 1000.0, ranged, splash, anti_air, buildings]


ARMY_FEATURES = ["hp", "dps", "ranged", "splash", "anti_air", "building_targeters"]


def _lane_stats(enemies, lane):
    ts = [u for u in enemies if u["lane"] == lane and u["eta_river"] <= 3.0]
    eta = min([u["eta_river"] for u in ts], default=10.0)
    return [len(ts), sum(u["hp"] * profile(u.get("card"))["hp"] for u in ts) / 3000.0, min(eta, 10.0)]


def _hand(s):
    cards = [c for c in s["hand"] if c]
    afford = [c for c in cards if CARDS.get(c, {}).get("cost", 99) <= s["elixir"]]
    return [
        sum(1 for c in cards if profile(c, ours=True)["buildings"]),            # win conditions
        sum(1 for c in cards if CARDS.get(c, {}).get("kind") == "spell"),
        sum(1 for c in afford if CARDS.get(c, {}).get("kind") == "spell"),
        sum(1 for c in cards if profile(c, ours=True)["splash_px"] > 0),
        sum(1 for c in cards if profile(c, ours=True)["hits_air"]),
        float(np.mean([CARDS.get(c, {}).get("cost", 4) for c in cards])) if cards else 0.0,
        len(afford),
    ]


def state_features(s):
    enemies = s["enemies"]
    towers = s["towers"]
    eh = s.get("enemy_hand", [])
    resp = s.get("responses") or {}
    return [
        s["t"] / 180.0, max(0.0, 180.0 - s["t"]) / 180.0, s["elixir"], s["enemy_elixir"],
        s["elixir"] - s["enemy_elixir"], 1.0 if s["regen"] > 0.5 else 0.0,
        _tower(towers.get("enemy_left")), _tower(towers.get("enemy_right")),
        _tower(towers.get("our_left")), _tower(towers.get("our_right")),
        1.0 if s["champion_ready"] else 0.0,
        len(enemies), sum(1 for u in enemies if u["y"] > RIVER_Y),
        *_lane_stats(enemies, "left"), *_lane_stats(enemies, "right"),
        *_hand(s),
        1.0 if any(prop(c, "splash") and prop(c, "hits_air") for c in eh) else 0.0,
        1.0 if any(prop(c, "swarm") for c in eh) else 0.0,
        max(resp.values(), default=0.0),
        *_army(enemies, ours=False),
        *_army(s.get("our_units", []), ours=True),
    ]


STATE_FEATURES = (
    ["t", "time_left", "elixir", "enemy_elixir", "elixir_diff", "double",
     "tw_enemy_left", "tw_enemy_right", "tw_our_left", "tw_our_right", "champion_ready",
     "n_enemies", "n_enemies_our_half",
     "left_threats", "left_threat_hp", "left_eta", "right_threats", "right_threat_hp", "right_eta",
     "hand_win_conditions", "hand_spells", "hand_spells_affordable", "hand_splash", "hand_anti_air",
     "hand_avg_cost", "hand_affordable", "eh_air_splash", "eh_swarm", "resp_swarm_max"]
    + [f"enemy_{f}" for f in ARMY_FEATURES] + [f"our_{f}" for f in ARMY_FEATURES]
)


def action_features(s, a):
    is_wait, is_ability = float(a["kind"] == "wait"), float(a["kind"] == "ability")
    n = len(ACTION_FEATURES) - 2
    if a["kind"] != "play":
        return [is_wait, is_ability] + [0.0] * n
    card = a["card"]
    x, y = float(a["x"]), float(a["y"])
    enemies = s["enemies"]
    near = [u for u in enemies if math.dist((x, y), (u["x"], u["y"])) <= NEAR_PX]
    ours = [u for u in s.get("our_units", []) if math.dist((x, y), (u[1], u[2])) <= ARMY_PX]
    behind = [u for u in ours if u[2] > y]          # our troops behind the move (support)
    ahead = [u for u in ours if u[2] < y]           # our troops in front of it (it supports them)
    lane = "left" if x < 540 else "right"
    front = max([u["y"] for u in enemies if u["lane"] == lane], default=0.0)
    air_splash = any(prop(u["card"], "splash") and prop(u["card"], "hits_air")
                     and math.dist((x, y), (u["x"], u["y"])) <= 6 * TILE for u in enemies)
    return [is_wait, is_ability, *card_vector(card),
            x / 1080.0, y / 2400.0, float(y < RIVER_Y + 120), (y - front) / 1000.0 if front else 0.0,
            min([math.dist((x, y), (u["x"], u["y"])) for u in enemies], default=2000.0) / 1000.0,
            *_army(near, ours=False), float(air_splash), _spell_kill_share(card, near),
            *_army(behind, ours=True), *_army(ahead, ours=True)]


def _spell_kill_share(card, units):
    if card not in SPELLS or not units:
        return 0.0
    dmg = SPELLS[card]["damage"]
    return sum(1 for u in units if u["hp"] * profile(u.get("card"))["hp"] <= dmg) / len(units)


ACTION_FEATURES = (
    ["act_wait", "act_ability"] + [f"act_{f}" for f in CARD_FEATURES]
    + ["act_x", "act_y", "act_at_bridge", "act_y_vs_front", "act_min_enemy_dist"]
    + [f"meets_{f}" for f in ARMY_FEATURES] + ["meets_air_splash", "act_spell_kill_share"]
    + [f"behind_{f}" for f in ARMY_FEATURES] + [f"ahead_{f}" for f in ARMY_FEATURES]
)
FEATURES = STATE_FEATURES + ACTION_FEATURES


def encode(s, a):
    return state_features(s) + action_features(s, a)


def encode_many(s, actions):
    base = state_features(s)
    return np.array([base + action_features(s, a) for a in actions], dtype=np.float32)

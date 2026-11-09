"""Troop profiles: numbers for every card, so the bot reasons with HP, damage, range and splash, and
generalises to cards it has never fought (owner: "the model should develop a profile for each troop").

Sources, in order:
  data/cards_api.json      official catalog (names, elixir, rarity, evo/hero) - api.clashroyale.com
  data/card_stats.json     base stats (RoyaleAPI cr-api-data; may lag balance patches)
  data/profiles_learned.json   what we measured ourselves across matches (speed, lifetime, seen count)
  bot/cards.py             hand-written traits (splash, sturdy, charge...) and owner knowledge

Level scaling is approximate: +10% per level above the rarity's starting level (unverified; the
real table differs by a few %). Our levels come from the owner's Battle Log; enemy level from towers.
"""
import json
from functools import lru_cache
from pathlib import Path

from .cards import CARDS

DATA = Path(__file__).resolve().parent.parent / "data"
TILE = 54.0
START_LEVEL = {"common": 1, "rare": 3, "epic": 6, "legendary": 9, "champion": 11}
OUR_LEVELS = {"witch": 14, "golden_knight": 13, "ram": 13, "poison": 11, "log": 13, "tombstone": 13,
              "hog": 12, "minions": 13}          # owner's Battle Log, 2026-11-08
ENEMY_LEVEL = 14                                 # practice vs Devil (level-14 towers); per match later

# our card keys -> official names / stats unit names, where a simple transform doesn't work
API_NAME = {"hog": "Hog Rider", "ram": "Battle Ram", "log": "The Log", "evo_barbarians": "Barbarians",
            "hero_wizard": "Wizard", "mini_pekka": "Mini P.E.K.K.A", "pekka": "P.E.K.K.A"}
UNIT_NAME = {"hog": "HogRider", "ram": "BattleRam", "minions": "Minion", "spear_goblins": "SpearGoblin",
             "evo_barbarians": "Barbarian", "barbarians": "Barbarian", "hero_wizard": "Wizard",
             "goblins": "Goblin", "goblin_gang": "Goblin", "skeleton_army": "Skeleton", "bats": "Bat",
             "minion_horde": "Minion", "mini_pekka": "MiniPekka", "pekka": "Pekka", "golem": "Golem",
             "goblin_barrel": "Goblin", "ram_rider": "Ram", "dart_goblin": "BlowdartGoblin",
             "sparky": "ZapMachine", "elite_barbarians": "AngryBarbarian"}
UNIT_COUNT = {"barbarians": 5, "evo_barbarians": 5, "spear_goblins": 3, "minions": 3, "minion_horde": 6,
              "goblin_gang": 6, "goblins": 3, "skeleton_army": 15, "bats": 5, "goblin_barrel": 3, "elite_barbarians": 2}

# spells at OUR level (unverified, from base stats scaled): total damage to troops, crown-tower factor
SPELLS = {
    "poison": {"radius_px": 3.5 * TILE, "damage": 57 * 8 * 1.1 ** (11 - 6), "tower_factor": 0.3},
    "log": {"width_px": 3.9 * TILE, "length_px": 10.1 * TILE, "damage": 240 * 1.1 ** (13 - 9), "tower_factor": 0.2},
}


@lru_cache(maxsize=1)
def _api():
    p = DATA / "cards_api.json"
    return {c["name"]: c for c in json.loads(p.read_text())["cards"]} if p.exists() else {}


@lru_cache(maxsize=1)
def _stats():
    p = DATA / "card_stats.json"
    return json.loads(p.read_text())["units"] if p.exists() else {}


@lru_cache(maxsize=1)
def _learned():
    p = DATA / "profiles_learned.json"
    return json.loads(p.read_text()) if p.exists() else {}


def _unit_name(card):
    if card in UNIT_NAME:
        return UNIT_NAME[card]
    camel = "".join(w.capitalize() for w in card.split("_"))
    return camel if camel in _stats() else camel.rstrip("s")


def profile(card, level=None, ours=False):
    """Numbers for one card. Unknown card -> generic mid-size troop."""
    if card and card.startswith("evo_") and card not in UNIT_NAME:
        card = card.removeprefix("evo_")           # an evolution has its base card's stats (approx.)
    if card is None:
        return dict(big_shot=0.0, card=None, cost=3.5, count=1, hp=900.0, dps=150.0, range_px=1.2 * TILE,
                    speed_px=1.0 * TILE, splash_px=0.0, hits_air=True, buildings=False, known=False)
    api = _api().get(API_NAME.get(card, card.replace("_", " ").title()), {})
    unit = _stats().get(_unit_name(card), {})
    rarity = api.get("rarity") or unit.get("rarity", "common").lower()
    level = level or (OUR_LEVELS.get(card, 13) if ours else ENEMY_LEVEL)
    scale = 1.1 ** max(0, level - START_LEVEL.get(rarity.lower(), 1))
    hit_speed = unit.get("hit_speed", 1000) / 1000.0
    trait = CARDS.get(card, {})
    learned = _learned().get(card, {})
    shot = trait.get("big_shot")                   # e.g. Sparky: one charged hit every few seconds
    return dict(
        big_shot=float(shot or 0.0),
        card=card,
        cost=float(api.get("elixirCost", trait.get("cost", 3.5))),
        count=UNIT_COUNT.get(card, unit.get("summon_number", 1) or 1),
        hp=float(unit.get("hitpoints", 900)) * scale,
        dps=(float(shot) * scale / 4.0 if shot else float(unit.get("damage", 150)) * scale / max(hit_speed, 0.3)),
        range_px=unit.get("range", 1200) / 1000.0 * TILE,
        speed_px=learned.get("speed_px") or unit.get("speed", 60) / 60.0 * TILE,
        splash_px=unit.get("area_damage_radius", 0) / 1000.0 * TILE or (1.5 * TILE if trait.get("splash") else 0.0),
        hits_air=bool(unit.get("attacks_air", trait.get("hits_air", False))),
        buildings=bool(unit.get("target_only_buildings", trait.get("buildings", False))),
        known=bool(unit) or bool(trait),
    )


DROPPED_IN_Y = 1080 + 200       # appeared this deep on our side = spell/spawner drop, not walked in
DROPPED_IN_HP = 250.0           # prior HP for such unknown units (goblins, skeletons ~80-300)


def remaining_hp(track):
    """Absolute HP left of a tracked enemy unit (fraction from its bar x its profile HP).

    Unknown units that appeared deep on our side (Goblin Barrel, Graveyard, Skeleton Barrel drop,
    spawners) get a low-HP swarm prior instead of the generic 900: otherwise a Log never looks like
    it kills them (owner, 2026-11-09: 'the best reaction to Goblin Barrel is a Log')."""
    if track.card is None and getattr(track, "y0", 0) >= DROPPED_IN_Y:
        return track.hp * DROPPED_IN_HP
    return track.hp * profile(track.card)["hp"]


def unit_value(card):
    """Elixir value of one unit of a card (Barbarians: 5 elixir / 5 units = 1 each)."""
    p = profile(card)
    return p["cost"] / max(1, p["count"])

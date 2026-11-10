"""Troop profiles: numbers for every card, so the bot reasons with HP, damage, range and splash, and
generalises to cards it has never fought (owner: "the model should develop a profile for each troop").

Sources, in order:
  data/card_levels.json    game stats per level (11-16) for every card, its evo and hero forms; decoded
                           from the game client (tools/build_card_levels.py)
  bot/cards.py             hand-written traits (splash, sturdy, charge...) and owner knowledge

Our levels come from the owner's Battle Log; enemy level from towers.
"""
import json
from functools import lru_cache
from pathlib import Path

from .cards import CARDS

DATA = Path(__file__).resolve().parent.parent / "data"
TILE = 54.0
OUR_LEVELS = {"witch": 14, "golden_knight": 13, "ram": 13, "poison": 11, "log": 13, "tombstone": 13,
              "hog": 12, "minions": 13}          # owner's Battle Log, 2026-11-08
ENEMY_LEVEL = 14                                 # practice vs Devil (level-14 towers); per match later
ALIAS = {"hog": "hog_rider", "ram": "battle_ram"}   # our card keys -> card_levels.json keys
FORMS = (("evo_", "evolution"), ("hero_", "hero"))


@lru_cache(maxsize=1)
def _cards():
    cards = json.loads((DATA / "card_levels.json").read_text())["cards"]
    return {c["key"]: c for c in cards.values()}


def _entry(card):
    """card_levels.json entry for one of our card keys; evo_ / hero_ keys get that form's numbers."""
    form = None
    for prefix, section in FORMS:
        if card.startswith(prefix):
            card, form = card.removeprefix(prefix), section
    c = _cards().get(ALIAS.get(card, card))
    if c is not None and form and c.get(form):
        return next(iter(c[form].values()))
    return c


def _stats(card, level):
    """(unit record, its numbers at `level`, unit count) of the unit a card puts on the field.
    Spells that drop units (Goblin Barrel) -> the dropped unit; damage spells -> (None, {}, 0)."""
    e = _entry(card)
    if e is None:
        return None, {}, 0
    rec = e["record"]
    lv = e["levels"][str(min(16, max(11, level)))]
    if "hitpoints" in rec:
        count = rec.get("count", 1) + (rec.get("second_summon") or {}).get("count", 0)
        return rec, lv, count
    for name, unit in e.get("units", {}).items():
        drop = rec.get("projectile") or {}
        count = drop.get("spawn_character_count") if drop.get("spawn_character") == name else None
        return unit, {k.removeprefix(f"units.{name}."): v for k, v in lv.items()}, count or 1
    return None, {}, 0


def _spells():
    """Our spells at OUR level: total damage to troops, crown-tower factor, area."""
    poison, log = _entry("poison"), _entry("log")
    aoe = poison["record"]["spell"]["area_effect_object"]
    p = poison["levels"][str(OUR_LEVELS["poison"])]
    hit = p["spell.area_effect_object.buff.damage_per_hit"]
    rolling = log["record"]["projectile"]["spawn_projectile"]
    lg = log["levels"][str(OUR_LEVELS["log"])]
    return {
        "poison": {"radius_px": aoe["radius_milli"] / 1000 * TILE,
                   "damage": hit * (aoe["life_duration_ms"] // aoe["buff"]["hit_frequency_ms"]),
                   "tower_factor": p["spell.area_effect_object.buff.crown_tower_damage_per_hit"] / hit},
        "log": {"width_px": 2 * rolling["projectile_radius_milli"] / 1000 * TILE,
                "length_px": rolling["projectile_range_milli"] / 1000 * TILE,
                "damage": lg["damage"], "tower_factor": lg["crown_tower_damage"] / lg["damage"]},
    }


SPELLS = _spells()


def profile(card, level=None, ours=False):
    """Numbers for one card. Unknown card -> generic mid-size troop."""
    if card is None:
        return dict(big_shot=0.0, card=None, cost=3.5, count=1, hp=900.0, dps=150.0, range_px=1.2 * TILE,
                    speed_px=1.0 * TILE, splash_px=0.0, hits_air=True, buildings=False, known=False)
    entry = _entry(card)
    level = level or (OUR_LEVELS.get(card, 13) if ours else ENEMY_LEVEL)
    unit, lv, count = _stats(card, level)
    unit = unit or {}
    trait = CARDS.get(card, {})
    dps = lv.get("dps")
    if dps is None and unit.get("hit_speed_ms"):   # damage only on a nested projectile (Firecracker)
        dmg = next((v for k, v in lv.items() if k.startswith("projectile.") and k.endswith(".damage")), None)
        dps = dmg * 1000 / unit["hit_speed_ms"] if dmg else None
    shot = trait.get("big_shot")                   # e.g. Sparky: one charged hit every few seconds
    elixir = (entry or {}).get("record", {}).get("elixir")
    return dict(
        big_shot=float(lv.get("damage", shot) if shot else 0.0),
        card=card,
        cost=float(elixir if elixir is not None else trait.get("cost", 3.5)),
        count=count or 1,
        hp=float(lv.get("hitpoints", 0 if entry else 900)),
        dps=float(dps if dps is not None else (0 if entry else 150)),
        range_px=unit.get("range_milli", 0) / 1000.0 * TILE,
        speed_px=unit.get("speed", 60) / 60.0 * TILE,
        splash_px=unit.get("area_damage_radius_milli", 0) / 1000.0 * TILE or (1.5 * TILE if trait.get("splash") else 0.0),
        hits_air=bool(unit.get("attacks_air", trait.get("hits_air", False))),
        buildings=bool(unit.get("target_only_buildings", trait.get("buildings", False))),
        known=entry is not None or bool(trait),
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

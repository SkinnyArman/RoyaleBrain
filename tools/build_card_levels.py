"""Build data/card_levels.json: every catalog card's full game record plus its stats at levels 11-16.

    .venv/bin/python -m tools.build_card_levels <path to RoyaleSim's data/derived/cards-*.json>

Source: RoyaleSim (MIT, pypi.org/project/royalesim), whose card file is decoded from the game client's
own csv_logic tables. Download the sdist from PyPI and pass its newest data/derived/cards-*.json.
Stats there are level-1 values; the game scales every HP and damage amount as
floor(base * multiplier[level] / 100), with the multiplier table carried in each record.
The card list comes from data/cards_api.json (official API), so the output has exactly its cards.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "card_levels.json"
LEVELS = range(11, 17)  # 16 is the highest playable level (2026)

# official name -> name in the game files, where they differ
GAME_NAME = {"Ice Spirit": "Ice Spirits", "Fire Spirit": "Fire Spirits", "Royal Ghost": "Ghost",
             "Zappies": "Mini Sparkys", "Wall Breakers": "Wallbreakers", "Magic Archer": "Elite Archer",
             "Mother Witch": "Witch Mother", "Rune Giant": "Giant Buffer", "Barbarian Barrel": "Barb Log",
             "Heal Spirit": "Heal", "Giant Snowball": "Snowball", "Void": "Dark Magic",
             "Spirit Empress": "Merge Maiden"}
# cards that play as one of several separate game records
FORMS = {"Merge Maiden": ["Merge Maiden_Normal", "Merge Maiden_Mounted"]}
# absolute HP/damage/heal amounts: these scale with level; percents, times and distances do not
SCALED = {"hitpoints", "damage", "shield_hitpoints", "death_damage", "damage_special", "melee_damage",
          "damage2", "damage3", "crown_tower_damage", "push_damage", "crown_damage", "added_damage",
          "added_crown_tower_damage", "tower_damage", "heal_per_second", "crown_tower_damage_per_hit"}
# keys whose string values name another game object (a unit or an area effect): spawned troops, death
# effects, Goblin Drill's morph into its building, typed refs like "AreaEffectType:GoblinCurseBase"
REF_KEYS = ("spawn", "summon", "character", "morph", "area")
DROP = {"defaults_applied", "raw", "overlays"}


def key_of(name):
    k = "".join(ch if ch.isalnum() else "_" for ch in name.lower().replace(".", ""))
    k = "_".join(p for p in k.split("_") if p)
    return k[4:] if k.startswith("the_") else k


def clean(o):
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items() if k not in DROP and v is not None and v != [] and v != {}}
    if isinstance(o, list):
        return [clean(x) for x in o]
    return o


def refs(o, tables, found, skip):
    """Game objects referenced anywhere in a record, recursively: {"units": {...}, "area_effects": {...}}."""
    if isinstance(o, dict):
        for k, v in o.items():
            if any(s in k for s in REF_KEYS):
                for name in (v if isinstance(v, list) else [v]):
                    if not isinstance(name, str) or name == skip:
                        continue
                    name = name.split(":", 1)[-1]  # "AreaEffectType:X" -> "X"
                    for kind, table in tables.items():
                        if name in table and name not in found[kind]:
                            found[kind][name] = table[name]
                            refs(table[name], tables, found, skip)
            refs(v, tables, found, skip)
    elif isinstance(o, list):
        for x in o:
            refs(x, tables, found, skip)
    return found


def real_projectile(rec, projectiles):
    """Princess fires a visual-only "...Deco" projectile; the damage is on the same name without Deco."""
    p = rec.get("projectile")
    if isinstance(p, dict) and p.get("name", "").endswith("Deco") and p["name"][:-4] in projectiles:
        real = projectiles[p["name"][:-4]]
        rec = {**rec, "projectile": real}
        if rec.get("damage") is None and real.get("damage"):
            rec["damage"] = real["damage"]
    return rec


def find_named(o, name):
    if isinstance(o, dict):
        if o.get("name") == name:
            return o
        o = list(o.values())
    if isinstance(o, list):
        for x in o:
            hit = find_named(x, name)
            if hit is not None:
                return hit
    return None


def crown(dmg, obj):
    """Damage to a crown tower. A reduction stored as a negative delta (Fireball -77 = takes 23%) floors
    the part removed: dmg - floor(dmg * 77 / 100). A plain percent (Tornado 30) floors the part kept."""
    raw = obj.get("crown_tower_damage_percent_raw")
    if raw is not None and raw < 0:
        return dmg - dmg * -raw // 100
    pct = obj.get("crown_tower_damage_percent")
    return dmg * pct // 100 if pct is not None and pct < 100 else None


def level_stats(obj, scale, path=""):
    """Every level-scaled number in a record, plus derived dps / crown tower / per-hit values."""
    out = {}
    if not isinstance(obj, dict):
        return out
    for k, v in obj.items():
        p = f"{path}{k}"
        if k in SCALED and isinstance(v, (int, float)) and not isinstance(v, bool) and v:
            out[p] = scale(v)
        elif isinstance(v, dict):
            out |= level_stats(v, scale, p + ".")
        elif isinstance(v, list):  # e.g. Void's damage tiers, Vines' strike options
            for i, x in enumerate(v):
                out |= level_stats(x, scale, f"{p}[{i}].")
    dmg = out.get(f"{path}damage")
    if dmg is not None:
        if obj.get("hit_speed_ms"):
            out[f"{path}dps"] = dmg * 1000 // obj["hit_speed_ms"]
        c = crown(dmg, obj)
        if c is not None:
            out[f"{path}crown_tower_damage"] = c
    dps, freq = obj.get("damage_per_second"), obj.get("hit_frequency_ms")
    if dps and freq:  # damage-over-time: the game scales the per-hit amount
        hit = scale(dps * freq // 1000)
        out[f"{path}damage_per_hit"] = hit
        out[f"{path}damage_per_second"] = hit * 1000 // freq
        c = crown(hit, obj)
        if c is not None:
            out[f"{path}crown_tower_damage_per_hit"] = c
    elif dps:
        out[f"{path}damage_per_second"] = scale(dps)
    return out


def levelled(rec, tables, skip):
    ls = rec["level_scaling"]
    body = real_projectile({k: v for k, v in rec.items() if k != "level_scaling"}, tables["projectiles"])
    linked = refs(body, {k: tables[k] for k in ("units", "area_effects")}, {"units": {}, "area_effects": {}}, skip)
    calc = body
    src = (body.get("damage_source") or "").split(".")
    if len(src) == 3 and "crown_tower_damage_percent_raw" not in body:
        # the card's top-level damage is a copy of this object's: use its crown tower rule too
        origin = find_named(body, src[1])
        if origin and origin.get("crown_tower_damage_percent_raw") is not None:
            calc = {**body, "crown_tower_damage_percent_raw": origin["crown_tower_damage_percent_raw"]}
    levels = {}
    for lv in LEVELS:
        i = lv - ls["base_level"]
        if not 0 <= i < len(ls["multiplier_percent_by_level"]):
            continue
        m = ls["multiplier_percent_by_level"][i]
        scale = lambda v, m=m: int(v * m // 100)  # noqa: E731
        row = level_stats(calc, scale)
        for kind, objs in linked.items():
            for name, o in objs.items():
                row |= level_stats(o, scale, f"{kind}.{name}.")
        levels[str(lv)] = row
    waves = body.get("spell", {}).get("projectile_waves")
    if waves:  # Arrows: each wave hits the same targets once more
        for row in levels.values():
            for f in ("damage", "crown_tower_damage"):
                if f in row:
                    row[f"total_{f}"] = row[f] * waves
    return {"base_level": ls["base_level"], "record": clean(body),
            **{kind: {n: clean(o) for n, o in objs.items()} for kind, objs in linked.items()}, "levels": levels}


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    src = Path(sys.argv[1])
    data = json.loads(src.read_text())
    api = json.loads((ROOT / "data" / "cards_api.json").read_text())["cards"]
    game = {c["display_name"]: c for c in data["cards"]}
    by_form = {}
    for kind in ("evolutions", "hero_forms"):
        for f in data[kind]:
            by_form.setdefault(f["form_of"], {}).setdefault(kind, []).append(f)
    tables = {"units": data["units"], "area_effects": data["area_effect_objects"],
              "projectiles": data["projectiles"]}

    problems, cards = [], {}
    for a in api:
        gname = GAME_NAME.get(a["name"], a["name"])
        rec = game.get(gname)
        if rec is None:
            problems.append(f"{a['name']}: no game record named {gname!r}")
            continue
        elixir = a.get("elixirCost")  # None for Mirror: it costs the mirrored card + 1
        if (rec["elixir"] if elixir is not None else None, rec["rarity"].lower()) != (elixir, a["rarity"]):
            problems.append(f"{a['name']}: game says {rec['elixir']} elixir {rec['rarity']}, "
                            f"API says {elixir} {a['rarity']}")
        skip = rec.get("summon_character")
        card = {"key": key_of(a["name"]), "id": a["id"], "name": a["name"], "game_name": gname,
                "type": {"26": "troop", "27": "building", "28": "spell"}[str(a["id"])[:2]],
                "elixir": elixir, "rarity": a["rarity"], "max_level": 16,
                **levelled(rec, tables, skip)}
        if gname in FORMS:
            card["forms"] = {n: levelled(game[n], tables, game[n].get("summon_character")) for n in FORMS[gname]}
        forms = by_form.get(rec["name"], {})
        for kind, out in (("evolutions", "evolution"), ("hero_forms", "hero")):
            for f in forms.get(kind, []):
                card.setdefault(out, {})[f["display_name"]] = levelled(f, tables, f.get("summon_character"))
        cards[a["name"]] = card

    if problems:
        raise SystemExit("not written, fix these first:\n  " + "\n  ".join(problems))
    OUT.write_text(json.dumps({
        "source": f"RoyaleSim {src.name} ({data['version']}): {data['provenance']['vintage']}; "
                  "card list, ids, elixir and rarity from data/cards_api.json",
        "source_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
        "verified": False,
        "notes": [
            "record / units / area_effects: the game's level-1 values, in its own units (see conventions).",
            "levels: every HP/damage amount at that level, flattened as dotted paths into record, "
            "e.g. projectile.damage, units.Barbarian.hitpoints, area_effects.GoblinDrillDamageArea.damage. Derived: dps = damage / hit speed, "
            "crown_tower_damage, total_* (all waves), damage_per_hit / damage_per_second (damage over time).",
            "Levels 11-16 only: 16 is the highest playable level; levels below 11 are left out on purpose.",
            "Checked against statsroyale.com for 12 cards in tests/test_card_levels.py.",
        ],
        "conventions": data["conventions"],
        "cards": cards,
    }, indent=1) + "\n")
    print(f"{len(cards)} cards -> {OUT}")


if __name__ == "__main__":
    main()

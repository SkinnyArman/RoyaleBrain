"""data/card_levels.json against values copied by hand from statsroyale.com (owner, 2026-11-10)."""
import json
from pathlib import Path

DATA = json.loads((Path(__file__).resolve().parent.parent / "data" / "card_levels.json").read_text())
CARDS = DATA["cards"]


def col(*values):
    return dict(zip(range(11, 17), values))


# card -> {path in levels: {level: statsroyale value}}
STATSROYALE = {
    "Knight": {"hitpoints": col(1766, 1938, 2132, 2339, 2566, 2822),
               "damage": col(202, 221, 244, 267, 293, 323), "dps": col(168, 184, 203, 222, 244, 269)},
    "Skeletons": {"hitpoints": col(81, 89, 98, 108, 119, 130), "dps": col(73, 80, 89, 98, 108, 118)},
    "Royal Ghost": {"hitpoints": col(1152, 1264, 1390, 1525, 1674, 1840),
                    "damage": col(263, 289, 318, 349, 383, 421), "dps": col(146, 160, 176, 193, 212, 233)},
    "Barbarian Barrel": {"damage": col(215, 236, 259, 284, 312, 343),
                         "units.Barbarian.hitpoints": col(716, 786, 865, 949, 1041, 1145),
                         "units.Barbarian.damage": col(192, 210, 231, 254, 279, 306),
                         "units.Barbarian.dps": col(137, 150, 165, 181, 199, 218)},
    "Fireball": {"damage": col(688, 755, 831, 911, 1000, 1100),
                 "crown_tower_damage": col(159, 174, 192, 210, 230, 253)},
    "Arrows": {"total_damage": col(366, 402, 444, 486, 534, 588),
               "total_crown_tower_damage": col(75, 81, 90, 99, 108, 120)},
    "The Log": {"damage": col(268, 295, 324, 355, 390, 429),
                "crown_tower_damage": col(35, 39, 43, 47, 51, 56)},
    "Lightning": {"spell.area_effect_object.projectile.damage": col(1057, 1160, 1276, 1400, 1536, 1689),
                  "spell.area_effect_object.projectile.crown_tower_damage": col(265, 290, 319, 350, 384, 423)},
    "Tornado": {"spell.area_effect_object.buff.damage_per_second": col(152, 167, 183, 201, 221, 243),
                "spell.area_effect_object.buff.damage_per_hit": {11: 84},
                "spell.area_effect_object.buff.crown_tower_damage_per_hit": {11: 25}},
    "Princess": {"hitpoints": col(261, 286, 315, 345, 379, 417),
                 "damage": col(168, 185, 203, 223, 245, 269), "dps": col(56, 61, 67, 74, 81, 89)},
    "Suspicious Bush": {"hitpoints": col(81, 89, 98, 108, 119, 130),
                        "units.BushGoblin.hitpoints": col(337, 370, 407, 447, 491, 539),
                        "units.BushGoblin.damage": col(256, 281, 309, 339, 372, 409),
                        "units.BushGoblin.dps": col(182, 200, 220, 242, 265, 292)},
    # Void: damage per target and to crown towers, for 1 target / a few / many (statsroyale's 3 pairs)
    "Void": {f"spell.area_effect_object.strike_area.tiers[{t}].buff.{f}": col(*v) for t, f, v in [
        (0, "damage_per_hit", (696, 764, 840, 922, 1011, 1112)),
        (0, "crown_tower_damage_per_hit", (97, 106, 117, 128, 141, 155)),
        (1, "damage_per_hit", (307, 337, 370, 406, 446, 490)),
        (1, "crown_tower_damage_per_hit", (51, 56, 61, 67, 74, 81)),
        (2, "damage_per_hit", (153, 168, 185, 203, 223, 245)),
        (2, "crown_tower_damage_per_hit", (35, 39, 43, 47, 52, 57))]},
}


def test_every_catalog_card_is_present():
    api = json.loads((Path(__file__).resolve().parent.parent / "data" / "cards_api.json").read_text())["cards"]
    assert sorted(CARDS) == sorted(c["name"] for c in api)


def test_matches_statsroyale():
    wrong = [f"{card} L{lv} {path}: ours {CARDS[card]['levels'][str(lv)].get(path)}, site {want}"
             for card, paths in STATSROYALE.items() for path, by_level in paths.items()
             for lv, want in by_level.items() if CARDS[card]["levels"][str(lv)].get(path) != want]
    assert not wrong, "\n".join(wrong)

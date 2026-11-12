"""RoyaleSim adapter: our card names, coordinates and decks <-> the engine (royalesim, pinned).

Engine facts (measured 2026-11-10, docs/experiments.md #21):
- 20 ticks per second; arena 18 x 32 tiles; 18,000 engine units per tile (IL_Replay uses 1,000).
- Side 0 = blue = the bottom player in our views, low y; side 1 = red, high y.
- reset() takes decks (catalogue ids), card levels, evo/hero forms and tower levels.
"""
import json
from dataclasses import dataclass

import royalesim

TICKS_PER_S = 20
TILE = 18_000                     # engine units per tile
W_TILES, H_TILES = 18, 32
MATCH_TICKS = 3 * 60 * TICKS_PER_S

# our card keys (bot/cards.py) -> engine catalogue names, where they differ
ENGINE_NAME = {"hog": "HogRider", "ram": "BattleRam", "golden_knight": "GoldenKnight", "log": "Log",
               "minions": "Minions", "witch": "Witch", "poison": "Poison", "tombstone": "Tombstone",
               "evo_barbarians": "Barbarians", "elite_barbarians": "AngryBarbarians",
               "spear_goblins": "SpearGoblins", "dark_prince": "DarkPrince", "musketeer": "Musketeer",
               "valkyrie": "Valkyrie", "miner": "Miner", "wizard": "Wizard", "hero_wizard": "Wizard",
               "boss_bandit": "BossBandit", "sparky": "ZapMachine", "goblin_giant": "GoblinGiant",
               "electro_wizard": "ElectroWizard", "goblin_barrel": "GoblinBarrel", "knight": "Knight",
               "archers": "Archer", "giant": "Giant", "fireball": "Fireball", "arrows": "Arrows",
               "skeletons": "Skeletons", "zap": "Zap", "rage": "Rage", "inferno_tower": "InfernoTower"}
OUR_DECK = ["witch", "ram", "golden_knight", "hog", "poison", "log", "tombstone", "minions"]
OUR_LEVELS = {"witch": 14, "golden_knight": 13, "ram": 13, "poison": 11, "log": 13, "tombstone": 13,
              "hog": 12, "minions": 13}                  # owner's Battle Log, 2026-11-08


@dataclass
class Unit:
    uid: int
    team: int
    name: str
    x: float          # tiles
    y: float          # tiles
    hp: int
    max_hp: int
    radius: float     # tiles
    flying: bool
    tower: int        # tower slot, -1 for troops/buildings
    deploying: bool


class Sim:
    def __init__(self):
        self.b = royalesim.Battle(card_names=None, slot_of_k=[[0, 1, 2], [0, 1, 2]])
        self.catalogue = json.loads(self.b.catalogue_json())
        self.ids = {row[0]: i for i, row in enumerate(self.catalogue)}
        self.cost = {i: row[2] for i, row in enumerate(self.catalogue)}
        self.F = {f: i for i, f in enumerate(royalesim.ENTITY_FIELDS)}

    def card_id(self, key):
        """Our key ('hog'), an engine name ('HogRider') or an 'evo_' key -> (catalogue id, form)."""
        form = 1 if key.startswith("evo_") else 2 if key.startswith("hero_") else 0
        base = key.removeprefix("evo_").removeprefix("hero_")
        name = ENGINE_NAME.get(key) or ENGINE_NAME.get(base) or base
        if name not in self.ids:
            raise KeyError(f"card {key!r} -> {name!r} is not in the engine catalogue")
        return self.ids[name], form

    CARD_FEATURES = ["elixir", "count", "radius", "flying", "hitpoints", "troop", "building", "spell",
                     "hero", "champion", "footprint", "evo_cycle"]

    def card_table(self):
        """Every catalogue card as numbers (the model's 'cards as stats' input), one row per card id.
        Values from the engine's own card table at the level battles run at."""
        rows = []
        for r in self.catalogue:
            name, placement, elixir, count, radius, flying, hp, footprint, kind, variants, hero, champion, evo = r
            rows.append([elixir / 10, (count or 1) / 10, (radius or 0) / TILE, float(bool(flying)),
                         (hp or 0) / 5000, float(kind == "TROOP"), float(kind == "BUILDING"),
                         float(kind == "SPELL"), float(bool(hero)), float(bool(champion)),
                         (footprint or 0) / 4, (evo or 0) / 3])
        return rows

    def name(self, card_id):
        return self.catalogue[card_id][0] if 0 <= card_id < len(self.catalogue) else "?"

    def start(self, blue, red, blue_levels=None, red_levels=None, tower_levels=(14, 14), seed=0):
        """blue/red: 8 card keys each. levels: dict key -> level (default 14)."""
        decks, forms, levels = [], [], []
        for keys, lv in ((blue, blue_levels or {}), (red, red_levels or {})):
            pairs = [self.card_id(k) for k in keys]
            decks.append([c for c, _ in pairs])
            forms.append([f for _, f in pairs])
            levels.append([lv.get(k, 14) for k in keys])
        self.b.reset(seed=seed, decks=decks, shuffle=1, start_tick=0, elixir_milli=[5000, 5000],
                     tower_hp=None, spawns=[], forms=forms, levels=levels, tower_levels=list(tower_levels))
        return self.state()

    def state(self):
        return json.loads(self.b.state_json())

    def units(self, st):
        F, out = self.F, []
        for e in st["entities"]:
            if e[F["hp"]] <= 0:
                continue
            out.append(Unit(e[F["uid"]], e[F["team"]], self.name(e[F["card_id"]]),
                            e[F["x"]] / TILE, e[F["y"]] / TILE, e[F["hp"]], e[F["max_hp"]],
                            e[F["radius"]] / TILE, bool(e[F["flying"]]), e[F["tower_slot"]],
                            e[F["deploy_ticks"]] > 0))
        return out

    def hand(self, st, side):
        return st["players"][side]["hand"]

    def play(self, side, slot, tx, ty, ticks=1):
        """Play hand slot at tile (tx, ty) (floats, tiles), then advance `ticks`. Returns reason."""
        r = self.b.step([(side, slot, int(tx * TILE), int(ty * TILE))], ticks)
        return royalesim.DEPLOY_REASONS[r[0][1]]

    def step(self, ticks):
        self.b.step([], ticks)

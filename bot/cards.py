"""Card properties the brain reasons with. One row per card; names match recogniser labels.

Fields:
  cost      elixir
  kind      troop / building / spell
  splash    hits a group: never put swarms (Minions, Witch's Skeletons, Minion Horde...) in reach
  air       flies (only air-targeting cards can hit it)
  hits_air  can attack air units
  ranged    attacks from range (stays behind its tank: "backline")
  charge    speeds up after walking a short distance and deals double damage on its first hit;
            anything in the way takes that hit, knockback/stun resets it (The Log, Skeletons)
  swarm     made of several units
  sturdy    swarm units with real HP (Barbarians): Poison/Log don't kill them (run 010052)
  tank      high-HP front unit
  buildings targets buildings only
  speed     tiles per second (our cards, for timing pushes; unverified: speed 60 = 1 tile/s)
  champion / hero  has an ability button (Heroes: since Dec 2025, an active ability on a normal card)
Source tags: owner = from the account owner's play; community = general knowledge, unverified.
"""

C = dict  # short alias for readability

CARDS = {
    # --- our deck ---
    "hog":            C(cost=4, kind="troop", buildings=True, speed=2.0, source="community"),
    # Ram: attack AND defence (owner) - enemy troops hit it on the way, 2 Barbarians pop out and fight
    "ram":            C(cost=4, kind="troop", buildings=True, charge=True, speed=1.0, source="owner"),
    "golden_knight":  C(cost=4, kind="troop", champion=True, speed=1.0, source="owner"),
    "witch":          C(cost=5, kind="troop", splash=True, hits_air=True, ranged=True, speed=1.0, source="community"),
    "tombstone":      C(cost=3, kind="building", source="community"),
    "minions":        C(cost=3, kind="troop", air=True, hits_air=True, ranged=True, swarm=True, speed=1.5, source="community"),
    "poison":         C(cost=4, kind="spell", splash=True, source="community"),
    "log":            C(cost=2, kind="spell", splash=True, source="community"),

    # --- Devil's deck (practice opponent, owner 2026-11-09): evo_barbarians, hero_wizard, boss_bandit,
    #     musketeer, spear_goblins, dark_prince, valkyrie, miner ---
    "evo_barbarians": C(cost=5, kind="troop", swarm=True, sturdy=True, source="owner"),
    # Hero Wizard: Wizard stats + ability (Fiery Flight / Fire Wings: flies, rains fire). Unverified details.
    "hero_wizard":    C(cost=5, kind="troop", splash=True, hits_air=True, ranged=True, hero=True, source="community"),
    # Boss Bandit: 6-elixir champion, ground only, dashes (invulnerable while dashing); ability 1 elixir,
    # 2 charges: briefly invisible + teleports 6 tiles back. Weak to air (our Minions).
    "boss_bandit":    C(cost=6, kind="troop", champion=True, charge=True, source="community"),

    # --- splash troops: "your Minion Horde gets cooked by one Wizard blow" (owner) ---
    "wizard":         C(cost=5, kind="troop", splash=True, hits_air=True, ranged=True, source="owner"),
    "dark_prince":    C(cost=4, kind="troop", splash=True, charge=True, source="owner"),
    "valkyrie":       C(cost=4, kind="troop", splash=True, source="community"),
    "baby_dragon":    C(cost=4, kind="troop", splash=True, air=True, hits_air=True, ranged=True, source="community"),
    "executioner":    C(cost=5, kind="troop", splash=True, hits_air=True, ranged=True, source="community"),
    "bowler":         C(cost=5, kind="troop", splash=True, ranged=True, source="community"),
    "bomber":         C(cost=2, kind="troop", splash=True, ranged=True, source="community"),
    "firecracker":    C(cost=3, kind="troop", splash=True, hits_air=True, ranged=True, source="community"),
    "mega_knight":    C(cost=7, kind="troop", splash=True, tank=True, source="community"),
    "electro_wizard": C(cost=4, kind="troop", hits_air=True, ranged=True, source="community"),
    "bomb_tower":     C(cost=4, kind="building", splash=True, source="community"),

    # --- single-target troops ---
    "knight":         C(cost=3, kind="troop", tank=True, source="owner"),          # single target, no charge
    # Ram Rider: building-targeting Ram (the profile uses the Ram's stats) with a rider who snares
    "ram_rider":      C(cost=5, kind="troop", buildings=True, charge=True, source="community"),
    # owner's next practice deck (2026-11-09)
    "goblin_giant":   C(cost=6, kind="troop", tank=True, buildings=True, source="community"),  # Spear Goblins ride on its back
    # Sparky: slow, charges one huge splash shot (~1100 dmg base, every ~4s); ground only. Distract
    # it (a cheap unit eats the shot) or reset it with a stun/zap (owner); air units are safe from it.
    "sparky":         C(cost=6, kind="troop", splash=True, big_shot=1100, source="owner"),
    "elite_barbarians": C(cost=6, kind="troop", swarm=True, sturdy=True, source="owner"),      # 2 fast, tough Barbarians
    "heal_spirit":    C(cost=1, kind="troop", hits_air=True, source="community"),               # jumps in, heals area
    "rage":           C(cost=2, kind="spell", source="community"),                              # speeds up their troops
    "prince":         C(cost=5, kind="troop", charge=True, source="community"),     # charge, single target
    "musketeer":      C(cost=4, kind="troop", hits_air=True, ranged=True, source="community"),
    "mini_pekka":     C(cost=4, kind="troop", source="community"),
    "pekka":          C(cost=7, kind="troop", tank=True, source="community"),
    "giant":          C(cost=5, kind="troop", tank=True, buildings=True, source="community"),
    "golem":          C(cost=8, kind="troop", tank=True, buildings=True, source="community"),
    "royal_giant":    C(cost=6, kind="troop", tank=True, buildings=True, ranged=True, source="community"),
    "balloon":        C(cost=5, kind="troop", air=True, buildings=True, source="community"),
    "lava_hound":     C(cost=7, kind="troop", air=True, tank=True, buildings=True, source="community"),
    "miner":          C(cost=3, kind="troop", source="community"),
    "lumberjack":     C(cost=4, kind="troop", source="community"),
    "inferno_tower":  C(cost=5, kind="building", hits_air=True, source="community"),

    # --- swarms ---
    "barbarians":     C(cost=5, kind="troop", swarm=True, sturdy=True, source="community"),
    "goblin_gang":    C(cost=3, kind="troop", swarm=True, source="community"),
    "spear_goblins":  C(cost=2, kind="troop", swarm=True, hits_air=True, ranged=True, source="community"),
    "goblins":        C(cost=2, kind="troop", swarm=True, source="community"),
    "skeleton_army":  C(cost=3, kind="troop", swarm=True, source="community"),
    "minion_horde":   C(cost=5, kind="troop", air=True, hits_air=True, ranged=True, swarm=True, source="community"),
    "bats":           C(cost=2, kind="troop", air=True, hits_air=True, swarm=True, source="community"),

    # --- spells ---
    "fireball":       C(cost=4, kind="spell", splash=True, source="community"),
    "rocket":         C(cost=6, kind="spell", splash=True, source="community"),
    "arrows":         C(cost=3, kind="spell", splash=True, source="community"),
    "zap":            C(cost=2, kind="spell", splash=True, source="community"),
    "lightning":      C(cost=6, kind="spell", source="community"),
    "goblin_barrel":  C(cost=3, kind="spell", swarm=True, source="community"),
}


def prop(card, name):
    """Property of a card, False when the card or the property is unknown."""
    return bool(CARDS.get(card, {}).get(name, False))

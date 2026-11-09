# Game knowledge

Every fact is tagged:
- **verified**: seen in our own screenshots or logs (source given).
- **unverified**: community knowledge, memory or a website. Test it before the bot relies on it.

Stats are level 11 (2v2 caps cards at 11; the Training Camp/1v1 levels may differ, so check).

## Our deck (owner's deck, 1v1 target)

| Card | Elixir | Role | Source |
|---|---|---|---|
| Hog Rider | 4 | Win condition. Fast, jumps river, targets buildings only | cost verified (hand screenshot) |
| Battle Ram | 4 | Second win condition. Breaks into 2 Barbarians on hit/death. Card art: barbarian carrying a rock-headed log | cost verified, art identified by elimination |
| Golden Knight | 4 | Champion. Dash chains between enemies; ability button costs 1 elixir | cost verified; ability cost from owner |
| Witch | 5 | Splash, hits air, spawns Skeletons | cost verified |
| Tombstone | 3 | Building: pulls building-targeters, spawns Skeletons | cost verified |
| Minions | 3 | Air DPS, 3 units | cost verified |
| Poison | 4 | Area damage over time. **Swarm/support killer, not a tank answer** | cost verified |
| The Log | 2 | Ground rolling spell, knockback, rolls **away from us** | cost verified |

Approximate level-11 stats (RoyaleAPI `cr-api-data` base stats scaled about 10%/level, ±2%, may lag patches): **unverified**

| Card | HP | Damage | Hit speed | Notes |
|---|---|---|---|---|
| Hog Rider | ~1700 | ~320 | 1.6s | |
| Battle Ram | ~975 | ~580 charge | | 2 Barbarians: ~680 HP, ~195 dmg each |
| Golden Knight | 1800 | 160, dash 310 | 0.9s | dash chains up to 10 targets |
| Witch | ~845 | ~135 splash | 1.1s | 4 Skeletons every 7s |
| Tombstone | ~535 | | | 2 Skeletons every ~3.5s, 4 on death, lifetime 30s |
| Minions | ~233 each | ~119 each | 1.0s | |
| Poison | | ~92/s for 8s (~28/s to towers) | | large radius |
| The Log | | ~290 (~58 to towers) | | |
| Skeleton | ~83 | ~83 | 1.0s | |

## Evolutions (unverified: RoyaleAPI/Sportskeeda articles, 2024-2025)

- A deck has 2 evo slots. After the card has been played N times ("cycles"), the next copy deploys evolved, then the count resets. The card shows a purple diamond frame above it when the evo is ready (seen in screenshots, verified as a UI cue, not yet as "next deploy is evo").
- **Evo Witch** (1 cycle): every Skeleton that dies near her heals her ~109 HP (lvl 11), ~1s after death. Same base stats.
- **Evo Battle Ram** (2 cycles): Super Charge. Keeps charging and bouncing off buildings/towers until it dies; ~572 per charge hit, knockback each bounce. Countered by Log, air, ranged units (they reset it).
- Since Dec 2025 there are also **Heroes** (another upgraded card form). Behaviour unknown to us.

## Champion ability

- Golden Knight: sword button at the right edge of the screen, above the hand, costs **1 elixir** (owner). Only usable while the Golden Knight is on the field. **unverified** position (seen at about (972, 1920)) and effect: test in Training Camp.

## Elixir rules (unverified until measured from logs)

- Max 10. Single elixir: about 1 per 2.8s. Double elixir in the last 60s of regulation. Overtime has faster regen.
- **Opponent elixir counter**: the opponent's elixir is never shown. We estimate it: start value, plus regen over time, minus the cost of every card we see them play. When they are low, we attack. This is the core economic signal.
- **Positive trade**: our defence costs less than their attack (e.g. 2-elixir Log kills a 3-elixir Goblin Gang = +1).

## Towers (verified, 2v2 screenshots, 08 Nov 2026)

- Princess Tower at level 11: **3052 HP**.
- King Tower: seen at 5414, 5539, 5789 in different 2v2 matches, so it depends on the players' levels. Re-measure in 1v1.
- **1v1 is not capped at level 11** (verified, owner's Battle Log 2026-11-08): owner's cards are
  levels 11-14 in 1v1 (Witch 14, GK 13, Hog 12, Poison 11...). Tower HP and all stats in 1v1 differ
  from the level-11 numbers above. `brain.PRINCESS_MAX_HP` (3052) must be re-measured in 1v1.

## Counters for our deck (unverified, community knowledge)

| Enemy plays | Our answer |
|---|---|
| Hog, Ram, Royal Hogs, Giant, Goblin Giant (building-targeters) | Tombstone in the center pull spot, then Minions |
| Golem, Lava Hound, Electro Giant, Mega Knight, P.E.K.K.A (tanks) | Witch behind + Minions on top + Tombstone to distract. **Never Poison a tank.** Golden Knight does not duel P.E.K.K.A/Mega Knight |
| Goblin Barrel, Skeleton Army, Goblin Gang, Princess, Dart Goblin | The Log |
| Minion Horde, Bats, Skeleton Dragons, Firecracker, Furnace | Poison or Witch |
| Balloon | Minions + Witch (our weakest matchup) |
| X-Bow, Mortar | Hog/Ram straight at it, plus Golden Knight |
| Inferno Tower / Dragon | Distract with Skeletons/Minions, then Hog |

## Card interactions: what beats what, and HOW

Tags: **owner** = from the account owner's own play experience (strong prior, still test it);
**unverified** = community knowledge. Each row says the mechanism, because the bot needs the *how*
(timing, placement, trigger), not just the matchup.

| Our card | Against | How it works | When to trigger | Tag |
|---|---|---|---|---|
| Golden Knight ability (1 elixir) | Goblin Gang, Skeleton Army, any swarm | The dash chains from enemy to enemy, killing each low-HP unit it passes | Swarm clumped within dash range of the GK | owner |
| Golden Knight ability | Witch + her Skeletons | Skeletons act as stepping stones: the chain dashes through them and reaches the Witch behind them | Witch has spawned Skeletons and they are near the GK | owner |
| Golden Knight (no ability) | Goblin Gang | His normal hits + dash shred low-HP units | Placed in front of the gang | owner |
| Tombstone | Hog, Ram, Giant, Royal Giant | Building in the center pulls building-targeters off the tower; Skeletons chip it | Before the targeter crosses the bridge | unverified |
| Minions | Tanks without air attack (Golem, Giant, P.E.K.K.A) | Air DPS the tank can't hit back | On top of the tank, after its support is gone | unverified |
| The Log | Goblin Barrel, Princess, Skeletons | Rolls through, kills/knocks back ground swarms | Goblin Barrel: Log at the landing spot as it lands | unverified |
| Poison | Bats, Minion Horde, Goblins + support | Area damage kills low-HP units, slows nothing, chips tower | Swarm clumped, or a push + their tower together | unverified |
| Witch | Swarms and air | Splash + Skeleton screen | Behind our tank, never at the front | unverified |

Bot status: our own troops are tracked by their blue bars and labelled with the card we played
(`tracker.OwnDeploys`: the first new blue bar near our placement within 2.5s). The ability fires only
when our tracked GK is within `GK_REACH_PX` of an enemy that has ≥2 others within `GK_CHAIN_PX`.
Both distances are unverified guesses (~5.5 tiles): calibrate from logs.

## Owner's lessons (2026-11-08, after two practice losses)

- **Splash vs groups** (owner): splash units (Wizard, Dark Prince, Valkyrie, Executioner, Bowler,
  Baby Dragon, Bomber, Firecracker...) wipe out groups in one hit. Never send Minions/Minion Horde
  or other swarms into them. Full list with flags in `bot/cards.py`.
- **Chargers** (owner, names checked against community knowledge): Prince and Dark Prince speed up
  after a short walk and deal double damage on the first hit. Dark Prince hits a group (splash);
  Prince hits one target. Knight does not charge and hits one target. A cheap unit in the path takes
  the charge hit (Tombstone/Skeletons); The Log knocks back and resets the charge.
- **Kill the damaged support first** (owner): when a low-HP Musketeer has fresh Barbarians placed in
  front of her, hit the Musketeer (cheap spell) before dealing with the Barbarians.

## Owner's lessons (2026-11-09, after the third practice loss)

1. **Two-lane pressure.** Opponents attack both sides. Rank lanes by urgency (threat size / time to
   arrival), don't let a small push on one side block the answer to a big one on the other, and
   defend again when a push grows. (`brain.lane_threat`, `GROWTH_REDEFEND`)
2. **No dry attacks.** A lone Hog dies to anything. Attack as a package: support first (Golden
   Knight: survives splash, dash clears defenders; Minions only when no splash card can be in their
   hand), win condition right behind at the same bridge, then Poison/Log the defenders gathering
   around it. (`_supported_push`, `_support_spell`)
3. **Counter-push with survivors.** After a defence, our surviving troops walking to the bridge are
   free support: drop the win condition in front of them. (`SURVIVOR_PX`)
4. **Predict their next card.** 8-card deck, 4 in hand: once their deck is known and plays are
   identified, their hand = deck minus their last 4 plays. (`Opponent.hand_estimate`)
5. **Dual-use cards.** Battle Ram defends (enemies hit it, its 2 Barbarians fight) and then
   counter-attacks if it survives. Ram is now in the single-target defence list.

## Owner's lessons (2026-11-09, round 4)

1. **Predict the air-splash conflict.** A Wizard (or Hero Wizard) cooks Minions. Don't place Minions
   when an air-hitting splash unit is near *or can be in their hand* (cycle estimate). Ground splash
   (Valkyrie) can't hit air: Minions are fine there. (`Brain._air_splash_risk`)
2. **Poison where the swarm will walk.** Place it on the predicted path so the whole group runs into
   it; if an enemy tower is inside too, even better. Poison first when 4+ units will be caught.
   (`best_poison_spot`: predicted positions 1.5s ahead, tower = +1.5 units)
3. **Golden Knight ability on key troops.** Use it to reach and kill the annoying backline (Wizard
   behind its tank), through the dash chain, not only on big clumps. (`chain_reach`, `is_key`)
4. **Log aim.** A Log was misplaced at 26s of run 004519: it aimed at one unit whose sideways speed
   was badge jitter (300 px/s). Logs now roll through the group's center; sideways speed is capped.
5. **Evo Ram: 2 cycles** (Evo Witch: 1). The bot counts its own plays and keeps an evo-ready Ram
   for attack. (`EVO_CYCLES`)

## Owner's lessons (2026-11-09, round 5)

- **Poison must land where the group will be**, centered on the group, and only on units it kills.
  Barbarians/Evo Barbarians survive it (`sturdy`).
- **Never waste a support troop.** A Witch/GK walking up after defending is the start of a push: put
  the Hog/Ram in front of her at the bridge, and save elixir for that instead of a Tombstone on a
  minor threat elsewhere.

## Owner's lessons (2026-11-09, round 6)

1. Poison still landed wrong (106s, run 010908): the Barbarians turned to our king because our lane
   tower was down. Enemy paths now go to the king once a lane tower falls.
2. Pushing both lanes can make sense (the bot switched lanes once; owner liked it).
3. A Log that only hits a full-HP Wizard + Valkyrie is pointless. 4. A Log that also hits their tower
   is better. 5. Poison on Barbarians is right when they're low / exposed to our Witch, wrong at full
   HP: decided by value now (`bot/spells.py`), not by a fixed rule.
6. Profiles per troop so the model generalises to new interactions (`bot/profiles.py`).
7. Never place a troop where one splash (Wizard) hits it AND our tower.
8. Lure: defend so the fight happens inside our tower's range (GK met a Musketeer at the river).
9. Everything into the model: elixir, time left, their hand, how they answered our attacks this
   match (Hog -> Skeletons: next time keep Poison ready or cast it early).
10. Their deck is learned from what they play, not told.

## Heroes and champions seen (unverified details, see sources in experiments.md #6)

- **Heroes** (since Dec 2025): a normal card + an active ability triggered with a button, like a
  champion. **Hero Wizard**: same base stats as the Wizard (splash, hits air, ranged); ability
  "Fiery Flight / Fire Wings": he flies while raining fire (sources disagree on the details).
- **Boss Bandit**: 6-elixir champion, ground-only, dashes (invulnerable while dashing). Ability
  (1 elixir, 2 charges since a mid-2025 patch): briefly invisible + teleports 6 tiles back. Weak to
  air: our Minions.
- Practice opponent "Devil" (owner): Evo Barbarians, Hero Wizard, Boss Bandit, Musketeer, Spear
  Goblins, Dark Prince, Valkyrie, Miner.

## Defending specific enemy troops with our deck (unverified, community knowledge + owner input)

The bot can't use this table until it recognises enemy cards (dataset: `runs/*/enemy_units/`).
"How" is what matters: placement relative to the enemy and timing.

| Enemy | Threat | Our answer | How / where | Avoid |
|---|---|---|---|---|
| Wizard (5) | Splash, kills swarms and Minions from range | Golden Knight (dash closes the gap); Hog/Ram to their tower forces them to defend | GK dropped so his first dash target is the Wizard, or kill it after it crosses with GK + tower | Minions/Witch's Skeletons near it: one splash kills them |
| Barbarians (5), Evo Barbarians | 5 sturdy melee units, shred single tanks | Witch behind a distraction; GK ability chains through all 5; Tombstone in the middle to split them | Tombstone ~3 tiles in front of the tower so they gather on it, then Witch/GK ability while they bunch | Poison alone (they survive it at equal level); a single troop in front of them |
| Valkyrie (4) | 360° splash melee, kills Skeletons/Witch support | Minions (she can't hit air) | Minions directly on her once she commits | Tombstone/Witch alone vs her |
| Musketeer / ranged single (4) | Kills Minions, out-ranges | GK dash, Log knocks back and chips; Poison if she stands behind a tank | Engage with GK on top of her | Minions in front of her |
| Spear Goblins / Goblin Gang | Cheap swarm | The Log (+1 elixir trade) | Log from just below them (it rolls up-screen) | Spending more than their cost |
| Miner (3) | Lands anywhere, chips tower | Witch/Skeletons or GK near the tower; Log if paired with goblins | Place the answer where he surfaces, right after he lands | Ignoring him: chip adds up |
| Dark Prince / Knight / Mini tank | Medium tank | Tombstone pull + Minions | Pull to the middle, Minions on top | Golden Knight face to face with a P.E.K.K.A-class tank |
| Hog / Ram | Building-targeter | Tombstone center pull, then Minions/GK | Before it crosses the bridge | Letting it touch the tower |

## Timing: answer the arrival, not the position

- Building-targeters and tanks are often deployed **at the back** (Golem, Giant, Lava Hound,
  Electro Giant) to build a push. Reacting when they cross the bridge can be too late for some
  answers. Reacting immediately wastes elixir and lets them add support.
- The bot tracks every enemy's speed and computes the **ETA to the river**, then answers when the
  ETA drops under `LEAD_S` (2s: ~1s deploy + walk). It aims at the enemy's predicted spot 1s ahead.
- A big deploy at the back is also an **elixir signal**: they just spent a lot. Punishing the
  other lane with Hog/Ram forces them to split elixir. (Golem = 8 elixir: unverified cost, the bot
  sees "a wide health bar", not a card name, until we have a detector.)

## Opponent deck awareness

- The bot keeps an opponent model (`bot/opponent.py`): cards we know they have, and the order of
  their plays. Cards come from the owner for now (`--enemy-deck rocket,golem`), later from a detector.
- **Cycle** (unverified): 4 cards in hand + 4 in queue. A played card can't come back until 4 other
  cards have been played. So right after their Rocket, our Witch is safe from it for 4 plays.
- **Spell-safe placement**: if a known spell may be in their hand, a back-line troop (Witch) is moved
  so that one spell can't hit it and our tower together (distance ≥ 2 × radius + half a tile).
  Example (owner): Witch placed far back next to the tower, opponent Rockets both. Next time, keep
  the Witch out of that range.
- Spell radii used (unverified, tiles): Rocket 2, Fireball 2.5, Poison 3.5, Lightning 3.5, Arrows 4,
  Earthquake 3.5, Zap 2.5, Giant Snowball 2.5, Barbarian Barrel 1.3, Log 2 (width).

## Spell finish on a low tower

- Poison + Log can finish a low princess tower. Damage used (unverified, lvl 11 crown-tower damage):
  Log ~58, Poison ~220 over 8s, both ~278. The bot uses 95% of that as the limit.
- Only when it is safe: no enemy reaching the river within 3s, and we keep ≥2 elixir afterwards,
  unless the opponent is estimated at ≤3 (they can't punish either). Cheapest combo first
  (Log alone, then Poison alone, then Poison then Log).
- Tower HP is read from the bar fill (verified within ~1% on the calibration frame), times 3052
  (level-11 princess tower; check Training Camp levels).

## Placement ideas to test (all unverified)

- Center pull: a building 3-4 tiles from the river, near the middle, pulls Hog/Giant away from the princess tower.
- King tower activation: luring an enemy troop so the King Tower shoots it activates it for the rest of the match.
- Log placement: Log rolls ~10 tiles toward the enemy side, so place it just behind (our side of) the targets.
- Splitting pushes: placing a tank in the back so the opponent spends first, then counter-pushing with what survives.

## Lessons from manual play (verified, see experiments.md #0)

- A human-in-the-loop at 12-15s per move cannot play: every card landed where the enemy had been.
- Poison on a single tank wastes 4 elixir.
- Card art is easy to misread at small size: the Battle Ram was mistaken for an "Ice Golem" and played as a tank.

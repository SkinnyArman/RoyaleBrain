# Roadmap

## Direction (decided 2026-11-10)

The bot sees and acts well enough; it **decides** badly, and learning from real matches can't fix
that (~20 matches/hour, ~250 logged plays, held-out skill ~0.3-0.4). The plan is the standard one for
game AI:

1. **Perception** (screen -> state) - built.
2. **Game state** (units, HP, ETAs, elixir, cycle) - built, limited by enemy card recognition.
3. **Decision-making** - to be replaced by a policy trained in a simulator.
4. **Training** - reinforcement learning (self-play) in our own **headless Clash Royale simulator**,
   started from what real games show (TV Royale replays), never trusted beyond what replays confirm.
5. **Execution** (taps, match flow, logging) - built.

Principle: **a simulator is only as good as its agreement with the real game.** Every mechanic and
card enters the simulator together with a check against recorded replays. "Brilliant at a game that
doesn't exist" is the main risk.

The current rule brain + outcome scorer stays as the live baseline and benchmark opponent. No new
rules for it, except fixes for clear bugs.

## Phases

| Phase | Goal | Status |
|---|---|---|
| 0 | Repo, docs, knowledge base | done |
| 1 | Perception: scrcpy capture + touch, elixir, hand, badges (both teams, level-15 style), towers, ~50 fps | done |
| 2 | State: trackers, ETA/path prediction, own-troop dead reckoning, opponent cycle + response memory, card profiles | done; enemy card naming weak (27 classes, ~31% answered at ~96% precision) |
| 3 | Rule brain (baseline): value-based spells, luring, supported pushes, two-lane defence | done; frozen except bug fixes |
| L1-L2 | Decision log, outcome labels (tower damage, enemy elixir killed, wasted elixir), LightGBM scorer, learned placement spots | done; too little data to matter |
| W | Watch the owner's matches + Battle Log ground truth (results, decks) + deck-constrained labelling | done |
| L3a | TV Royale recorder (`./tvroyale N`): replays, both decks, result | done (tested live 2026-11-09); **keep running whenever the phone is free** |
| **B** | **Benchmark**: fixed Training Camp opponent, 5 matches per version, wins / crowns / tower-damage difference; every bot version is scored | **next (small)** |
| **S1** | **Simulator core**: arena grid, lanes/bridges, elixir (x1/x2/x3, overtime), timer, towers (HP, range, targeting, king activation), deploy time, 4+4 card cycle, units (move, path, retarget, hit speed, range, splash, air/ground, building-targeters) | **next** |
| **S2** | **Replay extraction + sim check** (`tools.tv_extract`, `tools.sim_check`): both sides' plays (card, spot, time) from TV recordings; re-run the same plays in the sim and compare unit paths, tower HP over time, kill times | next (with S1) |
| S3 | Cards in batches, each one validated against replays: our 8 -> the ~20-30 most common Arena 24 cards -> the rest. Evolutions, Heroes, champion abilities as separate, explicitly validated mechanics | later |
| S4 | Imitation start: policy pre-trained on replay plays (both sides, outcome-weighted) | later |
| S5 | Self-play RL in the sim (PPO or similar), our deck vs a pool of common decks; checkpoints scored by the sim AND the real benchmark (B) | later |
| S6 | Deploy: sim-trained policy behind the existing perception/execution; becomes default only if it beats the rule baseline on benchmark B | later |
| 5 | Native Android port | later |
| - | 2v2 support | owner will specify the extra considerations |

## Simulator design notes (S1)

- Headless Python + NumPy, fixed tick (e.g. 20 Hz), deterministic with a seed, no graphics. A
  debug render (OpenCV image of the grid) only for checking.
- Coordinates in tiles (18 x 32 arena); conversion to/from screen pixels lives in one place, so
  extracted replay plays map straight into the sim.
- Card data: `data/card_stats.json` (base stats, may lag patches) + `bot/profiles.py` level scaling +
  values measured from replays (`data/profiles_learned.json`). Measured values win.
- Speed target: thousands of matches per hour on the Mac, so RL is feasible without a cluster.
- Interface mirrors the live bot: `State` in, `Action` out, so policies move between sim and phone.

## Known risks

- **Sim accuracy**: stats lag balance patches; evos/Heroes/champions have special mechanics; retarget
  and collision rules are subtle. Mitigation: replay checks per mechanic and per card; nothing is
  trained on before it passes.
- **Scope**: 120+ cards. Mitigation: start with our deck and the common Arena 24 cards.
- **Expectation**: realistic target is sensible play that beats average players with our deck.
  Beating professionals depends on how close the sim gets to the real game; not promised.
- **Storage**: ~180 MB per recorded replay (datasets/tv, git-ignored).

## Useful game features

- **Practice** button on every Battle Log entry: replay against that opponent's exact deck (vs AI).
- **TV Royale**: both hands, both elixir bars, both decks (list entry), winner + crowns (end screen).

## Open questions

- Exact elixir regen rates and Training Camp card levels (measure from logs/replays).
- Golden Knight ability: exact behaviour (to model and validate in S3).
- Can unit types be read from replays well enough for S2, or does extraction need a trained detector?

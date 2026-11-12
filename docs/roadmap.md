# Roadmap

## Direction (updated 2026-11-10)

The bot sees and acts well enough; it **decides** badly, and learning from our own matches can't
fix that (~20 matches/hour, ~250 logged plays). The plan:

1. **Perception** (screen -> state) - ours, built.
2. **Game state** (units, HP, ETAs, elixir, cycle) - ours, built; limited by enemy card naming.
3. **Decision-making** - a policy trained offline replaces the rule brain.
4. **Training** - imitation on public pro replays, then self-play RL in **RoyaleSim** instead of
   building our own simulator.
5. **Execution** (taps, match flow, logging) - ours, built.

### External building blocks (found 2026-11-10, not yet verified locally)

- **RoyaleSim** (github.com/RoyaleGym/RoyaleSim, MIT, `pip install royalesim`): deterministic Clash
  Royale battle engine in Rust with Python bindings, 20 ticks/s, rules measured against recordings
  of the real client, claims all 145 cards (58 also evolved/hero). ~16k 3-minute battles per hour
  per core. Its own published accuracy (older run): non-tower units within a quarter tile 56.5%,
  exact HP 79.5%; single units good, swarms weaker. Part of a stack (RoyaleGym environment,
  RoyaleLearn, RoyaleLive). Our `data/card_levels.json` already comes from its decoded game data.
- **IL_Replay** (huggingface.co/datasets/VanguardX101/IL_Replay): 252,238 replays, 17.8M plays,
  mostly Path of Legends. Per play: side, card, 20 Hz tick, exact tile coordinate (RoyaleSim's
  units); per replay: both decks with levels, result. **No license stated** - fine for a personal
  experiment, check before any public use.
- **ClashAI** (github.com/vegetableleaf/ClashAI): the same recipe (IL_Replay imitation -> PPO in
  RoyaleSim, opponent-elixir estimate from public events) for one deck. Reported ladder results:
  14,060 trophies after 4,499 games (51.5%), Ranked 33-48% over 150-629 games, 166 model versions.
  **No license**: read it for ideas, don't copy code. It is the reference to compare against.

Principles:
- **Verify before building on it**: our deck loads, speed on this Mac, one of our recorded matches
  replayed in RoyaleSim and compared.
- **Train on what the phone sees**: policy inputs = what live perception provides (enemy cards often
  unnamed, their elixir estimated), never the simulator's perfect state.
- **Learn what wins**: replay plays weighted by outcome; never "copy the owner".
- The rule brain stays as the live baseline and benchmark opponent; bug fixes only.

## Phases

| Phase | Goal | Status |
|---|---|---|
| 0 | Repo, docs, knowledge base | done |
| 1 | Perception: scrcpy capture + touch, elixir, hand, badges (both teams, level-15 style), towers, ~50 fps | done |
| 2 | State: trackers, ETA/path prediction, own-troop dead reckoning, opponent cycle + response memory, card profiles from game data | done; enemy card naming weak (27 classes, ~31% answered at ~96% precision) |
| 3 | Rule brain (baseline): value-based spells, luring, supported pushes, two-lane defence | done; frozen except bug fixes |
| W | Watch the owner's matches + Battle Log ground truth (results, decks) + deck-constrained labelling | done; optional data |
| L3a | TV Royale recorder (`./tvroyale N`) | done; optional (checks at our arena/level) |
| ~~L1-L2~~ | ~~Outcome scorer on our own matches (LightGBM, features, placements)~~ | **removed 2026-11-10** (experiments #20) |
| ~~S1-S2~~ | ~~Own simulator + TV Royale extraction~~ | **dropped**: RoyaleSim + IL_Replay instead |
| V | Verify RoyaleSim + IL_Replay locally | **done** (experiments #21): our deck loads, ~75k battles/h/core, 99% of replay plays accepted, open-loop winner agreement 60% |
| **B** | **Benchmark**: fixed Training Camp opponent, 5 matches per version, wins / crowns / tower-damage difference | next (small) |
| R1 | Replay pipeline: IL_Replay plays -> RoyaleSim -> samples (`tools.fetch_replays`, `tools.build_dataset`) | **in progress**: 29/52 shards downloaded, building (#23) |
| R2 | Bridge: our screen pixels <-> RoyaleSim tile coordinates; our live `State` <-> the policy's observation | after V |
| R3 | Imitation: network predicts card, tile, timing (or wait) from the visible state, outcome-weighted; a win-probability model alongside | after R1-R2 |
| R4 | Self-play RL (PPO) in RoyaleSim: our deck vs a pool of real replay decks, starting from R3; scored in the sim and on benchmark B | later |
| R5 | Deploy: trained policy behind our perception/execution; default only if it beats the rule baseline on B | later |
| 5 | Native Android port | later |
| - | 2v2 support | owner will specify the extra considerations |

## How we try to beat ClashAI (all decks, not one)

Same base recipe (replay imitation -> RL in RoyaleSim), plus:

1. **One generalist for every deck, with cards as numbers.** ClashAI's generalist knows cards by
   identity embeddings (a name vocabulary). We feed each card's stats from `data/card_levels.json`
   (HP, DPS, range, splash, speed, targets, cost, form) next to its identity, so new cards, evos,
   Heroes and balance patches start from sensible behaviour instead of zero.
2. **Decision-time search on a simulated copy of the live board.** `reset(spawns=...)` can rebuild
   the board from our perception (units, HP, towers, elixir). At ~100 engine ticks per ms, a 0.5s
   decision budget allows ~100-200 short rollouts of the policy's top candidate moves, scored by the
   value model: policy + value + search, AlphaZero-style. ClashAI built a search prototype but
   doesn't report using it. Needs the opponent's hidden hand sampled from the hand belief.
3. **Short-horizon training from replay states.** Open-loop replays diverge (#21), so instead of
   trusting full replayed matches: start the sim from many real mid-match states and learn values /
   moves over the next seconds, where the sim is accurate.
4. **Evolutions and Heroes from day one** (the engine now plays 58 forms; ClashAI's earlier runs
   played evolved cards as base cards).
5. **Deck choice**: a generalist lets us pick the strongest deck for our levels and the meta.
6. **Robustness to sim error**: randomise unit stats / timings slightly during RL so the policy
   doesn't exploit engine quirks.

Where we are BEHIND and must catch up: perception (ClashAI has a 230-class detector; our recogniser
names ~31% of units) and compute (they train on several GPUs; we have a Mac - serious RL needs rented
GPU time).

## Known risks

- **Sim-to-real gap**: RoyaleSim is measured but not exact (swarms, collisions, deaths); balance
  patches move numbers. Mitigation: replay our own recorded matches in it; prefer cards and
  interactions its parity tables show as accurate.
- **Perception gap**: live we see less than the simulator (unnamed enemy cards, estimated elixir).
  Mitigation: train only on visible inputs, with realistic noise.
- **Moving dependencies**: RoyaleSim releases almost daily (0.1.x). Pin a version per experiment.
- **Data rights**: IL_Replay has no license; ClashAI has no license (ideas only).
- **Expectation**: ClashAI, further along on the same recipe, reports ~33-48% in Ranked. Matching
  it is a realistic stretch goal; beating top players is not promised.
- **Storage**: IL_Replay ~1.9 GB; TV Royale recordings ~180 MB each (git-ignored).

## Useful game features

- **Practice** button on every Battle Log entry: replay against that opponent's exact deck (vs AI).
- **TV Royale**: both hands, both elixir bars, both decks (list entry), winner + crowns (end screen).

## Open questions

- Golden Knight ability and our other cards: how accurate is RoyaleSim for them (parity tables)?
- How many IL_Replay games include our cards / similar decks, at levels close to ours?

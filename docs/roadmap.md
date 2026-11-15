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
| R1 | Replay pipeline: IL_Replay -> RoyaleSim -> samples (`tools.fetch_replays`, `tools.build_dataset`) | **done** 2026-11-12: 251,291 matches (947 skipped), 37.1M samples, 13.4M plays incl. 583k ability presses (#23, #25). `./build` |
| **R3** | **First model (imitation + value)**: transformer over units / scalars / hand, cards as stats + identity; heads: wait, card, tile, win probability; enemy ids randomly hidden like live; trained on the Mac GPU | **done**: models/r3.pt, card 64.7%, tile within 1 48.0% held-out (#27) |
| **SB** | **Sim benchmark**: model plays our deck vs held-out real decks in RoyaleSim, watchable in `tools.sim_watch`; the rule brain is the baseline. Every change must move this number | **done**: r3 47.5% vs rules 30.5% vs random 15% (#27) |
| **R6** | **Decision-time search** (bot/search.py): copy the battle, play the model's top moves a few seconds forward, keep the best. Main edge over ClashAI | **in progress**: v1 no gain (#29); scored by real outcome: **84.0% vs 52.5%** (#30), not yet tested against an unpredictable opponent. See "Where we stopped" |
| **R2** | **Phone bridge**: `./play --model models/r3.pt` plays live (bot/live_model.py, #34-#36); recognition 71% on the practice deck; spell safety rules as a stopgap | **in progress**: 5 practice matches lost; next: search on the phone |
| **B** | **Phone benchmark**: fixed Training Camp opponent, 5 matches per version, wins / crowns / tower-damage difference | with R2 |
| R5 | Deploy: model (+ search) behind our perception/execution; default only if it beats the rule baseline on B | after R2/B |
| R4 | Self-play RL (PPO) in RoyaleSim vs a pool of real decks, starting from R3; scored in the sim and on B. Needs a rented GPU | later |
| 5 | Native Android port | later |
| - | 2v2 support | owner will specify the extra considerations |

## Where we stopped (2026-11-13): open problems, next steps

Scoreboard: `./bench <player> --vs models/r3.pt` (200 held-out pro decks, model-played, level 14 both
sides). rules 23.5%, r3 52.5%, r3 + search v1 55.0% (#28, #29).
**Update 2026-11-14 (#30):** search scored by real outcome (towers + material), model decides when,
12 s look-ahead: **84.0%** (p < 1e-10 vs r3). Shortcoming 1 below is fixed by that; 2 and 3 now matter
most. Against an opponent it can't predict (`--vs sample:models/r3.pt`): search 84.5% vs plain r3
61.5% (+23 points, p < 1e-8): mostly real. Remaining edge: it reads the opponent's hand/elixir from the
engine; on the phone they are tracked (elixir count, card cycle: known once all 8 seen), so only unseen
cards early on and missed detections are unknown (AGENTS.md). Variants B (search
decides timing) and C (value score + model timing) not run: wait for the owner's go.

Shortcomings, most important first:
1. **Search v1 doesn't clearly help** (52 vs 47 matches won one way or the other, p = 0.69). It plays
   ~30% more cards. Suspected cause: it scores futures with r3's value head, the weakest output
   (winner 59.6% held-out, trained on final results of drifting pro re-simulations), so 6 s ahead it
   can't tell a good move from a busy one.
2. **The search reads the opponent from the engine**: it copies the exact battle, incl. the opponent's
   hand and elixir. On the phone it must rebuild the board from what is seen (`reset(spawns=...)`), with
   the opponent's elixir COUNTED from seen plays (capped at 10 continuously) and the hand TRACKED
   through the cycle (exact once all 8 cards are seen); only unseen cards are sampled. Not built.
   The elixir-count cap bug is fixed (#31).
3. **The benchmark opponent is the search's own rollout policy** (deterministic r3), so rollouts
   predict its replies exactly. Use `--vs sample:models/r3.pt` (seeded sampling) for honest numbers
   once search helps; not run at full scale yet.
4. **Model timing is weak**: play/wait 70.1%, flat through training (#27).
5. **Engine bug**: RoyaleSim 0.1.51 can't reload some snapshots with a Bowler on the board (~0.2% of
   decisions; the plain move is played instead). Worth reporting upstream.
6. **Benchmark limits**: simulator, not phone; the rule brain gets perfect vision; the blind-replay
   opponent is too easy at equal levels (85-95%), keep it as a sanity check only.
7. **Rule brain Log bug** (live too): its tower-finish Log targets past the bridge, illegal in the real
   game (#26). Brain is frozen as the baseline; not fixed.

Next (updated 2026-11-14):
1. DONE (#30): futures scored by what happened (towers + material), model decides when, 12 s look-ahead.
   Best player: `./bench search:models/r3.pt --vs models/r3.pt --score outcome --timing model --horizon 12`.
2. Tracked-opponent search, still in the sim: rollouts start from what the phone would know: the
   opponent's elixir COUNTED (capped at 10 continuously: DONE 2026-11-15, #31) and
   hand TRACKED through the cycle (tracker DONE 2026-11-15: `Opponent.queue/certain_hand/sample`, #32);
   sample only cards not seen yet. DONE 2026-11-15 (#33): honest search 73.5% vs r3, 81.0% vs
   sample:r3 (plain r3 52.5% / 61.5%). Possible next: a deck prior for unseen cards; several guesses averaged.
3. R2: the phone bridge (board from the screen -> `reset(spawns=...)`), with reliable enemy-card
   recognition (missed plays break the elixir count and the cycle), then B in Training Camp.
4. Learned value from simulator self-play (r3 vs r3, exact outcomes) to replace the hand-made score;
   the same machinery starts R4.
Not run: variant C (value score + model timing), not needed after B (#30).

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

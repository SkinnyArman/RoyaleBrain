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
| **SB** | **Sim benchmark**: model plays our deck vs held-out real decks in RoyaleSim, watchable in `tools.sim_watch`; the rule brain is the baseline. Every change must move this number | **done**: equal levels, vs r3: rules 23.5%, r3 52.5% (#28) |
| **R6** | **Decision-time search** (bot/search.py): copy the battle, play the model's top moves a few seconds forward, keep the best. Main edge over ClashAI | **done in the sim**: honest search 73.5% vs r3 / 81.0% vs sample:r3 (plain r3 52.5% / 61.5%) (#30-#33); on the phone: next (see "Where we stopped") |
| **R2** | **Phone bridge**: `./play --model models/r3.pt` plays live (bot/live_model.py, #34-#36); recognition 71% on the practice deck; spell safety rules as a stopgap | **in progress**: 5 practice matches lost; search on the phone built + tested offline (#37): next a match with `--search` |
| **B** | **Phone benchmark**: fixed Training Camp opponent, 5 matches per version, wins / crowns / tower-damage difference | with R2 |
| R5 | Deploy: model (+ search) behind our perception/execution; default only if it beats the rule baseline on B | after R2/B |
| R4 | Self-play RL (PPO) in RoyaleSim vs a pool of real decks, starting from R3; scored in the sim and on B. Needs a rented GPU | later |
| 5 | Native Android port | later |
| - | 2v2 support | owner will specify the extra considerations |

## Where we stopped (2026-11-16 evening): handoff for the next agent

Read AGENTS.md first (rules, owner preferences, commands), then docs/experiments.md #21-#40.

### State
- Model `models/r3.pt` (git-ignored; retrain with `./train` from `./build` data if missing): transformer
  imitation + value net on 251k pro replays (#24-#27).
- Simulator scoreboard (`./bench`, 200 held-out pro decks, level 14 both sides): rules 23.5%, r3 52.5%,
  r3 + search 84.0% (sees everything), **r3 + honest search 73.5% vs r3 / 81.0% vs sample:r3** (#28-#33);
  search deciding timing too: 54% (#40, not used).
  Best: `./bench search:models/r3.pt --vs models/r3.pt --score outcome --timing model --horizon 12 --honest`.
- Phone: best is `./play --model models/r3.pt --search` (#37-#40): the live board is rebuilt in RoyaleSim
  (bot/rebuild.py: units with their badge-read levels, towers, both elixirs, both cycles), search picks
  what + where on a worker thread when the model's gate says play. 8 Training Camp matches vs one bot
  deck (Golden Knight, evo Mega Knight, evo Witch, Giant Snowball, Skeleton Dragons, Void, Skeleton Army,
  Minion Horde), all lost; matches 7-8 (search) took a tower / did the most damage so far.
- Perception fixed today: ghost "enemy" on our tower tops masked; enemy levels read from badges
  (bot/levels.py, never wrong on its labelled set); hand reader no longer misreads greyed cards
  (0 duplicate frames on 8 recordings). Recognition: 80% on this deck's cards, does not scale to 120+
  cards (needs a trained detector, later).
- **Main weakness now: WHEN to play.** The model's gate says wait while a tower dies with 4-6 elixir in
  the bank (match 8, 0:28-0:41). Owner, 2026-11-16: next focus is making the MODEL smarter, not image
  recognition.
- Hand-written spell safety rules in bot/live_model.py still apply to the plain path only (skipped with
  `--search`). Owner dislikes hard-coding: remove them once `--search` is the default.

### Next, in order
0. **The model's timing** (owner's next focus): find why the gate says wait in states like match 8
   0:28-0:41 (phone logs + the same states in the sim vs what pros do), then improve the gate (training
   targets / features / fine-tuning) and measure on the SB scoreboard and one phone match.
1. **Search on the phone**: built. a-c DONE 2026-11-16 (#37): `./play --model models/r3.pt
   --search` (bot/rebuild.py; compare offline with `.venv/bin/python -m tools.search_replay runs/<id>`).
   Offline it avoids 4 of the 5 mistakes checked; search takes 75-300 ms. Match 6 with `--search` (#38):
   lost, caused by a vision ghost on our towers and every unnamed enemy rebuilt as a Golden Knight; both
   fixed. Match 7 (#39): lost 1-3, took a tower; fixed after it: enemy levels READ from the badges
   (bot/levels.py), hand reader no longer misreads greyed cards. Match 8 (#40): lost on TIMING (the
   gate said wait while a tower died); search deciding timing scored 54% in the sim (vs 73.5%): not
   used. NEXT: the model's timing (owner, 2026-11-16: focus on the model, not image recognition).
   Recognition at scale (120+ cards) needs a trained detector (e.g. from game sprites), not more
   nearest-neighbour pictures: a separate project, later. The original plan, for reference:
   a. Board rebuild: live State -> a RoyaleSim battle via `reset(spawns=...)` / `unit_spawns` (see the
      engine docstring for `reset`): enemy units by recognised card; unknown ones as the most likely
      card (their seen deck, else catalogue prior); our troops from vision + OwnDeploys estimates
      (full-HP allies have no badge); tower HP from vision (king 1.0 unless read); both elixirs (ours from
      vision, theirs from economy.EnemyElixir / tools.build_dataset.ElixirCount); our hand + next card;
      their hand/queue from the cycle tracker (bot/opponent.Opponent.sample, AGENTS.md "tracked, not
      guessed"). Card ids: bot/live_model.ModelPolicy.cid. Pixels <-> tiles: bot/sim.to_px/to_tile.
   b. Decide: when the model's gate says play, bot/search.Search (score="outcome", timing="model",
      horizon 12 s) picks what + where from that rebuilt battle; keep the 0.5 s budget (sim search is
      ~17 ms/decision, the rebuild adds to it: measure and log ms).
   c. Test offline first on the recordings: `.venv/bin/python -m bot.main --frames runs/<id> --model
      models/r3.pt` (runs 20261115-112539, -114941, -120115, -121938, -122231). Check the three judgment
      mistakes above. Then the owner plays a match; label afterwards (step 2).
   d. Then remove the spell safety rules and compare.
2. **Labelling round after every match** (owner, ~5 min): routine in AGENTS.md. Rounds 3-5 (#38, #40):
   this deck's cards 71% -> 80% leave-one-out (81% -> 83% restricted to the deck) with 114 -> 295
   pictures; Mega Knight (5/12) and evo Witch (14/23) are still weak. Named tracks counted as spawns never join their deck
   (#38): fix with care (the class "skeletons" is the Skeleton Army card here).
3. **Enemy play counter**: still overcounts (54 "plays" in match 3). Spawn rule = tracker.is_spawn.
   Ideas: their Skeleton Army skeletons were level 13, the Witch's level 15 (badge digits are now read:
   Track.level, #39; use it here);
   detect spells (owner: Void = red thing dropping from the sky leaving a hole); the opponent's plays
   show a level banner (no name).
4. **Public repo** (an outside watcher since 2026-11-15): anonymise other players' names in docs/run
   notes, decide on game screenshots in datasets/enemy_units, add LICENSE + README. Ask the owner first.
5. Later: learned value from sim self-play to replace the hand-made outcome score (starts R4); a deck
   prior for unseen cards; several guesses averaged in honest search.

### Known problems (not blocking)
- Model timing is weak (play/wait 70%, #27); search covers what/where, the gate still decides when.
- RoyaleSim 0.1.51 can't reload some snapshots with a Bowler (~0.2% of searches fall back), #29.
- The benchmark opponent is r3 itself; use `--vs sample:models/r3.pt` too (#30).
- Rule brain Log bug (frozen baseline, not fixed), #26.

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

# cr-bot

A Clash Royale bot, built as a technical experiment. It reads the screen of an Android phone
over USB, decides what to play, and taps. Current target: **1v1, Training Camp** (vs the in-game AI).
2v2 has extra rules that are not designed yet; do not optimise for it.

The account owner accepts the ban risk. Develop and test in **Training Camp only**, so that
half-working builds never spoil real players' matches.

## Read first

| Doc | What's in it |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Pipeline, modules, latency budget, why PC first and native later |
| [docs/calibration.md](docs/calibration.md) | Screen coordinates, colors, templates, how each was measured |
| [docs/game-knowledge.md](docs/game-knowledge.md) | Cards, evos, abilities, elixir rules, counters, placements, with confidence level |
| [docs/experiments.md](docs/experiments.md) | Log of every test run: question, setup, result, what changed in the bot |
| [docs/roadmap.md](docs/roadmap.md) | Phases, what's done, what's next |

## Commands

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # once
.venv/bin/python -m tools.grab --cards      # screenshot + hand-slot crops into shots/
./play                                      # wait for a match, play it with the rule brain (baseline), stop at the end
./play --dry-run                            # same, but never tap (watch + log only)
./play --tower-hp 4032                      # optional match info
./watch 5                                   # watch the OWNER play 5 real matches (never taps), battle log, report
./tvroyale 10                               # from the main page: record 10 TV Royale replays (both sides)
.venv/bin/python -m tools.battlelog         # true results + both decks for recent runs (needs .env)
.venv/bin/python -m tools.label_run runs/<id> --single   # label enemy crops against the real deck
.venv/bin/python -m tools.report --since <run>   # results per match
.venv/bin/python -m pytest -q               # tests (offline, saved frames); needs `pip install pytest`
# without pytest: .venv/bin/python -c "import tests.test_offline as t; [getattr(t,n)() for n in dir(t) if n.startswith('test_')]"
```

Card data lives in `data/`: `cards_api.json` (official catalog: refresh with
`CR_API_TOKEN=... .venv/bin/python -m tools.fetch_catalog`; never commit a token), `card_levels.json` (every catalog card's full game record + all stats at
levels 11-16, incl. spawned units, evolutions, hero forms; decoded from the game client by RoyaleSim,
MIT: download its sdist from PyPI and run `.venv/bin/python -m tools.build_card_levels
<sdist>/data/derived/cards-<newest>.json`; checked against statsroyale in tests/test_card_levels.py). `bot/profiles.py` reads it.

Growing the enemy recogniser: after a match, look at `runs/<id>/enemy_units/*.png`, copy clear
crops into `datasets/enemy_units/<card_name>/` (names = keys in `bot/cards.py`), then run
`.venv/bin/python -m tools.eval_recognizer` and record the leave-one-out result in experiments.md.

The phone must show up in `adb devices`. Device: Galaxy S20 FE, 1080x2400. All coordinates are
in that resolution; another phone needs recalibration (see docs/calibration.md).

## Direction (owner, 2026-11-09, updated 2026-11-10): a learning system, not an if/else script

The bot must make data-driven decisions using information humans can't track while playing (exact
elixir and cycle, HP, ETAs, statistics over many games).

- **Perception + execution are ours** (screen -> State -> taps). **Decisions will come from a policy
  trained offline**: imitation from public pro replays (VanguardX101/IL_Replay on Hugging Face:
  252k replays, every play with side, card, tick and exact tile), then self-play RL in RoyaleSim
  (MIT Clash Royale battle engine, measured against the real client). Both still to be verified
  locally before we build on them (docs/roadmap.md).
- **The policy learns what WINS, not who played it.** Replay plays are weighted by outcome; the
  owner's own matches are never targets to copy.
- **Train on what the phone can see.** The policy's inputs must be what live perception provides
  (enemy card names often unknown, their elixir estimated), not the simulator's perfect state.
- **Cards are numbers, never names, inside the model** (owner: "I can't give you every variation";
  there are 120+ cards). Every card enters as its stats; patterns must transfer between cards and the
  input size must not grow with the number of cards.
- The rule brain (`bot/brain.py`) is frozen: it is the live baseline and the benchmark opponent.
- Removed 2026-11-10 as obsolete: the outcome scorer trained on our own matches (features.py,
  outcomes.py, placements.py, train_policy.py, BlendPolicy, backfill, ./note) and the old
  cr-api-data stats. Rationale in docs/experiments.md #20.

## Current plan (2026-11-10)

See docs/roadmap.md. Next: verify RoyaleSim (our deck loads, speed, one of our recorded matches
replayed) and the IL_Replay data, then benchmark (B), replay -> simulator pipeline, imitation, RL.

## Rules for agents

1. **Knowledge lives in files, not in your head.** Whatever you learn (a measured coordinate, a
   placement that works, a rule that failed), write it into the matching doc in the same change.
   Mark game facts as `verified` (seen in our own logs/screenshots, say where) or `unverified`
   (community knowledge, memory, a website). Never upgrade a fact to verified without evidence.
2. **Every behaviour change to the bot is backed by an experiment** recorded in docs/experiments.md:
   the question, the setup, the numbers, the decision.
3. **Elixir economy is the core strategy.** Prefer the play that wins the elixir trade. Track both
   our elixir and the opponent's estimated elixir; punish when they are low.
4. Keep the per-frame loop fast. Measure (`ms` is printed per frame) before and after any change
   to capture, vision or input. State the numbers in the commit.
5. Small modules, no framework. Python 3, OpenCV, NumPy. Ask before adding a dependency.
6. Tests run offline against saved frames in `tests/frames/`; never need a phone.
7. Commit messages: conventional commits (`feat(vision): ...`). No AI attribution lines.

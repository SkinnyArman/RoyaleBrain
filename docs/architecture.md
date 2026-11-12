# Architecture

```
phone ──H.264──> scrcpy server ──adb socket──> pump thread ──> ffmpeg (own process) ──BGR──> latest frame
                                                                                              │
          ┌───────────────────────────────────────────────────────────────────────────────────┘
          v
   vision.elixir / vision.hand / vision.enemies ──> Tracker (IDs, speed, ETA, new plays) ──> EnemyElixir
          │                                                              │
          └───────────────────────────> Brain.decide <───────────────────┘
                                             │
                     FastDevice.play  <──────┘   (32-byte touch messages on the scrcpy control socket)
                                             │
                                         Recorder  ──> runs/<timestamp>/log.jsonl + frames/
```

## Decision loop (learning foundation, 2026-11-09)

```
frame -> vision/trackers -> State (bot/state.py, serializable)
                             |
                             v
        candidates(State) = WAIT + ability + every playable card x grid cell (bot/actions.py)
                             |
                             v
        Policy.score(State, candidates) -> choose best (bot/policy.py)
            RulePolicy  = the rule brain (live baseline)                         <- now
            Trained     = imitation on pro replays + RL in RoyaleSim         <- planned (roadmap)
                             |
                             v
        execute + DecisionLog: runs/<id>/decisions.jsonl (State + action + policy per decision point)
```

- Grid: one cell per tile on our side for troops/buildings (18 x 10 = 180 cells), 2-tile cells over
  the whole arena for spells. Rule/human placements are snapped to a cell to become labels; the rule
  policy still executes its exact pixel spot.
- Decision points logged: every play, plus a WAIT state every 0.5s (so "not playing" is in the data).
  ~1.6 KB per line, ~0.6 MB per match. Candidates are rebuilt from the State when training.
- `--frames runs/<id>` replays a recorded match through the whole loop offline (frame timestamps as
  the clock; output in runs/replays/). It checks the pipeline; it can't evaluate a policy, because the
  recorded frames don't react to the bot's moves.

## Removed 2026-11-10

The outcome scorer trained on our own matches (`features.py`, `outcomes.py`, `placements.py`,
`tools/train_policy.py`, `BlendPolicy`, `tools/backfill.py`, `./note`) and the old cr-api-data stats
were removed: a few hundred self-played moves can't train a decision model, and pro replays + a
simulator replace them (docs/experiments.md #20; git history has the code).

## Modules (bot/)

| File | Job |
|---|---|
| `fastdevice.py` | scrcpy v5.0.1 server: video stream in, touch events out. Protocol taken from the v5.0.1 server source (`ControlMessageReader.parseInjectTouchEvent`, `Options` `raw_stream`/`send_dummy_byte`, `DesktopConnection`). |
| `device.py` | Fallback: `adb exec-out screencap` (raw, no PNG) + `input tap` via one persistent shell. Use with `--slow`. |
| `layout.py` | Every screen coordinate, for 1080x2400. |
| `vision.py` | Elixir from the pink bar, hand by template matching, troop bars for both teams (position, width, HP %), tower HP from bar fill, champion button, `StaticFilter` (learns arena decorations that look like bars). |
| `tracker.py` | Tracks for both teams: ID, smoothed velocity, ETA to a line, predicted position, new-unit groups (= plays). `OwnDeploys` labels our own tracks with the card we played. |
| `cards.py` | Card properties (cost, splash, air, hits_air, ranged, charge, swarm, tank, buildings) with a source tag. |
| `recognizer.py` | Enemy card from a unit crop: nearest neighbour over `datasets/enemy_units/<card>/`, color histogram + shape thumbnail, answers None when unsure. |
| `state.py` | `State`/`Unit`: the serializable snapshot every policy gets and every decision logs. |
| `actions.py` | Fixed action space: WAIT, ability, card x grid cell; `snap` maps any placement to a cell. |
| `policy.py` | `Policy` (score candidates, choose best), `RulePolicy` (rules as scores), `DecisionLog`. |
| `profiles.py` | Troop profiles: HP/DPS/range/speed/splash/count per card at the right level, from `data/card_levels.json` (game stats at levels 11-16, incl. evo and hero forms). Our spells' damage, area and tower factor come from the same file. |
| `spells.py` | Log/Poison value in elixir (kills incl. units our troops will finish, chip, tower damage) and the best cast spot. Spells are cast only when worth their cost. |
| `observer.py` | Watch mode: detects the owner's plays (card leaves the hand + elixir drop; spot = the pink cost drop + offset) and logs them as `policy: human` decisions. Runs in shadow during bot matches (`shadow.jsonl`) to measure its own accuracy. |
| `sim.py` | RoyaleSim adapter (engine pinned in requirements.txt): our card keys -> engine names, decks/levels/forms, units in tiles, play/step. |
| `framedevice.py` | Offline replay of a run's frames (`--frames`). |
| `opponent.py` | Opponent model: known cards, play order (cycle), spells possibly in hand, spell-safe placement. |
| `economy.py` | Opponent elixir estimate. Regen rate learned from our own bar, so double/triple elixir needs no timer. |
| `brain.py` | Rules in priority order: queued follow-up (Log after Poison), GK ability from the GK's tracked position, defend by ETA (cheapest fitting card, aimed at the predicted spot, spell-safe), spell finish on a low tower when safe, punish big back deploys in the other lane, attack from 9+ elixir or when the opponent is low. |
| `recorder.py` | Logs every frame's state and decision; saves half-res frames (dataset for a future detector). |
| `main.py` | The loop. Only processes newly decoded frames. |

## Latency budget (targets; measure and record real numbers in experiments.md)

| Step | screencap path | scrcpy path | native (phase 5) |
|---|---|---|---|
| capture | 200-500ms (unmeasured) | ~35-70ms encode+transfer+decode | ~16-30ms |
| vision | ~10-20ms | same | ~20-40ms on phone |
| input | ~100ms (`input tap` starts a JVM) | ~1-5ms socket write | ~10-50ms gesture |

The game itself adds ~1s deploy time to every card, so decision quality matters more than the
last 30ms.

## Measured

- Live, run 235339: 95ms per frame with full hand matching every frame -> ~11ms with the per-slot
  cache (offline measurement; a slot that changes costs ~21ms once).

- Vision per full-res frame (M-series Mac, `calib/battle_7elixir.png`): 34.8ms with NumPy masks ->
  **14.2ms** after sharing one HSV conversion and using `cv2.inRange` (2026-11-08).

## Why Python, not Rust (decided 2026-11-08, revisit with measurements)

The expensive work per frame is not Python: video encode/decode (phone hardware + ffmpeg, C),
image ops (OpenCV/NumPy, C++), and later a detector (ONNX/CoreML). Python glue is an estimated
1-3ms per frame. A Rust rewrite would save a few ms and slow down every experiment. Rule: profile
on the phone first (`ms` per frame is logged). If a Python step shows up as a real cost, port that
step (or do it in the native phase 5 app), not the whole bot.

## Why PC first, native later

The PC gives fast iteration, full logs, a debugger and a GPU for training. A native Android app
(MediaProjection capture, TFLite model, AccessibilityService `dispatchGesture`) removes the cable
and ~30ms, but every change means a rebuild and it competes with the game for the phone's CPU and
heat budget. Port once the logic is stable.

## Known limitations

- Enemy card identity is unknown: every enemy play costs 3.5 in the estimate, and spells (no
  health bar) are not seen. Fix: train a detector on `runs/*/frames`.
- Tower HP is not read yet.
- The tracker treats every bar seen on the first frame as a new play; start the bot before the match.
- Units are found by level badge. Our own units at full HP show no badge, so our troops are only
  seen once damaged; the Golden Knight's position falls back to dead reckoning.
- Enemy card recognition is a bootstrap (32 labelled crops, one deck): it names about half the
  units and stays silent on the rest. Splash/charge rules only fire for named units.
- Enemy units standing right next to their own princess towers are masked out (tower decorations
  gave false badges).
- Static decorations are only filtered after 8s; in the first seconds they can show up as units.
- Hand recognition needs one template per card (`templates/<card>.png`), cut from real frames.
- The evo frame (purple diamond) may lower the template match score; check in logs.

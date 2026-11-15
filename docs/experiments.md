# Experiments

One entry per test run. Newest at the bottom. Format:

```
## #N  YYYY-MM-DD  short title
Question:  what we wanted to know
Setup:     mode, deck, bot version (commit), what was varied
Result:    numbers from logs (runs/<match-id>/)
Decision:  what changed in the bot or docs, or "no change" and why
```

## #0  2026-11-08  Manual play by an LLM over adb (baseline)

Question: can an LLM play live by screenshot -> think -> tap?
Setup: 2v2 ladder, owner's deck, `adb exec-out screencap -p` (PNG) + `adb shell input tap`.
Result:
- PNG screencap took 2.6s; a full look-think-tap loop took 12-15s of game time.
- Match 1: lost 0-1, dealt ~35 tower damage, took ~4000.
- Match 2: tower HP roughly even until late, lost on king damage; several taps landed on wrong targets
  because the hand order had changed between the screenshot and the tap.
- Poison was used on a single tank (wasted). The Battle Ram card was misread as Ice Golem.
Decision: move all real-time play into a program (this repo). The LLM's job is analysis of logs
and improving rules, not live play.

## #1  2026-11-08  Vision speed (offline)

Question: is Python fast enough for per-frame vision, or do we need Rust?
Setup: all vision steps on `calib/battle_7elixir.png` (1080x2400), 30-50 runs each.
Result: 34.8ms per frame with NumPy boolean masks (troop bars 18 + 13ms). After one shared HSV
conversion + `cv2.inRange`: 14.2ms, identical outputs, all tests pass.
Decision: stay in Python. Re-measure on live frames.

## #2  2026-11-08  scrcpy stream on the phone (Galaxy S20 FE, Android 13)

Question: does the scrcpy path deliver frames, and how fast?
Setup: `FastDevice`, scrcpy server 5.0.1, H.264 (`OMX.qcom.video.encoder.avc`), ffmpeg 9.0 decoder.
Result:
- First attempt: video arrived (3.5 MB) but zero frames decoded. Cause: `-fflags nobuffer` makes
  ffmpeg 9.0 output nothing on this stream (tested flag by flag on a captured file). Also, without
  `-fps_mode passthrough` ffmpeg invents frames to fill an assumed 25 fps.
- After the fix: first frame 1.0s after start, ~62 decoded frames/s, newest frame 6ms old when read.
Decision: keep scrcpy as the default path. Measure end-to-end (screen change -> decision -> tap)
in a match.

## #3  2026-11-08  First live bot match: Practice vs Devil's deck (lost 0-3)

Question: does the bot see, decide and tap correctly in a real 1v1?
Setup: Practice from the Battle Log (AI "Trainer Cheddar II" with Devil's deck, level 14 towers 4032),
bot started ~15s into the match, scrcpy path, `runs/20261108-233727`.
Result:
- Pipeline fine: ~57 fps processed, 13-18ms per frame for vision + decision.
- Only 6 plays all match. Hand recognised 0-1 of 4 cards most of the time: 4 card templates were
  missing, and greyed (unaffordable) cards didn't match the colored templates. Bot sat at 9.9 elixir.
- Saw no enemies: troop detection looked for health bars, but **full-HP units show only their level
  badge**. Enemy goblins at our bridge and a troop on our tower were invisible.
- Tower HP read None all match: the 1v1 tower bars are in different places than in 2v2.
- Two plays fired on consecutive frames (Ram, then the next card in that slot): the UI lags a few
  frames behind a tap.
Decision / changes:
- Units are detected by level badge (red/white enemy, blue/yellow ours); bar only adds HP%.
- 1v1 layout recalibrated; tower HP verified against on-screen numbers.
- 4 missing card templates + 11 greyed-state templates cut from this run's crops; art-only,
  shift-tolerant matching; empty-slot check. All in-match crops of the run now label correctly.
- "Next:" label = in-match check. 0.8s gap between plays + spent elixir counted until the bar updates.
- Our units at full HP have no badge: Golden Knight position is dead-reckoned from our placement.
- Every new enemy unit is now cropped to `enemy_units/` to build the enemy-card recogniser.

## #4  2026-11-08  Second practice vs Devil's deck (lost 0-3): analysis

Run: `runs/20261108-235339`. Bot started before the match, played 14 cards.
Result:
- Vision worked live: enemy badges tracked (goblins, both pushes), hand 3-4/4 recognised.
- 95ms per frame (~10 fps): the shift-tolerant hand matcher ran 76 template searches every frame.
- Elixir averaged 1-3 all match: offensive Ram (24s) and Hog (33s), plus answering every small threat.
  At 47s a Tombstone went on 2 weak units on the left; at 49-55s a Dark Prince-type push on the
  right took our right tower 3668 -> 0 in ~7s while the bot had 0-2 elixir.
- The opponent-elixir estimate fell to 0 because badges hidden for a moment came back as "new
  plays"; that made "punish when low" fire the Hog at 33s into a full-elixir opponent.
- Our right tower read None while alive (troops standing on the bar).
- Champion ability button confirmed at ~(980,1932) in 1v1 while the GK was alive.
- Enemy unit crops: a third were the enemy tower itself, many were just the deploy stopwatch.
Owner's lessons (tagged owner in game-knowledge.md): splash kills groups; Prince/Dark Prince charge
(Dark Prince = splash, Knight = single target, no charge); finish the low-HP backline first.
Changes:
- Hand cache per slot (only re-match a slot whose pixels changed): 86ms -> ~11ms per frame.
- Defence reserve 4: no attack that leaves less. Lone/weak threats (HP <= 40%) left to the tower.
- "Punish when low" off until enemy cards are recognised. Reappearing badges no longer count as plays.
- Tower memory: hidden bar keeps its last value; destroyed only if low and unreadable for 2s.
- New `bot/cards.py` (splash/charge/ranged/swarm... per card). Rules: Log the low-HP support behind
  the front first; Minions never placed near a known splash unit; Tombstone first vs a charger, Log to
  reset a charger near our tower. The last two need enemy recognition (`track.card`).
- Enemy tower bodies masked; enemy units cropped 1.2s after they appear (after the deploy stopwatch).

## #5  2026-11-09  Third practice vs Devil's deck (lost): full 3-minute match

Run: `runs/20261109-000342`. 27 plays, ~50 fps, 11ms median per frame (p90 32ms).
Result:
- Enemy towers damaged: left 4032 -> 2640, right 4032 -> 3293. Ours: left fell ~40s, right ~160s,
  king at 221 HP with 6s left.
- Golden Knight ability fired 4 times (28s, 76s, 128s, 161s).
- Evo Witch has different card art: unrecognised from ~107s, elixir sat at 9-10 for ~40s.
- Poison was never played (in hand 15s -> end), Ram stuck 18s -> 145s: effectively a 2-3 card hand.
- A Golden Knight was placed at x=1120 (screen is 1080 wide): the predicted enemy position ran off
  screen; the card stayed selected (orange "can't deploy" overlay) until the next tap.
- Tower memory kept our destroyed left tower at 0.156 (threshold was 0.15).
- Enemy unit crops: no tower false-positives any more, sprites visible in most crops.
Changes:
- Evo Witch templates (colored + greyed). All saved unknown crops of this run now label correctly
  except empty slots and slide-in frames.
- Placements clamped: x 50-1030; troops/buildings y 1120-1700; spells anywhere on the arena.
- At >= 9 elixir with no threat: Hog/Ram to a bridge; else value Poison (2+ enemies together, or
  enemies next to their tower); at >= 9.8 Poison the weaker tower or start a push from behind the king.
- Tower "destroyed" threshold 0.25.
Open: label the enemy crops (needs the opponent's 8 card names from the owner).

## #6  2026-11-09  Owner feedback round + enemy recogniser bootstrap (offline)

Owner feedback after #5: bad at two-lane defence; attacks are dry (lone Hog); use defence survivors
for counter-pushes; predict their next card; Ram is dual-use. Opponent deck given by the owner.
Changes (all offline-tested, 46 tests):
- Lane urgency + re-defend when a push grows; supported push (GK/Minions then Hog/Ram at the same
  bridge); support spells around our Hog at their tower; counter-push with survivors; Ram in the
  defence list; opponent hand estimate from the cycle.
- Recogniser: 32 hand-labelled crops from runs 235339 + 000342 (18 Evo Barbarians, 4 Valkyrie,
  3 Dark Prince, 3 Spear Goblins, 2 Musketeer, 1 Boss Bandit, 1 Miner). Leave-one-out without
  rejection: 23/32 (72%), but only 5/14 on non-Barbarian cards. With a distance cutoff of 1.0:
  15/32 answered, 15/15 correct. Cutoff set to 0.95. ~0.07ms per unit.
- Sources for Heroes/Boss Bandit: RoyaleAPI Hero Wizard blog (Jan 2026), Supercell December 2025
  update notes, sportsdunia, noff.gg Boss Bandit page, esports.net, Supercell July balance notes.
Next: more labelled crops per card (aim >= 10 each) before trusting the splash/charge rules widely.

## #7  2026-11-09  Learning foundation (offline)

Owner direction: a data-driven learning system, not an if/else script (AGENTS.md "Direction").
Built: State snapshot, fixed action space (180 troop cells + spell cells + WAIT/ability), Policy
interface with the rule brain as the first policy, decision log, offline frame replay. Added
scikit-learn 1.9.1 + LightGBM 4.7.0 (owner approved).
Check: replaying run 000342 offline through the whole loop: 171s, 323 decision points, 25 plays,
realistic unit speeds (median |vy| 8 px/s) once the replay used frame timestamps (the first try ran
on wall-clock and inflated speeds ~8x). 50 offline tests pass. Bot behaviour live is unchanged
(RulePolicy = same decisions as before).
Next: every live match now produces decisions.jsonl = training data for L2.

## #8  2026-11-09  Match 004519 (lost, king at 281 HP) + step 2: learning from outcomes

Run `runs/20261109-004519`: 174s, 28 plays (23 defences, 3 GK abilities, 2 lone attacks), 88 elixir
spent; elixir >= 7 in only 4% of frames, so supported pushes never triggered. Overpaid for cheap
threats (Witch 5 / GK 4 vs Spear Goblins 2). Recogniser named Miner, Evo Barbarians, Musketeer,
Spear Goblins live. ~2400 tower damage dealt (best so far).
Owner feedback: Wizard-vs-Minions not predicted; Poison not used on swarms' path; GK ability not used
on key troops; one Log misplaced (26s, confirmed: badge-jitter sideways speed); Evo Ram = 2 cycles.
Fixes: see game-knowledge "round 4". 59 offline tests.
Step 2 built: outcome labels, features, LightGBM scorer, BlendPolicy + exploration, retrain after
every match. First training: 342 decisions / 26 plays from 1 match (no held-out check possible yet);
mean outcome per move was confounded by situation (GK is played when a big push is already
hitting, so it "looks" worst) - more matches + exploration needed before trusting it. beta = 0.10.
Replay timing note: 92ms/frame in replays comes from re-matching cards on JPEG frames 0.5s apart
(81ms); live it's ~1.4ms. Learned scoring: 0.17ms per decision.

## #9  2026-11-09  Match 010052 (lost by ~110s): bad Poison, wasted Witch

Run `runs/20261109-010052`. Model retrained on 2 matches: leave-one-match-out rank correlation 0.14
(plays 0.10): barely above chance, as expected with 38 plays.
Owner: "your Poison drop was horrible"; "your Witch went to waste alone, then a dumb Tombstone".
Confirmed in frames:
- Poison (85s) centered on one Evo Barbarian's straight-line guess at the left edge; the group walked
  diagonally to the bridge and out of it. Also: Barbarians survive Poison anyway (all were still
  unrecognised, and unknown units counted as vulnerable).
- Witch (45s) defended, then walked up the left lane alone. Our units at full HP show no badge, so
  the counter-push rule never saw her; at 54s the last 3 elixir went to a Tombstone on the right
  instead of a Hog in front of her.
Changes:
- Enemy prediction follows the walking path (lane bridge, then our lane tower).
- Poison: centered on the group inside it; value per unit (swarm/damaged 1.0, sturdy Barbarians 0.2,
  unknown 0.5); cards get a `sturdy` flag.
- Our Witch/GK/Minions are dead-reckoned for 14s (`OwnDeploys.supports`). Near its bridge with a win
  condition in hand: play it in front of her; if not affordable yet, save elixir unless a threat is
  urgent (lane threat / seconds >= 3).
- Static filter matches by distance+HP tolerance (grid keys reset on jitter).
- Exploration only when no enemy is within 1s of the river.
- Features: support_left/right. Model retrained (38 plays).
- Recogniser: +45 labelled crops (77 total). Leave-one-out 91%; cutoff 1.0 answers 77% at 98%.
64 offline tests pass.

## #10  2026-11-09  Match 010908 (lost 0-1, best so far) + round 6

Run `runs/20261109-010908`: full 175s, lost only our left tower; ~2540 tower damage dealt; 5
supported pushes. Model on 3 matches: plays rank correlation 0.30 (before new features).
Owner round 6 (see game-knowledge). Confirmed in frames: Poison 106s aimed at a dead tower's path;
Logs 98s/135s hit sturdy / full-HP units; GK vs Musketeer 89s fought at the river out of tower range;
Witch push 56s: the Hog went ahead because the Witch's estimate kept walking while she fought.
Built:
- data/: official card catalog (owner's API token, 123 cards; token not stored), base stats (208 units).
- profiles.py (+ learned per-card speed/lifetime from logs), spells.py (value-based Log/Poison).
- Path to the king after a tower falls; fight-aware support estimates; luring + splash-safe
  defender spots; in-match response memory with spell readiness / pre-cast; deck learned from plays.
- Features: time left, elixir difference, response probabilities, enemy profile totals, per-move
  remaining HP / DPS met and spell kill share (63 features).
Retrained (63 plays): leave-one-match-out 0.07 (plays 0.18), down from 0.30 with fewer features:
more features on the same tiny data overfit. Needs more matches before it carries weight.
70 offline tests pass.

## #11  2026-11-09  Run 040133 stopped at 37s: exploration bug; watch mode for the owner's matches

- All 4 plays of run 040133 (and 3 of 040043) were *explored* moves. Two bugs: exploration re-rolled
  every frame (an explored WAIT made the rules propose again next frame), so 15% became ~100%; and its
  alternatives put spells on coarse 2-tile grid cells at the rule's troop spot (x=104/320: the
  "edge" drops the owner saw), on targets the value check had rejected. Fixed: one roll per move,
  10s cooldown, alternatives are plays only, never spells (spells only at their value-computed spot).
- Watch mode (`./watch N`): logs the owner's own real matches as training data (policy "human").
  Placement anchor: the pink cost drop above a fresh placement, offset (+15, +55) px measured on 64
  of 67 of our own logged plays (spread ~±40px). Offline replay at 2 fps detected only 9/23 plays
  (frames too sparse); live it runs at ~50 fps - accuracy is measured per match by the elixir
  self-check (detected plays vs elixir spent) and in bot matches by shadow.jsonl.
- `./note <s> good|bad "text"`: owner verdicts override the outcome label of plays within 2s, and go
  to docs/insights-log.md for turning into rules/features.
74 offline tests.

## #12  2026-11-09  Features: cards as numbers

Owner: per-combination feedback ("Hog behind Witch") doesn't scale to 120+ cards. Features rewritten
so no card is a name: our move = its profile (11 numbers), our hand = counts (win conditions,
spells affordable, splash, anti-air, avg cost), our troops behind / ahead of the move and the
enemies it meets = profile totals (HP, DPS, ranged, splash, anti-air, building-targeters). State got
`our_units` (visible + dead-reckoned). 79 features, independent of the number of cards.
Same 67 plays, leave-one-match-out: 0.23 overall / 0.33 on plays (was 0.07 / 0.18 with name
features): it generalises better even with tiny data. `./note` text is optional (never read by the
model). 75 tests.

## #13  2026-11-09  Owner's 5 ladder matches (watch mode): what broke, what the data says

Runs 042916, 043226, 043631, 043941, 044251 (owner playing; bot observing).
Results (towers re-read from frames): W 1-0, L 0-1 (OT), W 1-0, unclear (no princess tower fell),
L (3-crown, king at 85 HP at the end).
What broke and was fixed:
- Crash at 3.5s in the first attempt: a badge at the right screen edge left an empty health-bar strip
  (cv2.inRange on empty input). Fixed + every frame is now wrapped: errors go to runs/<id>/errors.log.
- Play detection explained only 15-81% of spent elixir. Cause: a played card's slot goes EMPTY first
  and the elixir bar drops 0.1-0.4s later; the detector checked the drop at the same instant.
  Now: empty slot -> confirm the drop within 1s. Re-run on the 5 logs: 15-23 plays per match
  (was 5-23). 90 plays recovered into decisions_backfill.jsonl (spots from the cost drop in saved
  frames; by eye ~3 in 4 well placed).
- Ladder arena: enemy tower bars sit ~25px lower than in Training Camp -> live tower readings were
  wrong (None / 0). Tower reader now searches a band of rows; towers re-read from frames into
  towers_fixed.jsonl (outcomes prefer it).
- ~1/4 of "enemy units" were arena scenery (tower/king decorations, tower HP bars). Now: everything
  visible in the first 1.5s is scenery; units are only cropped/named after moving 30px or losing HP;
  bar masks +30px.
- Enemy naming: many opponent cards were new and my visual guesses were wrong. Stopped guessing:
  tools/battlelog.py attaches the true result + both decks per match (needs the owner's API key + tag).
Signals (small sample):
- Wins had more bridge attacks (6, 5) and pressure focused on one lane (W1: 14 of 17 plays right).
- Losses: L(3-crown) 2 bridge attacks, 14 of 16 plays on one side defending; L(OT) 23 plays with
  4 Witch + 4 GK + 1 Hog and the lowest average elixir (3.4): heavy, expensive defence.
- Owner never sat at a full bar (0-1s per match); the bot's own matches did for long stretches.
- Owner's moves, 10s outcome: Ram +0.41, Poison +0.17, Hog +0.04 ... Witch -0.63 (situational).
Model: 212 plays from 10 matches (90 owner), leave-one-match-out 0.29 / plays 0.24.

## #14  2026-11-09  Battle log API: true results + decks; deck-constrained troop labels

- tools/battlelog.py (key + tag in .env, git-ignored): attaches result + both decks to each run.
  First matching shifted every battle by one (run start vs battle start); now nearest start, 1:1.
- True results of the 5 watched matches: W 1-0, L 0-1, W 2-0, W 1-0, L 0-3 (3 wins). My frame-based
  guesses had one "unclear" that was a win, and a 2-0 read as 1-0.
- Opponents' decks were almost all new to us (Monk, Royal Giant, Golem, Phoenix, Rascals, Skeleton
  Barrel, Bomb Tower, Night Witch, Dart Goblin...). Labelled 99 crops one by one using ONLY each
  opponent's 8 cards (tools/label_run.py --single / --apply-single); unclear crops skipped.
- Recogniser now 27 classes / 176 crops: leave-one-out 68% open-set, 64% with the deck known (most
  new classes have 1-5 examples). Cutoff 0.9 -> 96% precise, 31% answered. `predict(allowed=deck)`.
Model retrained: 212 plays (90 owner), held-out 0.24 on plays.

## #15  2026-11-09  Training Camp: bot played 1 card in 54s (model vetoed everything)

Run 055851: hand read fine, elixir 9-10 all match, enemies seen; rules proposed plays within 4s
(offline replay), the blended model picked WAIT every time. Causes: (1) outcome label charged each
play 80 HP per elixir and waiting nothing, so "wait" looked best; (2) z-scored model output, with
beta grown to 0.8 (212 plays), overrode the rule prior on noise.
Fixes: label = tower dealt - taken - elixir WASTED at a full bar (spending isn't a cost by itself);
blend uses raw outcome differences / 0.5; at >= 9 elixir the model can re-aim or swap the card but
can't veto into WAIT. Replay of 055851 now plays (repeats are a replay artifact). Retrained:
Poison +0.44, Ram +0.33, Hog +0.29 ... GK ability -0.51; held-out 0.27 on plays. 77 tests.

## #16  2026-11-09  Practice vs a level-15 deck: the bot was blind

Run 061201 (practice vs sнαωĸy's deck, lost both towers by 59s, 7 plays). From 31s to 55s the log
shows zero enemies while a Prince took our right tower. Cause: level-15 enemy badges are orange-red
(hue ~11, sat ~200) with YELLOW digits; detection only knew pink-red badges with white digits.
Fix: second enemy badge range (hue 0-13, sat >=150: bridge wood is sat ~90-116) + yellow digits.
Regression test on the frame. Static false hits (king tower, decorations) are removed live by the
start-of-match scenery filter. This run's enemy crops are mostly missing (enemies weren't seen), so
no labels from it.

## #17  2026-11-09  Owner: random Poison woke their king; no Tombstone; defence must count; TV Royale

- Run 061822 Poison (17s): the "full bar, don't leak" rule cast Poison on one unknown unit next to
  their right tower; its radius reached the king tower and activated it. Fixes: spells that touch the
  enemy king (radius + king footprint) are worth 0; tower chip alone never justifies a spell; the
  full-bar spell dump is removed (a full bar starts a push instead).
- "Why didn't it learn the Tombstone from my plays?": the model only re-ranked around the rule move,
  so "Tombstone where the owner puts it" was never a candidate. New `bot/placements.py`: top cells per
  (card, situation = lane of the most urgent enemy) learned from human plays; added to the shortlist.
- Outcome label now credits defence: + 120 tower-HP per elixir of enemy units killed on our half in
  the 10s window (owner: "a good play is sometimes only defending / neutralising"). Held-out rank
  correlation 0.24 -> 0.39 (overall), 0.33 on plays.
- TV Royale recorder (`./tvroyale N`): replays show BOTH hands and elixir bars, the list shows both
  decks, the end screen the winner/crowns. Navigation: menu -> TV Royale; Watch buttons found by
  colour; already-recorded replays recognised by normalised card-art thumbnails (same entry 0.21 vs
  others 0.77; an exact hash broke when "Watched" greyed the entry). Data -> datasets/tv/<ts>/.
  Extraction of both sides' plays (tools.tv_extract) is the next step.
81 offline tests.

## #18  2026-11-10  Direction: simulator + RL, validated against TV Royale replays

Owner asked whether to drop TV Royale and build a simulator (after a GPT outline: perception,
state, decisions, RL in a simulator, execution). Decision: build the simulator (RL needs millions of
games; the real game gives ~20/hour), keep recording TV Royale (ground truth to validate the sim,
and data to start the policy from), freeze the rule brain as the baseline, add a fixed benchmark.
Roadmap rewritten (phases B, S1-S6).

## #19  2026-11-10  Profiles from the game's own stats (data/card_levels.json)

Question: the bot's numbers came from cr-api-data (last updated 2023) with a guessed +10%/level
scaling, so are they wrong enough to matter? Setup: offline, every card in bot/cards.py, old vs new
profile at enemy level 14. The new file is checked against statsroyale for 12 cards (exact).
Results:
- Most ranged troops had NO damage in the old file and fell back to a 150 default scaled up: Witch
  dps 292 -> 162, Musketeer 428 -> 288, Minions 518 -> 118, Baby Dragon 214 -> 148, Bomber 288 -> 156,
  Spear Goblins 305 -> 67 (hit speed is now 1.6s). Firecracker had none at all -> 28 (its explosion).
- Other fixes: Skeleton Army hp 69 -> 108, Goblins are 4 per card (was 3), Boss Bandit hp 1198 -> 3474,
  Lumberjack hp 1449 -> 1698 and range 1.2 -> 0.7 tiles, Executioner range 1.2 -> 4.5 tiles.
- Evo Barbarians and Hero Wizard now use their own form's stats (were the base card's).
- Damage spells get hp/dps 0 (were a 900/150 default troop). Unknown cards keep the default.
- Our spells: Poison (lvl 11) 734 -> 736 total over 8s, tower factor 0.30 -> 0.22; Log (lvl 13)
  351 -> 324, tower factor 0.20 -> 0.13. Areas unchanged (3.5 tiles radius; 3.9 x 10.1 tiles).
- Sparky: dps 443 -> 440 from the data; big_shot is now its real hit (1762 at lvl 14).
Retrained on the same 14 matches: held-out rank correlation 0.39 -> 0.38 overall, 0.33 -> 0.33 on
plays (no change beyond noise). 83 offline tests pass.
Decision: keep. Not yet measured in matches: run practice matches and compare to #17-#18 baselines.

## #20  2026-11-10  RoyaleSim, IL_Replay, ClashAI found; obsolete learning code removed

Found (owner): RoyaleSim (MIT Rust engine with Python bindings, rules measured against the real
client, all 145 cards, ~16k battles/h/core; published parity: 56.5% of non-tower unit-ticks within a
quarter tile, 79.5% exact HP), IL_Replay (252k Path of Legends replays, 17.8M plays with side, card,
tick, exact tile; no license stated), ClashAI (same recipe for one deck; ~14k trophies, 33-48% in
Ranked; no license). Read from their repos/data cards and a sample of the actions table; RoyaleSim
not yet run locally (installing it was held for the owner's OK: it executes downloaded code).
Decision: drop our own simulator (S1) and TV Royale extraction (S2); use RoyaleSim + IL_Replay after
local verification. Removed as obsolete: the outcome scorer on our own matches (bot/features.py,
bot/outcomes.py, bot/placements.py, tools/train_policy.py, BlendPolicy, tools/backfill.py, ./note,
--policy/--explore, retraining in ./play and ./watch, outcome section of tools.report, LightGBM),
data/card_stats.json (replaced by card_levels.json, #19), data/placements.json,
data/profiles_learned.json (game data has real speeds). Kept: perception, trackers, rule brain
(baseline), watch/tvroyale/battlelog/labelling, recogniser, cards_api.json. 73 offline tests pass.

## #21  2026-11-10  RoyaleSim verified locally; open-loop replay of 292 pro matches; ClashAI read

Setup: royalesim 0.1.51 in a throwaway venv (owner approved), Python 3.14, this Mac.
- Our 8 cards load (engine names: Witch, BattleRam, GoldenKnight, HogRider, Poison, Log, Tombstone,
  Minions); 145-card catalogue; levels, evo/hero forms and tower levels are reset() arguments.
- Speed, one core: ~115k empty 3-min battles/h; ~75k/h with both sides playing (Python loop,
  JSON state every second).
- Coordinates: engine = 18,000 units/tile; IL_Replay native = 1,000/tile, same 18x32 frame, team =
  blue = engine side 0 (low y). Engine x,y = native x,y * 18.
- IL_Replay shard replays/part-000000 (5,000 replays, sha256 matches the manifest). Open-loop
  replay (each recorded play injected at its tick and tile; deck ordered by first play; card waits
  up to 3s for hand/elixir) on the first 300: 292 simulated (8 skipped: Flying Machine not mapped),
  99% of 18,518 plays accepted, **winner agrees 60%, exact crowns 49%**.
  Reading: plays line up mechanically, but whole matches diverge - the recorded taps were reactions
  to the real board, so once the sim drifts they no longer fit. This measures chaos as much as
  accuracy; RoyaleSim's per-tick parity (56.5% within 1/4 tile, 79.5% exact HP) is the better gauge.
  Implication: train on short horizons from replay states (plays + value), not on full-match
  open-loop outcomes.
- ClashAI read (no license: ideas only). Pipeline: corpus replays driven through RoyaleSim ->
  imitation dataset for both sides -> transformer (unit tokens + board patches + global token,
  card-identity embeddings, pointer heads for card / cell / wait) -> PPO with KL leash to the
  imitation model, league self-play, terminal reward, many opt-in shaping terms per deck (Rocket,
  X-Bow, habits). Live: a 230-class detector (not in the repo), opponent hand belief and elixir
  counter from public events, action delay + extrapolation modelled. Hardware: multi-GPU (cuda:0-3).
  Has a decision-time rollout search (search_s0) as an experiment; not in its reported results.
  Results: ~14k trophies (51.5% over 4,499), Ranked 33-48%.

## #22  2026-11-10  RoyaleSim pinned in the bot; battle viewer

royalesim==0.1.51 added to requirements.txt (owner approved). `bot/sim.py` adapts our card keys,
levels and forms to the engine; `tools/sim_watch.py` plays a battle (placeholder random players on
both sides, no trained model yet) and renders an H.264 video to sims/ (git-ignored): a 3-minute
battle renders in ~10s. tests/test_sim.py: our deck loads, a play is accepted, same seed -> same
battle.

## #23  2026-11-11  Replay dataset: download + samples from RoyaleSim

- `tools/fetch_replays.py`: only IL_Replay's `replays/` shards (0.83 GB; each payload already holds
  every play, `actions/` is an expanded copy), resumable, SHA-256 checked. First run: 29/52 shards
  (~145k replays) before the network failed; re-run resumes. PyPI timed out repeatedly the same day;
  pyarrow installed from the Aliyun mirror (`pip -i https://mirrors.aliyun.com/pypi/simple/`).
- `tools/build_dataset.py`: each replay re-played in RoyaleSim (real levels, evo/hero forms, tower
  levels); a sample at every play + a "wait" sample per side per 3s without a play. Inputs from the
  acting player's view (own king at the bottom; red rotated 180 degrees): up to 48 units (card id +
  8 features), 12 scalars (time, elixir, public enemy-elixir count, 6 tower HP, crowns, overtime),
  hand + next, enemy cards seen. Labels: hand slot (or wait) + tile; outcome = the player's real
  result. `drift` = plays rejected so far (open-loop drift, #21). Chunks of 1,000 replays per file
  (9 GB RAM machine), atomic writes, resumable.
- Check on 40 replays: 6,244 samples (2,421 plays, 3,823 waits), 96% of plays reproduced; 85% / 87%
  of plays in the own half for blue / red (rotation correct); results 51% win / 49% loss; ~4 units
  per sample (max 26). ~6.5 KB per replay compressed: all 145k replays ~1 GB.
- Not phone-identical yet: enemy unit ids are true ids (training will mask a share to "unknown");
  enemy elixir is the exact public count (live is an estimate).

## #24  2026-11-11  R3: first model (RoyaleBrain) and Mac GPU speed

PyTorch 2.15 (owner OK; Aliyun mirror), Apple GPU (MPS) available. `bot/model.py`: 1.08M
parameters, d=128, 4 layers, 4 heads; tokens = 1 global + units + 5 hand + seen cards; each card =
learned identity + engine card-table stats (`Sim.card_table`, 12 numbers). Heads: gate (play/wait),
card (pointer over the 4 hand cards), tile (576 cells, conditioned on the card), value (win prob).
`tools/train_model.py`: streams the 1,000-replay chunks; held out = replays with id % 50 == 0;
40% of wait samples kept; sample weight 1/(1 + drift/3); training hides 50% of enemy unit ids and
30% of seen cards (live recognition is partial).
Speed (this Mac): 600 ms/step at batch 512 at first. Not the data (4 ms/batch). A bare 4-layer
transformer was ~500 ms/step on 62 tokens; most unit slots are empty (~4 units per sample), so
batches are now trimmed to the occupied slots (2.5x on a bench; 1.5 -> 2.2 steps/s in training,
~1,100 samples/s). fp16/bf16 autocast gave nothing on MPS. Reading losses only every 20 steps.
Smoke run (300 steps, held-out): card 41%, tile exact 10% / within 1 tile 20%, play/wait 61-63%,
winner 53-55%. Main run r3a: 20,000 steps (~10M samples, ~2.5 h) on 114 chunks (~114k replays).
Follow-up (owner): the full-data run continues from r3a's weights if r3a checks out, instead of
starting over: `tools.train_model --init models/r3a.pt --name r3b`. New checkpoints also store the
optimizer state and total steps, so later continuations resume exactly.

## #25  2026-11-12  Abilities were missing from the dataset; rebuild

Owner asked whether champion/hero abilities cost elixir. In RoyaleSim: yes (Golden Knight press =
-1 elixir; command slot 4 = first ability button; per-button record [ready, ?, cost, card id, ?]).
IL_Replay has `activate_ability` events (side + tick, no position): 7,654 in 2,000 replays (~5% of
actions), in 91% of replays. The builder ignored them: champions/heroes never used abilities in the
re-played matches, elixir stayed too high, and the model could never learn to press.
Fix: presses replayed at their tick on a ready button (matching the event's candidate card);
label_slot 4 = ability press (no tile); 9 ability scalars (ready, cost... for 2 buttons); model's
card head gets a 5th option, masked unless a button is ready. 74% of presses reproduce (rest: unit
dead / not ready after drift). Old samples could not be patched: 45% of them precede the first
press and are still valid, but every match must be re-simulated from its start anyway and they lack
the ability inputs. Old data kept in datasets/samples_v1, old model as models/r3a_noabilities.pt.
r3a (no abilities) as a pipeline check, held-out after 8,000 steps (74 min): card 61.5%, tile within
1 tile 40%, play/wait 70%, winner 60% (from 41% / 20% / 62% / 55% at 300 steps): training works.
Builder speed: the engine's step() is ~80% of the time (0.08 s/replay); the earlier slow rate came
from sharing the CPU with training. Full rebuild with 7 workers started.
Build command (owner): `./build` (7 workers by default, live progress bar, Ctrl+C stops safely, rerun
resumes), `./build --status`. The builder now re-enables SIGINT itself (a process launched in the
background of a script ignores it). Measured: ~23 replays/s with 2 workers.
Train command (owner): `./train` (= tools.train_model --name r3 --steps 44000 --eval-every 2000),
`./train --status`. Ctrl+C saves the checkpoint at that step (weights, Adam state, learning-rate
schedule, step); rerunning the same name continues it exactly; a finished name refuses and points to
`--name r3b --init models/r3.pt`. Estimate from samples_v1: ~150 samples and ~53 plays per replay ->
~38M samples for 252k replays; training keeps plays + 40% of waits minus held-out = ~22M per pass =
~44k steps of 512 at ~2.2 steps/s = ~5.5-6 h (+ ~22 held-out checks).

## #26  2026-11-12  SB: the simulator benchmark

Question: does a player (rule brain, model, random) win with our deck against real decks?
Setup (`./bench <player>`, tools/sim_bench.py): our deck at our levels (blue) vs 200 HELD-OUT pro
matches (replay id % 50 == 0, never trained on) that lasted 3:00+, alternating which side's deck we
face; our deck order shuffled per match with a fixed seed. Same 200 matches for every run, so two
runs compare match by match. Opponent (`--vs`): `replay` (default) = the pro's real moves replayed at
their time and spot, rotated to red; it does not react to us, and plays randomly once the real
match's moves run out; or a model checkpoint playing the opponent's deck.
- Rule brain in the sim: Brain unchanged, fed tracks built from the sim's units (perfect vision: all
  units, all enemy cards, our own troops), the same public enemy-elixir count as the model. Tiles <->
  phone pixels fitted on layout.py anchors (x exact, y +-50 px). Bug found on the way: the rule
  player looked cards up in the unshuffled deck order (it thought slot 3 was a cheap card).
  Remaining refusals ~1.5/match, mostly the brain aiming the Log at an enemy tower: the engine only
  allows the Log on our own side (OUT_OF_TERRITORY). Not changed (the brain is the frozen baseline);
  Owner (2026-11-12): in the real game the Log can be cast at most at the bridge (it rolls on to
  the tower), so the ENGINE IS RIGHT and the brain's Log finish is a live bug too (taps an illegal spot).
- Model player: same observation as training; plays when gate logit > 0, its best card if
  affordable (else waits for it), best LEGAL tile (engine check_deploy). Gate measured: at 0, ~24
  plays in 2:36 (pros ~26 per 3:00); a prior correction to ln(15) = 2.7 made it never play.
- Replay opponents first went idle after a short real match ended (12 plays then nothing): fixed by
  using only 3:00+ matches and a random fallback.
First small runs (12 matches, too few to trust; 95% ranges overlap): random 1/12, rules 3/12,
r3 at 4k steps 5/12 (plays ~29/match, 0 refusals). ~2 s per match per worker.
Memory: the 8 GB Mac cannot run 3 bench workers (each loads PyTorch) next to training: swap hit
7.2/8 GB and training stalled ~30 min. Held-out selection now streams 50-row batches (180 MB peak,
was a whole shard's payload column); default 2 workers. Run full benches after training, or with
`--workers 1` during it.

## #27  2026-11-13  r3 finished; first full benchmark: the model beats the rule brain

r3: 44,000 steps (1 pass, ~22M samples), resumed several times. Held-out: card 64.7%, tile within
1 tile 48.0%, play/wait 70.1%, winner 59.6%, ability presses 53.5% (r3a: 61.5 / 40.4 / 69.6 / 60.2 / -).
Card and tile kept improving; timing and win prediction stayed flat.
SB, 200 held-out pro matches vs replayed pro moves (`./bench`, 4 workers, < 1 min each):

| player | won | 95% range | crowns for-against | tower dmg dealt / taken | plays/match | refused |
|---|---|---|---|---|---|---|
| random | 30 (15.0%) | 11-21% | 0.59-2.51 | 37% / 76% | 13.4 | 0 |
| rules | 61 (30.5%) | 25-37% | 1.13-1.84 | 56% / 65% | 23.3 | 2.0 |
| **r3** | **95 (47.5%)** | 41-54% | 1.48-1.54 | 61% / 58% | 23.4 | 0 |

Same matches, compared one by one: both won 53, only the model 42, only the rules 8 (sign test
p < 0.0001). The model is clearly better than the rule brain here. Limits: the opponent replays a
pro's moves blind (does not react); sim, not phone.
Fix on the way: one held-out replay has tower level 0 (missing), the engine refuses it and the
whole benchmark crashed; matches with missing levels are now skipped when the set is picked (the
set is otherwise the same rule: first 200 valid held-out 3:00+ matches).

## #28  2026-11-13  Equal levels: the real scoreboard

#27 used our real levels vs the pros' (mostly higher). Against a REACTING opponent (r3 playing the
pro deck) that gave rules 12.5% vs r3 15.0%: mostly a card-level gap, not skill. Owner: compare
players at equal levels. `./bench` now puts every card and tower on both sides at level 14 by default
(`--real-levels` for the old setting). Same 200 held-out matches:

| player | vs blind replay | vs r3 (reacts) |
|---|---|---|
| rules | 170 (85.0%, 79-89%) | 47 (23.5%, 18-30%), draws 7 |
| **r3** | 189 (94.5%, 90-97%) | **105 (52.5%, 46-59%)**, draws 24, crowns 0.89-0.79 |

- The blind replay is too easy at equal levels (85-95%): only a sanity check now.
- r3 vs r3 is ~50% as it should be (same brain both sides; our deck vs real meta decks).
- r3 is far better than the rule brain against the same reacting opponent (52.5% vs 23.5%).
- SCOREBOARD from here: `./bench <player> --vs models/r3.pt` (equal levels). r3 = 52.5%; search (R6)
  must beat that.

## #29  2026-11-13  R6 search, first version: no clear gain yet

bot/search.py: candidates = WAIT + the model's top 2 affordable cards x top 2 legal tiles (<= 5);
each in an exact copy of the battle (engine save/load, ~3 ms per copy), played 6 s forward with r3
greedy on both sides (batched forward passes), scored by r3's value head (win probability) for us.
~36 ms per decision. `./bench search:models/r3.pt --vs models/r3.pt`, same 200 matches, equal levels:

| player vs r3 | won | 95% range | draws | crowns | plays/match |
|---|---|---|---|---|---|
| r3 (greedy) | 105 (52.5%) | 46-59% | 24 | 0.89-0.79 | 27.9 |
| r3 + search | 110 (55.0%) | 48-62% | 20 | 1.18-0.98 | 36.0 |

Match by match: only search won 52, only plain won 47 (sign test p = 0.69): NOT a real improvement,
even though the rollouts used the opponent's exact policy and its hidden hand/elixir (an oracle a
real opponent never gives). The search plays ~30% more cards: it prefers having units on the board.
Likely cause: the value head is the weak part (winner 59.6% held-out, trained on final results of
pro matches whose re-simulation drifts), so 6 s ahead it cannot tell good moves from busy ones.
Engine bug found: RoyaleSim 0.1.51 cannot load some snapshots with a Bowler on the board
("snapshot entity tables are inconsistent", 151 of ~70k decisions); those fall back to the plain move.
Also added: `--vs sample:<ckpt>`: the opponent samples its card/tile from the model (seeded), so the
search can't foresee its moves exactly (for honest tests once search helps).

## #30  2026-11-14  Search scored by real outcome: 84% vs 52.5%

Change (bot/search.py, `./bench search:models/r3.pt --vs models/r3.pt --score outcome --timing model
--horizon 12`): two switches against search v1 (#29).
- score "outcome" instead of the value head: after the look-ahead, tower HP dealt - taken (1 = a
  whole tower) + 0.1 x material lead (elixir in the bank + elixir worth of living units x their HP
  fraction; 10 elixir ~ one tower); a finished match +-3. Hand-made: a stopgap until a value learned
  from simulator games (self-play) replaces it.
- timing "model": the model's gate still decides WHEN to play (as without search); search only picks
  WHICH play among the top 2 affordable cards x top 2 legal tiles.
- look-ahead 12 s (was 6 s), so pushes reach a tower.

Same 200 held-out matches, equal levels, opponent r3 playing the pro decks:

| player | won | 95% range | draws | crowns | tower dmg dealt / taken | plays |
|---|---|---|---|---|---|---|
| r3 (greedy) | 105 (52.5%) | 46-59% | 24 | 0.89-0.79 | 51% / 44% | 27.9 |
| search v1 (value, search timing, 6 s) | 110 (55.0%) | 48-62% | 20 | 1.18-0.98 | 54% / 50% | 36.0 |
| **search A (outcome, model timing, 12 s)** | **168 (84.0%)** | 78-88% | 18 | 1.61-0.45 | 70% / 35% | 24.6 |

Match by match vs plain r3: only search A won 78, only plain won 15 (sign test p < 1e-10).
14.5 ms per decision (searches only when the model wants to play), 17 Bowler-snapshot fallbacks,
5.5 min for 200 matches on 4 workers.

NOT YET SHOWN, so 84% is an upper bound:
- The opponent in the rollouts is the benchmark opponent itself (deterministic r3) with its real hand
  and elixir: search foresees its replies exactly. Next test: `--vs sample:models/r3.pt`.
- Which switch did it? B run 2026-11-14 (below); C (value score + model timing) not run yet.

Variant B (outcome score, 12 s, but SEARCH decides when, WAIT is a candidate): 161/200 = 80.5%
(74-85%), draws 7, crowns 1.52-0.61, tower damage 67% / 45%, 30.2 plays/match, 87 ms per decision,
29 min. Match by match vs A: only B won 22, only A won 29 (p = 0.40): no real difference, and B is
6x slower and loses more towers. So the OUTCOME SCORE is what made the jump (both ~80-84% vs v1's
55%); letting search decide timing adds nothing. Keep A (model timing).

Honest-opponent test (2026-11-14): opponent `sample:models/r3.pt` = r3 that SAMPLES its card and tile
from its probabilities (seeded per match), so the search's greedy rollouts can't foresee its moves.
Same 200 matches, equal levels:

| player vs sample:r3 | won | 95% range | draws | crowns | tower dmg dealt / taken |
|---|---|---|---|---|---|
| r3 (greedy) | 123 (61.5%) | 55-68% | 24 | 1.06-0.64 | 57% / 42% |
| search A | 169 (84.5%) | 79-89% | 11 | 1.48-0.41 | 66% / 35% |

The sampling opponent is weaker than greedy r3 (plain r3 wins 61.5% instead of 52.5%), so the fair
measure is the gain over plain r3 on the same opponent: +23 points (was +31.5 against the opponent it
could predict exactly). Match by match: only search won 54, only plain won 8 (p < 1e-8).
So most of the gain is real, not foresight of the opponent's exact replies.
Still in its favour: the rollouts read the opponent's hand and elixir from the engine, and the
rollout policy is the same model family as the opponent. Correction (owner): on the phone those are
mostly TRACKABLE, not hidden: elixir = public count of seen plays (capped at 10 at every moment),
hand = known once all 8 cards were played (fixed cycle), narrowed before that. Truly unknown: unseen
cards early in the match and plays our vision misses (AGENTS.md).

## #31  2026-11-15  Opponent elixir count capped at every moment (step 1a)

Bug: the public count of the enemy's elixir (dataset builder `observe`, benchmark, search) was
5 + all regen - all spent, capped at 10 only at the end. A player who waits a minute at full and then
plays a 4 has 6; the old count said 10 (shown before the fix). The live bot was already right
(bot/economy.py caps every frame).
Fix: `tools.build_dataset.ElixirCount` (5 at the start, regen x2 from 2:00, minus each play seen,
capped at 10 at every play), used by observe, the benchmark's Match and the search rollouts.
tests/test_elixir_count.py (start, leak at full, double elixir). Not rebuilt: the training data and r3
still use the old count; the next dataset build uses the fixed one.
Scoreboard rerun (vs r3, same 200 matches, level 14): r3 105/200 = 52.5% (draws 29, was 24),
search A 168/200 = 84.0% (crowns 1.62-0.41). Same win rates as before: the matches play out a bit
differently, the results don't move. Fine to have, not a source of strength.

## #32  2026-11-15  Opponent cycle tracking, verified against the engine (step 1b)

bot/opponent.Opponent gained (additive; the frozen brain's calls behave as before):
- `queue()`: their 4-card queue = their last 4 plays, oldest first; early in the match the front is
  unknown (cards not played yet), a missed play is unknown too. `next_card()` = queue[0].
- `certain_hand()`: seen cards not in the queue, only when every queue slot is known (4+ plays, none
  missed); `unknown_hand_slots()` = 4 - that.
- `sample(rng, pool)`: one (hand, queue) consistent with everything seen, unseen deck cards drawn from
  a pool, for the search (1c). Exact when nothing is unknown.
Verified (tests/test_opponent_cycle.py): RoyaleSim red plays 30 random cards; after every play our
next card = the engine's, and once all 8 cards are seen our certain hand = the engine's exact hand.
The cycle rule in the file's docstring was "unverified": it is now.
Found on the way:
- Bug: `played()` used `if card:`, so an engine card id 0 never entered the deck (live uses names, so
  only the sim was affected). Fixed (`is not None`).
- The engine leaves a hand slot empty (-1) for a moment after a play, until the next card slides in
  (the real game's short delay). Code reading hands must allow for it.

## #33  2026-11-15  Honest search: only what we could know about the opponent (steps 1c + 1d)

bot/search.Hidden rewrites each search copy before the rollouts: the opponent's elixir = our
ElixirCount (#31), their hand and queue = Opponent.sample() from the cycle tracker (#32): exact once
all 8 cards are seen and no recent play was missed, otherwise unseen slots get cards they haven't
shown (uniform over the catalogue), which also replace the unseen cards in their deck list (level =
median of their known cards, base form). Our own side and the board stay exact.
How: snapshots are JSON; hand/queue use the engine's INTERNAL card ids (79 of 145 differ from the
catalogue ids; table built at start, 0.5 s); load() refuses an edited snapshot (stored state_hash),
and the refusal names the rebuilt hash, so a deliberate edit loads on the second try (the engine
still rebuilds and checks the whole state). +~11 ms per searched decision (16.6 ms average).
Tests: tests/test_hidden.py (real battle untouched, counted elixir, unseen real cards only by chance,
exact copy once everything is known). `./bench search:models/r3.pt --score outcome --timing model
--horizon 12 --honest`. Same 200 matches, equal levels:

| opponent | plain r3 | search, sees everything | **search, honest** |
|---|---|---|---|
| r3 (greedy) | 52.5% | 84.0% | **73.5%** (67-79%), crowns 1.43-0.58 |
| sample:r3 (unpredictable) | 61.5% | 84.5% | **81.0%** (75-86%), crowns 1.49-0.46 |

Match by match: honest vs plain r3: 68-26 (vs r3) and 57-18 (vs sample), both p < 1e-5.
Honest vs sees-everything: 19-40 vs r3 (p = 0.009: knowing a DETERMINISTIC opponent's exact hand let
the full search predict its replies), 24-31 vs sample:r3 (p = 0.42: no clear cost).
So against an opponent it can't predict anyway, playing honestly costs little; the search keeps a
+20-point gain over plain r3 using only what a player could know. (Plain r3 vs sample:r3 was measured
before the elixir-count fix, #31; vs r3 it did not change with the fix.)
Next to try: a prior for unseen cards (the 251k replays' deck statistics instead of uniform over all
145 cards); several guesses per decision averaged.

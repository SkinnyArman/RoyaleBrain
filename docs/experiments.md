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

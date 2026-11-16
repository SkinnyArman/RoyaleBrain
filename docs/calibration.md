# Calibration (Galaxy S20 FE, 1080x2400, portrait)

**1v1 and 2v2 are laid out differently.** The bot's `layout.py` now holds 1v1 values (the target).
1v1 values were measured on practice frames on 2026-11-08 (recorder frames are half-res; upscaled).

## 1v1 (current)

| What | Value | How it was measured | Status |
|---|---|---|---|
| Card tap centers | x = 336, 536, 744, 944; y = 2190 | practice frame | verified |
| Tower bars | enemy row 416, ours row 1451; x 176-308 / 813-945 (enemy), 178-306 / 816-945 (ours) | fill vs on-screen numbers: enemy left 0.76 vs 0.77, our left 0.48 vs 0.50 | verified on 2 frames |
| Tower max HP | enemy 4032 (level 14), ours 3668 (level 13) in the practice vs Devil's deck | on-screen numbers at match start | verified, per match |
| River / bridges | river y≈1035-1075; bridges (226,1120), (854,1120) | practice frame | approximate |
| **Unit detection = level badges** | enemy badge HSV ~(171,185,140) + white digits; our badge ~(103,145,145) + **yellow** digits; 16-46px square | full-HP enemy units show only the badge (no bar); our units at full HP show nothing | enemy verified on 2 frames; ours on 1 blurry frame |
| In-match check | "Next:" label template, box (0,2100)-(300,2350) | scores 1.00 in match vs 0.37-0.48 on results/menus | verified on 1 run |

## 2v2 (old, from the first sessions)

All values live in `bot/layout.py`. Measured from 2v2 screenshots on 2026-11-08 unless noted.
**Re-check every value in 1v1 Training Camp** and update this table with the frame you used.

| What | Value | How it was measured | Status |
|---|---|---|---|
| Card slot tap centers | x = 336, 540, 744, 948; y = 2160 | taps that worked in 2v2 | verified (2v2) |
| Card crop boxes | ±85px around x, y 2085-2295 | full-res screenshot `calib/battle_7elixir.png` | verified (2v2) |
| Elixir bar | row y=2364, pink from x=290 (0) to x=1044 (10) | pink pixel extent at 7 elixir ended at x=818: (818-290)/(1044-290)*10 = 7.0 | verified on 1 frame |
| Pink color | HSV h>140, s>120, v>150 | same frame | verified on 1 frame |
| River | y ≈ 1010-1100 | screenshots | approximate |
| Bridges (deploy) | left (264,1128), right (840,1128) | Hog deploys that worked | verified (2v2) |
| Enemy tower HP bars (masked) | (150,440)-(340,530), (730,440)-(940,530), king (380,190)-(700,270) | screenshots | approximate |
| Our troop bars (blue) | fill HSV (95-108, 110-200, 220-255), empty (106-116, 80-140, 90-135) | sampled on our 3 bridge units; all 3 found at 27% HP | verified on 1 frame |
| Enemy troop bars (red) | fill (165-180 or 0-5, 150-255, 180-255), empty (158-172, 80-150, 70-120) | **assumed** from the enemy tower bar | **unverified** |
| Bar shape | fill+empty joined, 20-160px wide, 3-14 core rows, level badge (≥18px tall) within 14px to the left | badge separated by vertical opening | verified on 1 frame |
| Tower HP bars | row y=507 (enemy) / 1470 (ours), x 194-319 (left), 800-925 (right) | fill fraction vs on-screen numbers: 0.76 (2342), 1.0 (3052), 0.896 (2771) | verified on 1 frame; our left mirrored |
| Champion ability button | ≈ (972,1920) | seen in screenshots | **unverified** |

## Learned at runtime

- Arena decorations that look like bars (e.g. 4 blue ornaments around our king tower on the 2v2
  arena) are learned by `vision.StaticFilter`: same spot, same HP for 8s = scenery.

## Card templates

`templates/<name>.png` are crops of the card slots (`layout.SLOT_BOXES`), names must match
`brain.COST` keys: `hog, ram, golden_knight, witch, tombstone, minions, poison, log`.

Have: witch, tombstone, poison, ram (from `calib/battle_7elixir.png`).
Missing: hog, golden_knight, minions, log. Get them with `python -m tools.grab --cards` while each
is in hand, then copy the right `shots/slot<N>_*.png` to `templates/<name>.png`.

## Unused coordinates kept for reference (removed from code 2026-11-16, nothing read them)

- TV Royale list: Watch buttons of the first two entries at y 1171 and 1697 (x 898 is still in
  tools/tvroyale.py). Measured 2026-11-09.
- Defensive spots in front of our princess towers: left (300, 1380), right (780, 1380). Set by hand
  for the rule brain, never measured against outcomes.
- "Our half" for threats: y 1080 (river line) to 1760.
- TV Royale list entries: first entry's top edge y 735, entry height 526 px.

## Badge levels and greyed hand cards (2026-11-16, experiments #39)

- Enemy badge digits: white on the red badge, yellow on the level-15 style badge; read by
  bot/levels.py from datasets/badge_levels (labelled from the 2026-11-15/16 enemy crops). Seen so far
  on enemies: 13, 14, 15.
- Greyed (unaffordable) hand cards: art saturation 75th percentile 6-15, in colour 135+ (threshold
  60, vision.HandReader.GREY_SAT). Greyed art shows a refill sweep, so templates of it are unreliable.

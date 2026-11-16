"""Screen coordinates for a 1080x2400 phone (Galaxy S20 FE), measured from screenshots."""

W, H = 1080, 2400

# Hand: 4 card slots (tap centers) and crop boxes (x0, y0, x1, y1) used for recognition.
SLOTS = [(336, 2190), (536, 2190), (744, 2190), (944, 2190)]
SLOT_BOXES = [(x - 85, 2085, x + 85, 2295) for x, _ in SLOTS]

# Elixir bar: pink fill from x=290 (0) to x=1044 (10) on row y=2364.
ELIXIR_Y = 2364
ELIXIR_X0, ELIXIR_X1 = 290, 1044

CHAMPION_ABILITY = (972, 1920)
CHAMPION_BOX = (860, 1790, 1080, 2050)    # search area for templates_ui/champion_ability.png

# Arena (1v1). The river is around y=1035-1075; our half is below it.
RIVER_Y = 1080
MID_X = 540
ARENA_Y = (180, 1760)
# Princess tower HP bars in 1v1: (team, row y, x0, x1) of the bar (crown badge is left of it).
# Measured 2026-11-08 on 1v1 practice frames against the on-screen numbers (enemy left 0.76 vs
# 3109/4032, our left 0.48 vs 1848/3668). 2v2 is laid out differently (see docs/calibration.md).
TOWER_BARS = {
    "enemy_left": ("enemy", 416, 176, 308),
    "enemy_right": ("enemy", 416, 813, 945),
    "our_left": ("ally", 1451, 178, 306),
    "our_right": ("ally", 1451, 816, 945),
}
# Tower and king bars + crown badges, ignored by troop detection. (x0, y0, x1, y1)
TOWER_BAR_MASKS = [(130, 385, 330, 470), (770, 385, 965, 470), (380, 160, 700, 260),   # +30px: ladder arena bars sit lower
                   (130, 1420, 330, 1475), (770, 1420, 965, 1475)]
# Tower centers (spell targeting, spell-safety checks)
TOWERS = {"enemy_left": (220, 580), "enemy_right": (860, 580),
          "our_left": (220, 1400), "our_right": (860, 1400)}
TILE_PX = 54                                   # arena ~972px wide / 18 tiles
# Ignored for enemy badges: the princess towers' red banners + archer (they look like enemy badges,
# runs 235339, 20261115-*) and the king body. Narrowed 2026-11-15 from (140, 440, 330, 720): the old box
# also hid real enemy units standing in front of their towers (the model saw no enemies there).
ENEMY_TOWER_BODIES = [(130, 480, 340, 565), (740, 480, 950, 565), (380, 240, 700, 420),
                      # the top of OUR princess towers (cannon + red arrow, it turns with the cannon) read as an
                      # enemy badge: 7,997 detections in the 2026-11-15/16 runs, all full HP, never named; 26
                      # damaged ones (maybe real units) also fall inside (experiments #37, #38)
                      (140, 1330, 300, 1410), (780, 1330, 940, 1410)]
DEPLOY_X = (50, 1030)                          # playable arena width
OUR_DEPLOY_Y = (1120, 1700)                    # our side: just below the river .. behind the king
BACK = {"left": (380, 1640), "right": (700, 1640)}   # behind the king tower, to build a push
OUR_TOWER_BODIES = [(90, 1320, 350, 1480), (730, 1320, 990, 1480)]   # ignored for our own badges
NEXT_LABEL_BOX = (0, 2100, 300, 2350)          # search area for templates_ui/next_label.png
BRIDGE = {"left": (226, 1120), "right": (854, 1120)}
# Center pull spots (the rule brain's lure).
CENTER_PULL = {"left": (430, 1330), "right": (650, 1330)}
OUR_KING = (540, 1600)                         # our king tower center (1v1 frames)
ENEMY_KING = (540, 330)                        # their king tower center
KING_HALF_PX = 120                             # king tower footprint half-size (~4.5 tiles wide)

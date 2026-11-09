"""Offline tests: no phone needed. Run: .venv/bin/python -m pytest -q"""
import json
import math
import struct
from pathlib import Path

import cv2
import numpy as np

from bot import layout as L
from bot import vision
from bot.brain import PRINCESS_MAX_HP, Brain
from bot.economy import EnemyElixir
from bot.opponent import Opponent
from bot.tracker import OwnDeploys, Tracker

FRAME = Path(__file__).resolve().parent.parent / "calib" / "battle_7elixir.png"      # 2v2, full-res
FRAMES = Path(__file__).resolve().parent / "frames"
ROOT_DIR = Path(__file__).resolve().parent.parent


def frame_1v1(name):
    """1v1 practice frames are stored half-res (as the recorder saves them): scale back up."""
    return cv2.resize(cv2.imread(str(FRAMES / name)), (1080, 2400), interpolation=cv2.INTER_CUBIC)


def test_elixir_reads_seven():
    assert vision.elixir(cv2.imread(str(FRAME))) == 7.0


def test_hand_recognised():
    img = cv2.imread(str(FRAME))
    assert vision.hand(img, vision.load_templates()) == ["witch", "tombstone", "poison", "ram"]


def test_only_blue_bars_in_our_half_means_no_threat():
    img = cv2.imread(str(FRAME))
    assert [p for p in vision.enemies(img) if p[1] > 1100] == []


def test_touch_message_is_32_bytes():
    assert struct.calcsize(">BBqiiHHHii") == 32


def test_spawn_group_counts_once():
    tr = Tracker()
    tr.update([], 0.0)
    group = [(300, 400, 60), (330, 420, 60), (310, 450, 60)]
    assert tr.update(group, 0.1) == []
    assert len(tr.update([(x + 2, y + 5, w) for x, y, w in group], 0.2)) == 1
    assert tr.update([(x + 4, y + 10, w) for x, y, w in group], 0.3) == []


def walk(points_fn, t_end, dt=0.1):
    """Feed a tracker frames from points_fn(t) and return it."""
    tr, t = Tracker(), 0.0
    while t <= t_end + 1e-9:
        tr.update(points_fn(t), t)
        t += dt
    return tr


def test_enemy_elixir_regen_and_spend():
    e = EnemyElixir()
    e.update(0, 5)
    e.update(2.8, 6)
    assert round(e.value, 1) == 6.0
    e.enemy_played(2.8, cost=4)
    assert round(e.value, 1) == 2.0


def test_defend_on_our_side_then_cooldown():
    tr = walk(lambda t: [(300, 1250 + 50 * t, 70)], 1.0)
    b = Brain()
    hand = ["witch", "tombstone", "poison", "ram"]
    assert b.decide(7, hand, tr.tracks, now=0)[0] == "tombstone"
    assert b.decide(7, hand, tr.tracks, now=1) is None


def test_golem_at_back_is_not_answered_early_but_on_time():
    hand = ["witch", "tombstone", "minions", "log"]
    # slow tank deployed at their back, walking down at 40 px/s: far from the river
    far = walk(lambda t: [(300, 300 + 40 * t, 130)], 2.0)
    assert Brain().decide(7, hand, far.tracks, now=0) is None
    # same tank later, ~1.5s from the river: answer now, before it reaches the bridge
    near = walk(lambda t: [(300, 980 + 40 * t, 130)], 2.0)
    assert near.tracks[0].eta(1100) < 2.0
    assert Brain().decide(7, hand, near.tracks, now=0) is not None


def test_big_deploy_at_back_punished_in_other_lane():
    tr = Tracker()
    tr.update([], 0.0)
    tr.update([(300, 300, 130)], 0.1)                 # Golem-sized bar, left back
    plays = tr.update([(300, 302, 130)], 0.2)
    action = Brain().decide(7, ["hog", "log", "minions", "witch"], tr.tracks, new_plays=plays, now=0)
    assert action[0] == "hog" and action[2] == L.BRIDGE["right"]


def gk_at(x, y):
    """Our own tracks with a Golden Knight at (x, y), labelled the way OwnDeploys does it."""
    tr = Tracker()
    own = OwnDeploys()
    own.played("golden_knight", (x, y), 0.0)
    tr.update([], 0.0)
    tr.update([(x, y, 60, 1.0)], 1.0)
    own.update(tr.update([(x, y, 60, 1.0)], 1.1), 1.1)
    return tr.tracks


def test_own_deploy_gets_labelled():
    assert [t.label for t in gk_at(300, 1300)] == ["golden_knight"]


def test_gk_ability_only_when_gk_can_reach_the_clump():
    clump = [(300, 1250, 50), (340, 1270, 50), (320, 1300, 50), (290, 1320, 50)]
    tr = walk(lambda t: clump, 0.3)
    hand = ["witch", "tombstone", "poison", "ram"]
    near = Brain().decide(5, hand, tr.tracks, allies=gk_at(330, 1380), champion_ready=True, now=0)
    assert near[0] == "gk_ability"
    far = Brain().decide(5, hand, tr.tracks, allies=gk_at(850, 1500), champion_ready=True, now=0)
    assert far is None or far[0] != "gk_ability"
    no_button = Brain().decide(5, hand, tr.tracks, allies=gk_at(330, 1380), champion_ready=False, now=0)
    assert no_button is None or no_button[0] != "gk_ability"


def test_punish_low_enemy_elixir_is_off_until_estimate_is_reliable():
    import bot.brain as B
    hand = ["hog", "log", "minions", "witch"]
    assert Brain().decide(8, hand, [], enemy_elixir=2.0, now=0) is None      # off by default
    old, B.PUNISH_BELOW = B.PUNISH_BELOW, 2.5
    try:
        assert Brain().decide(8, hand, [], enemy_elixir=2.0, now=0)[0] in ("minions", "hog")
        assert Brain().decide(8, hand, [], enemy_elixir=6.0, now=0) is None
    finally:
        B.PUNISH_BELOW = old


def test_champion_button_detected():
    img = cv2.imread(str(FRAME))
    assert vision.champion_ready(img, vision.load_champion_template())


def test_tower_hp_from_bars_1v1():
    start = vision.tower_hp(frame_1v1("1v1_start_goblins.jpg"))
    assert start == {"enemy_left": 1.0, "enemy_right": 1.0, "our_left": 1.0, "our_right": 1.0}
    hp = vision.tower_hp(frame_1v1("1v1_24s.jpg"))
    assert abs(hp["enemy_left"] - 3109 / 4032) < 0.04       # screen shows 3109 of 4032
    assert abs(hp["our_left"] - 1848 / 3668) < 0.04         # screen shows 1848 of 3668
    assert hp["enemy_right"] == 1.0 and hp["our_right"] == 1.0


def test_enemy_badges_full_hp_goblins_and_damaged_troop():
    found = vision.enemies(frame_1v1("1v1_start_goblins.jpg"))
    goblins = [p for p in found if 140 < p[0] < 270 and 1020 < p[1] < 1110]
    assert len(goblins) == 3 and all(p[3] == 1.0 for p in goblins)   # full HP: badge only, no bar
    assert any(abs(p[0] - 76) < 15 and abs(p[1] - 1349) < 15 for p in found)   # damaged, at our tower
    assert len(found) == 4                                   # no tower bars counted as troops


def test_static_filter_learns_scenery_not_troops():
    f = vision.StaticFilter()
    deco, troop = (350, 1570, 32, 1.0), lambda t: (300, 1200 + 40 * t, 40, 1.0)
    for i in range(100):
        t = i * 0.1
        out = f.update([deco, troop(t)], t)
    assert deco not in out and len(out) == 1


def test_witch_kept_out_of_rocket_range_of_our_tower():
    opp = Opponent(["rocket"])
    tx, ty = L.TOWERS["our_right"]
    x, y = opp.safe_spot((tx - 40, ty + 40))                   # right next to our right tower
    assert ((x - tx) ** 2 + (y - ty) ** 2) ** 0.5 >= 4 * 54
    assert Opponent([]).safe_spot((tx - 40, ty + 40)) == (tx - 40, ty + 40)  # no known spell: no change


def test_cycle_rocket_not_in_hand_right_after_use():
    opp = Opponent(["rocket"])
    opp.played("rocket")
    assert not opp.may_have_in_hand("rocket")
    for _ in range(4):
        opp.played(None)
    assert opp.may_have_in_hand("rocket")


def test_spell_finish_poison_then_log_when_safe():
    b = Brain()
    hand = ["poison", "log", "hog", "witch"]
    towers = {"enemy_left": 250 / PRINCESS_MAX_HP, "enemy_right": 1.0}
    first = b.decide(9, hand, [], towers=towers, now=0)
    assert first[0] == "poison"
    second = b.decide(5, ["log", "hog", "witch", "minions"], [], towers=towers, now=1)
    assert second[0] == "log"


def test_spell_finish_not_when_a_push_is_coming():
    push = walk(lambda t: [(300, 1000 + 60 * t, 70)], 0.5)    # ~1.5s from the river
    towers = {"enemy_left": 250 / PRINCESS_MAX_HP, "enemy_right": 1.0}
    act = Brain().decide(9, ["poison", "log", "hog", "tombstone"], push.tracks, towers=towers, now=0)
    assert act is None or act[0] not in ("poison", "log") or act[2][1] > 1000


def test_spell_finish_not_if_it_leaves_us_broke():
    towers = {"enemy_left": 250 / PRINCESS_MAX_HP, "enemy_right": 1.0}
    assert Brain().decide(6, ["poison", "log", "hog", "witch"], [], towers=towers, enemy_elixir=8, now=0) is None


def test_no_double_play_while_ui_catches_up():
    b = Brain()
    hand = ["hog", "log", "minions", "witch"]
    assert b.decide(10, hand, [], now=0)[0] == "minions"        # support first (no dry Hog)
    assert b.decide(10, hand, [], now=0.1) is None             # UI not updated yet
    assert b.decide(5, ["hog", "log", "witch", "tombstone"], [], now=0.5) is None   # gap not over


def test_gk_dead_reckoning():
    own = OwnDeploys()
    own.played("golden_knight", (300, 1500), 0.0)
    assert own.estimate("golden_knight", 0.5) == (300, 1500)    # still deploying
    x, y = own.estimate("golden_knight", 4.0)
    assert y < 1500                                            # walking toward the bridge
    assert own.estimate("golden_knight", 30.0) is None         # too old to trust


def test_empty_slot_is_none():
    img = cv2.imread(str(FRAME)).copy()
    x0, y0, x1, y1 = L.SLOT_BOXES[0]
    img[y0:y1, x0:x1] = (160, 90, 30)                          # plain tray color
    assert vision.hand(img, vision.load_templates())[0] is None


def test_in_match_label():
    tpl = vision.load_next_template()
    assert vision.in_match(frame_1v1("1v1_24s.jpg"), tpl)


def tracked(points, card=None, seconds=0.3):
    tr = walk(lambda t: points, seconds)
    for t in tr.tracks:
        t.card = card
    return tr.tracks


def test_tower_handles_a_lone_damaged_unit():
    assert Brain().decide(7, ["tombstone", "minions", "log", "witch"], tracked([(300, 1250, 40, 0.2)]), now=0) is None


def test_minions_not_placed_into_a_wizard():
    act = Brain().decide(6, ["minions", "golden_knight", "log", "witch"], tracked([(300, 1250, 40, 1.0)], card="wizard"), now=0)
    assert act[0] != "minions"


def test_tombstone_first_vs_charger():
    act = Brain().decide(7, ["minions", "golden_knight", "tombstone", "witch"], tracked([(300, 1250, 40, 1.0)], card="dark_prince"), now=0)
    assert act[0] == "tombstone"


def test_no_attack_that_leaves_us_without_defence():
    assert Brain().decide(6, ["hog", "log", "minions", "witch"], [], now=0) is None      # below 9: no attack
    assert Brain().decide(9.2, ["hog", "log", "tombstone", "poison"], [], now=0) is None # alone needs 9.5 + reserve
    assert Brain().decide(9.6, ["hog", "log", "tombstone", "poison"], [], now=0)[0] == "hog"


def test_hidden_badge_coming_back_is_not_a_new_play():
    tr = Tracker()
    tr.update([], 0.0)
    tr.update([(300, 400, 30, 1.0)], 0.1)
    assert len(tr.update([(300, 400, 30, 1.0)], 0.2)) == 1          # real play
    tr.update([], 1.0)                                              # badge hidden -> track dropped
    tr.update([(305, 410, 30, 1.0)], 1.3)
    assert tr.update([(306, 412, 30, 1.0)], 1.4) == []              # same unit, not a new play


def test_tower_memory_keeps_value_when_bar_hidden():
    m = vision.TowerMemory()
    assert m.update({"our_right": 0.79}, 0)["our_right"] == 0.79
    assert m.update({"our_right": None}, 0.5)["our_right"] == 0.79  # troops on the bar
    m.update({"our_right": 0.05}, 1)
    m.update({"our_right": None}, 1.5)
    assert m.update({"our_right": None}, 4.0)["our_right"] == 0.0   # was low, gone for 2.5s


def test_placements_stay_on_screen_and_on_our_side():
    from bot.brain import clamp
    assert clamp("golden_knight", (1120, 1650)) == (1030, 1650)          # run 000342 bug
    assert clamp("golden_knight", (500, 900))[1] >= 1120                  # troops: our side only
    assert clamp("poison", (500, 600)) == (500, 600)                      # spells: anywhere


def test_full_bar_never_dumps_a_spell():
    """Run 061822: a full-bar Poison on one unknown unit next to their tower woke their king."""
    group = walk(lambda t: [(300, 700, 40, 1.0), (340, 720, 40, 1.0)], 0.3).tracks    # their side
    act = Brain().decide(9.9, [None, "poison", "minions", "tombstone"], group, now=0)
    assert act is None or act[0] != "poison"


def test_spell_touching_their_king_is_worthless():
    from bot.spells import spell_value
    gobs = walk(lambda t: [(560 + 20 * i, 420, 30, 0.2) for i in range(4)], 0.3).tracks
    assert spell_value("poison", (580, 430), gobs) == 0.0

def test_full_bar_builds_a_push_from_the_back():
    act = Brain().decide(10, ["witch", "minions", "tombstone", "log"], [], now=0)
    assert act[0] == "witch" and act[2][1] >= 1600


def test_evo_witch_recognised():
    crop = cv2.imread(str(FRAMES / "slot0_evo_witch.png"))
    img = cv2.imread(str(FRAME)).copy()
    x0, y0, x1, y1 = L.SLOT_BOXES[0]
    img[y0:y1, x0:x1] = crop
    assert vision.hand(img, vision.load_templates(), slots=[0]) == ["witch"]



def test_attack_is_supported_then_win_condition_follows():
    b = Brain()
    sup = b.decide(10, ["hog", "golden_knight", "log", "witch"], [], now=0)
    assert sup[0] == "golden_knight"                                          # GK leads (survives splash)
    win = b.decide(6, ["hog", "minions", "log", "witch"], [], now=1.0)
    assert win[0] == "hog" and math.dist(win[2], sup[2]) < 120              # same bridge, right behind


def test_minions_not_used_into_air_splash_but_fine_vs_ground_splash():
    # owner: a Wizard cooks Minions. Valkyrie splashes too but can't hit air: Minions are fine there.
    risky = Brain(Opponent(["hero_wizard", "spear_goblins"])).decide(10, ["hog", "minions", "log", "tombstone"], [], now=0)
    assert risky is None or risky[0] != "minions"
    safe = Brain(Opponent(["valkyrie", "miner"])).decide(10, ["hog", "minions", "log", "tombstone"], [], now=0)
    assert safe[0] == "minions"


def test_both_lanes_most_urgent_first_and_redefend_when_push_grows():
    b = Brain()
    hand = ["tombstone", "golden_knight", "log", "witch"]
    left = walk(lambda t: [(300, 1000 + 60 * t, 40, 1.0)], 0.5).tracks                  # far, small
    right = walk(lambda t: [(800, 1150 + 60 * t, 120, 1.0), (840, 1170 + 60 * t, 40, 1.0)], 0.5).tracks   # close, big
    first = b.decide(10, hand, left + right, now=0)
    assert first[2][0] > 540                                                 # right lane first
    grown = walk(lambda t: [(800, 1150, 120, 1.0), (840, 1170, 40, 1.0), (820, 1100, 120, 1.0),
                            (790, 1120, 120, 1.0)], 0.3).tracks
    again = b.decide(6, ["golden_knight", "log", "witch", "minions"], grown, now=1.0)
    assert again is not None and again[2][0] > 540                           # push grew: defend again


def test_counter_push_with_survivors():
    survivor = walk(lambda t: [(250, 1250 - 40 * t, 40, 0.5)], 0.5).tracks                # our GK walking up
    act = Brain().decide(6, ["hog", "log", "witch", "minions"], [], allies=survivor, now=0)
    assert act[0] == "hog" and act[2] == L.BRIDGE["left"]


def test_poison_defenders_around_our_hog():
    tx, ty = L.TOWERS["enemy_right"]
    defenders = walk(lambda t: [(tx - 40, ty + 150, 40, 1.0), (tx + 30, ty + 120, 40, 1.0)], 0.3).tracks
    act = Brain().decide(7, ["poison", "log", "witch", "minions"], defenders,
                         own_last={"hog": (854, 1120, 0.0)}, now=4.0)
    assert act[0] == "poison"


def test_ram_defends_a_single_ground_push():
    act = Brain().decide(7, ["ram", "golden_knight", "log", "witch"], tracked([(300, 1250, 40, 1.0)]), now=0)
    assert act[0] == "ram"


def test_opponent_hand_estimate_from_cycle():
    deck = ["evo_barbarians", "hero_wizard", "boss_bandit", "musketeer", "spear_goblins",
            "dark_prince", "valkyrie", "miner"]
    opp = Opponent(deck)
    for c in ["valkyrie", "miner", "spear_goblins", "musketeer"]:
        opp.played(c)
    assert sorted(opp.hand_estimate()) == sorted(["evo_barbarians", "hero_wizard", "boss_bandit", "dark_prince"])


def test_recogniser_is_confident_or_silent():
    from bot.recognizer import DATA, Recognizer
    r = Recognizer()
    paths = [p for d in sorted(DATA.glob("*")) for p in d.glob("*.png")]
    answered = wrong = 0
    for i, p in enumerate(paths):
        label, _ = r.predict(cv2.imread(str(p)), exclude=i)       # leave-one-out
        answered += label is not None
        wrong += label is not None and label != p.parent.name
    assert wrong <= 0.05 * answered and answered >= 0.25 * len(paths)  # precise first; coverage grows with data
    grass = np.full((180, 160, 3), (60, 160, 80), np.uint8)
    assert r.predict(grass)[0] is None


def test_identified_play_updates_cycle():
    opp = Opponent(["valkyrie", "miner"])
    opp.played(None)
    assert opp.identify(0, "valkyrie")
    assert opp.plays == ["valkyrie"] and not opp.may_have_in_hand("valkyrie")


# ---- learning foundation: state, candidates, policy, decision log ----

def _state(**kw):
    from bot.state import State
    base = dict(t=10, elixir=7, regen=0.357, enemy_elixir=5, hand=["hog", "log", "witch", "tombstone"],
                enemy_hand=[], enemy_deck=[])
    base.update(kw)
    return State(**base)


def test_candidates_cover_legal_moves_only():
    from bot.actions import SPELL_GRID, TROOP_GRID, WAIT, candidates
    cands = candidates(_state(elixir=4))                   # witch (5) unaffordable
    cards = {c.card for c in cands if c.kind == "play"}
    assert cards == {"hog", "log", "tombstone"} and cands[0] == WAIT
    assert all(c.y >= L.OUR_DEPLOY_Y[0] for c in cands if c.card in ("hog", "tombstone"))   # troops: our side
    assert any(c.y < L.RIVER_Y for c in cands if c.card == "log")                           # spells: anywhere
    assert len(cands) == 1 + 2 * len(TROOP_GRID) + len(SPELL_GRID)


def test_snap_and_rule_policy_match_the_brain():
    from bot.actions import WAIT, snap
    from bot.policy import Context, RulePolicy
    tracks = tracked([(300, 1250, 40, 1.0)])
    hand = ["witch", "tombstone", "poison", "ram"]
    expected = Brain().decide(7, hand, tracks, now=0)
    chosen, _, _ = RulePolicy(Brain()).choose(_state(elixir=7, hand=hand), Context(tracks=tracks, now=0))
    assert chosen == snap(expected[0], expected[1], expected[2])
    idle, _, _ = RulePolicy(Brain()).choose(_state(elixir=3, hand=hand), Context(now=0))
    assert idle == WAIT


def test_rule_policy_scores_every_candidate():
    from bot.actions import candidates
    from bot.policy import Context, RulePolicy
    st = _state(elixir=7, hand=["witch", "tombstone", "poison", "ram"])
    cands = candidates(st)
    scores = RulePolicy(Brain()).score(st, cands, Context(tracks=tracked([(300, 1250, 40, 1.0)]), now=0))
    assert len(scores) == len(cands) and sorted(scores)[-1] == 1.0 and scores.count(1.0) == 1


def test_decision_log_roundtrip(tmp_path=None):
    import json
    import tempfile
    from pathlib import Path
    from bot.actions import WAIT, Action
    from bot.policy import DecisionLog
    from bot.state import State
    d = Path(tempfile.mkdtemp())
    log = DecisionLog(d)
    st = _state()
    log.record(st, WAIT, "rules", 0.0)
    log.record(st, WAIT, "rules", 0.2)                     # throttled: waits every 0.5s only
    log.record(st, Action("play", "hog", 0, 239, 1201), "rules", 0.3)
    log.close()
    rows = [json.loads(line) for line in open(d / "decisions.jsonl")]
    assert [r["action"]["kind"] for r in rows] == ["wait", "play"]
    assert State(**rows[1]["state"]).hand == st.hand



def test_gk_ability_takes_out_key_backline_troop():
    gk = gk_at(300, 1250)
    front = (310, 1150, 40, 1.0)
    wiz = (320, 900, 40, 1.0)                              # behind the tank, reachable via the chain
    tr = walk(lambda t: [front, wiz], 0.3).tracks
    tr[0].card, tr[1].card = "knight", "hero_wizard"
    act = Brain().decide(3, ["witch", "tombstone", "poison", "ram"], tr, allies=gk, champion_ready=True, now=0)
    assert act[0] == "gk_ability"


def test_log_rolls_through_the_group_center():
    group = walk(lambda t: [(150, 900 + 250 * t, 40, 1.0), (270, 905 + 250 * t, 40, 1.0), (210, 950 + 250 * t, 40, 1.0)], 0.4).tracks
    group[0].vx = -300                                     # badge jitter like run 004519
    xy = Brain()._where("log", "left", group[0], group)
    assert 180 < xy[0] < 240                               # group center, not the screen edge


def test_evo_ram_counted_and_saved_for_attack():
    b = Brain()
    b.note_played("ram"); assert not b.evo_ready("ram")
    b.note_played("ram"); assert b.evo_ready("ram")        # 2 cycles -> next Ram is evolved
    act = b.decide(7, ["ram", "tombstone", "log", "witch"], tracked([(300, 1250, 40, 1.0)]), now=0)
    assert act[0] == "tombstone"                           # defend with something else
    b.note_played("ram"); assert not b.evo_ready("ram")    # the evolved one was used


# ---- step 2: features, outcome labels, blended policy ----

def test_feature_vector_matches_names():
    from bot.actions import Action
    from bot.features import FEATURES, encode
    s = _state().to_dict()
    for a in (Action("wait"), Action("ability", "gk_ability"), Action("play", "log", 1, 300, 900)):
        assert len(encode(s, a.to_dict())) == len(FEATURES)


def test_outcome_label_is_tower_damage_not_elixir_spent():
    from bot.outcomes import ENEMY_TOWER_HP, OUR_TOWER_HP, label, tower_series
    log = [{"t": 0, "towers": {"enemy_left": 1.0, "enemy_right": 1.0, "our_left": 1.0, "our_right": 1.0}},
           {"t": 5, "towers": {"enemy_left": 0.9, "our_left": None}},          # None = keep last value
           {"t": 10, "towers": {"enemy_left": 0.8, "our_right": 0.95}}]
    series = tower_series(log)
    hog = {"state": {"t": 0}, "action": {"kind": "play", "card": "hog"}}
    wait = {"state": {"t": 0}, "action": {"kind": "wait", "card": None}}
    expected = (0.2 * ENEMY_TOWER_HP - 0.05 * OUR_TOWER_HP) / 1000
    assert abs(label(hog, series) - expected) < 1e-6 and label(wait, series) == label(hog, series)

def _blend(beta=None, explore=0.0, seed=1):
    import json as _json
    import random
    from bot.policy import BlendPolicy
    bp = BlendPolicy(Brain(), ROOT_DIR / "models" / "q_lgbm.txt",
                     _json.loads((ROOT_DIR / "models" / "q_meta.json").read_text()),
                     explore=explore, rng=random.Random(seed))
    if beta is not None:
        bp.beta = beta
    return bp


def test_blend_with_no_weight_follows_the_rules():
    from bot.actions import snap
    from bot.policy import Context
    tracks = tracked([(300, 1250, 40, 1.0)])
    hand = ["witch", "tombstone", "poison", "ram"]
    expected = Brain().decide(7, hand, tracks, now=0)
    chosen, cands, _ = _blend(beta=0.0).choose(_state(elixir=7, hand=hand), Context(tracks=tracks, now=0))
    assert chosen == snap(expected[0], expected[1], expected[2]) and len(cands) > 3


def test_prediction_follows_the_lane_to_the_bridge():
    # a unit at their left side walking diagonally toward the bridge (run 010052 Barbarians)
    tr = walk(lambda t: [(120 + 40 * t, 800 + 60 * t, 40, 1.0)], 1.0).tracks
    x, y = tr[0].at(3.0)
    bx, _ = L.BRIDGE["left"]
    assert abs(x - bx) < abs(120 - bx)                     # heads toward the bridge, not off the edge
    assert y > 800


def test_join_our_witch_push_instead_of_a_tombstone():
    # our Witch (no badge at full HP) walking to the left bridge; a lone enemy far on the right
    lone = walk(lambda t: [(760, 900 + 30 * t, 40, 1.0)], 0.4).tracks
    sup = [("witch", "left", (240, 1200))]
    act = Brain().decide(5, ["hog", "tombstone", "log", "minions"], lone, supports=sup, now=0)
    assert act[0] == "hog" and act[2][0] == L.BRIDGE["left"][0]
    save = Brain().decide(3, ["hog", "tombstone", "log", "minions"], lone, supports=sup, now=0)
    assert save is None                                    # can't afford Hog yet: save, no Tombstone


def test_supports_dead_reckoned_from_our_plays():
    own = OwnDeploys()
    own.played("witch", (293, 1579), 0.0)
    (card, lane, (x, y)), = own.supports(8.0)
    assert card == "witch" and lane == "left" and y < 1579
    assert own.supports(20.0) == []                        # assumed gone after 14s


def test_static_filter_tolerates_jitter():
    f = vision.StaticFilter()
    for i in range(100):
        jitter = (i % 3) - 1
        out = f.update([(100 + jitter, 1068 - jitter, 30, 0.9 + 0.01 * jitter)], i * 0.1)
    assert out == []                                       # learned as scenery despite jitter



# ---- round 6: spells by value, troop profiles, luring, splash, king path, memory ----

def labelled(points, card, seconds=0.3):
    tr = walk(lambda t: points, seconds).tracks
    for t in tr:
        t.card = card
    return tr


def test_log_on_full_hp_wizard_and_valkyrie_is_not_worth_it():
    from bot.spells import best_spell, worth_it
    tr = labelled([(420, 600, 40, 1.0)], "hero_wizard") + labelled([(440, 640, 40, 1.0)], "valkyrie")
    _, v = best_spell("log", tr)
    assert not worth_it("log", v)                          # run 010908, 135s: pointless Log


def test_log_kills_the_low_hp_backline():
    front = labelled([(300, 1250, 40, 1.0)], "evo_barbarians")
    musk = labelled([(310, 1120, 40, 0.25)], "musketeer")   # owner: hit the low-HP backup first
    act = Brain().decide(6, ["log", "tombstone", "minions", "witch"], front + musk, now=0)
    assert act[0] == "log"
    from bot.spells import _inside
    assert _inside("log", act[2], (310, 1120))


def test_spear_goblins_get_the_log_not_the_poison():
    gobs = labelled([(800 + 20 * i, 1150 + 10 * i, 30, 1.0) for i in range(5)], "spear_goblins")
    act = Brain().decide(7, ["log", "poison", "golden_knight", "witch"], gobs, now=0)
    assert act[0] == "log"                                 # 2 elixir kills them all; Poison costs 4


def test_poison_half_hp_barbarians_next_to_our_witch_but_not_full_hp_ones():
    from bot.spells import best_spell, worth_it
    ring = [(400 + 90 * math.cos(a), 1200 + 90 * math.sin(a), 30, 0.5) for a in (0, 1.3, 2.6, 3.9, 5.2)]
    half = labelled(ring, "evo_barbarians")
    _, v = best_spell("poison", half, helpers=[(400, 1300)])
    assert worth_it("poison", v)                           # owner round 6
    full = labelled([(x, y, w, 1.0) for x, y, w, _ in ring], "evo_barbarians")
    _, v = best_spell("poison", full)
    assert not worth_it("poison", v)


def test_log_rolling_into_their_tower_is_worth_more():
    from bot.spells import spell_value
    tx, ty = L.TOWERS["enemy_left"]
    gob = labelled([(tx, ty + 200, 30, 1.0)], "spear_goblins")
    into_tower = spell_value("log", (tx, ty + 300), gob)
    beside = spell_value("log", (tx + 250, ty + 300), labelled([(tx + 250, ty + 200, 30, 1.0)], "spear_goblins"))
    assert into_tower > beside


def test_defender_lures_a_musketeer_into_tower_range():
    from bot.brain import TOWER_RANGE_PX
    musk = labelled([(240, 900, 40, 1.0)], "musketeer")[0]
    x, y = Brain()._defend_spot("left", musk, [musk])
    tower = L.TOWERS["our_left"]
    reach = 6.0 * 54                                       # she stops at her range from our troop
    assert math.dist((x, y), tower) + reach <= TOWER_RANGE_PX + 10


def test_defender_not_in_one_splash_with_our_tower():
    from bot.brain import TOWER_HALF_PX
    wiz = labelled([(240, 900, 40, 1.0)], "hero_wizard")[0]
    x, y = Brain()._defend_spot("left", wiz, [wiz])
    assert math.dist((x, y), L.TOWERS["our_left"]) >= TOWER_HALF_PX + 1.5 * 54   # owner round 6, #7


def test_enemies_walk_to_the_king_once_the_lane_tower_is_down():
    import bot.tracker as trk
    tr = walk(lambda t: [(230, 1150 + 60 * t, 30, 1.0)], 1.0).tracks
    try:
        trk.set_alive({"our_left": 0.0, "our_right": 1.0})
        x_dead, _ = tr[0].at(4.0)
        trk.set_alive({"our_left": 1.0, "our_right": 1.0})
        x_alive, _ = tr[0].at(4.0)
    finally:
        trk.set_alive({})
    assert x_dead > x_alive                                # heads toward the king (center), not the dead tower


def test_support_estimate_waits_while_fighting():
    own = OwnDeploys()
    own.played("witch", (293, 1579), 0.0)
    enemy = walk(lambda t: [(300, 1450, 30, 1.0)], 0.2).tracks
    for i in range(1, 60):
        own.advance(i * 0.1, enemy)
    x, y = own.estimate("witch", 5.9)
    assert abs(y - 1579) < 5                               # stayed to fight, didn't walk to the bridge
    own2 = OwnDeploys()
    own2.played("witch", (293, 1579), 0.0)
    for i in range(1, 60):
        own2.advance(i * 0.1, [])
    assert own2.estimate("witch", 5.9)[1] < 1450           # nothing near: walks on


def test_attack_prepares_for_their_usual_swarm_answer():
    opp = Opponent([])
    opp.note_response("hog", "spear_goblins")
    opp.note_response("hog", "spear_goblins")
    b = Brain(opp)
    assert b.decide(9.6, ["hog", "log", "tombstone", "witch"], [], now=0)[0] in ("hog", "witch")
    assert any(q[0] == "log" for q in b.queue)             # pre-cast queued for their Spear Goblins
    poor = Brain(opp)
    assert poor._attack_ready("hog", 5.0, {"hog": 0, "log": 1}) == (False, None)   # can't afford both


def test_features_match_names():
    from bot.actions import Action
    from bot.features import FEATURES, encode
    s = _state().to_dict()
    for a in (Action("wait"), Action("play", "poison", 1, 300, 900)):
        assert len(encode(s, a.to_dict())) == len(FEATURES)



def test_exploration_rolls_once_per_move_and_never_spells():
    from bot.policy import Context
    tracks = tracked([(300, 1250, 40, 1.0)])
    hand = ["witch", "tombstone", "poison", "log"]
    explored = 0
    bp = _blend(beta=0.0, explore=1.0, seed=1)               # explore every time it may
    for i in range(50):                                     # 50 frames ~ 1 second
        bp.brain = bp.rule.brain = Brain()
        chosen, cands, _ = bp.choose(_state(elixir=9, hand=hand), Context(tracks=tracks, now=i * 0.02))
        explored += bp.last_explored
        assert not (chosen.kind == "play" and chosen.card in ("poison", "log") and bp.last_explored)
    assert explored == 1                                    # one roll, then the 10s cooldown


def test_override_leaves_no_rule_bookkeeping_behind():
    from bot.policy import Context
    tracks = tracked([(300, 1250, 40, 1.0)])
    hand = ["witch", "tombstone", "minions", "ram"]
    bp = _blend(beta=0.0, explore=1.0, seed=3)
    chosen, _, _ = bp.choose(_state(elixir=7, hand=hand), Context(tracks=tracks, now=0))
    rule = bp.rule._rule_action(_state(elixir=7, hand=hand), Context(tracks=tracks, now=0))[0]
    assert bp.last_explored and chosen != rule
    assert bp.brain.last_defend["left"] == float("-inf")     # rules' proposal undone
    assert bp.brain.last_action == 0                        # the explored move was committed


# ---- watching the owner: play detection + notes ----

def _frame_with_drop(xy=None):
    img = np.full((2400, 1080, 3), (60, 140, 70), np.uint8)       # grass
    if xy:
        cv2.circle(img, (int(xy[0]), int(xy[1])), 18, (200, 40, 220), -1)   # pink cost drop (BGR)
    return img


def test_detects_owner_play_card_and_spot():
    from bot.observer import HumanPlayDetector, coverage
    det = HumanPlayDetector()
    st = _state()
    hand = ["hog", "log", "witch", "tombstone"]
    t, out = 0.0, []
    for _ in range(10):                                            # steady hand, 8 elixir
        out += det.update(t, _frame_with_drop(), hand, 8.0, st); t += 0.02
    # real plays (owner's ladder matches): the slot goes EMPTY first, the elixir bar drops ~0.2s later
    for i in range(16):
        h = [None, "log", "witch", "tombstone"] if i < 12 else ["minions", "log", "witch", "tombstone"]
        e = 8.0 if i < 6 else 4.0
        drop = (240 - 15, 1150 - 55) if i >= 8 else None           # cost drop appears a bit later
        out += det.update(t, _frame_with_drop(drop), h, e, st); t += 0.03
    assert len(out) == 1
    before, act, (x, y) = out[0]
    assert act.card == "hog" and abs(x - 240) < 5 and abs(y - 1150) < 5
    assert coverage(det) > 0.9


def test_hand_flicker_is_not_a_play():
    from bot.observer import HumanPlayDetector
    det = HumanPlayDetector()
    hand = ["hog", "log", "witch", "tombstone"]
    out = []
    for i in range(20):
        h = ["minions", "log", "witch", "tombstone"] if i == 10 else hand   # one-frame misread
        out += det.update(i * 0.02, _frame_with_drop(), h, 8.0, _state())
    assert out == []


def test_owner_note_overrides_label():
    import tempfile
    from bot.outcomes import apply_notes
    d = Path(tempfile.mkdtemp())
    (d / "notes.jsonl").write_text(json.dumps({"t": 106, "verdict": "bad", "text": "poison on the edge"}) + "\n")
    decisions = [{"state": {"t": 105.5}, "action": {"kind": "play", "card": "poison"}},
                 {"state": {"t": 105.5}, "action": {"kind": "wait", "card": None}},
                 {"state": {"t": 120}, "action": {"kind": "play", "card": "log"}}]
    assert apply_notes(d, decisions, [0.3, 0.1, 0.2]) == [-1.5, 0.1, 0.2]


def test_moves_are_numbers_so_patterns_transfer_between_cards():
    """Owner: 'I can't give you every variation'. Ram in front of our Wizard must look like Hog in
    front of our Witch (both: building-targeter + ranged splash support behind), not like Hog alone."""
    from bot.features import ACTION_FEATURES, action_features
    def move(card, support):
        s = _state(our_units=[[support, 240, 1450]] if support else []).to_dict()
        return np.array(action_features(s, {"kind": "play", "card": card, "slot": 0, "x": 240, "y": 1150}))
    hog_witch, ram_wiz, hog_alone = move("hog", "witch"), move("ram", "hero_wizard"), move("hog", None)
    assert np.linalg.norm(hog_witch - ram_wiz) < np.linalg.norm(hog_witch - hog_alone)
    assert not any(name.startswith("act_hog") or name.startswith("hand_hog") for name in ACTION_FEATURES)


def test_model_cannot_veto_a_move_at_full_elixir():
    """Run 055851: the blended model chose WAIT for 54s at 9-10 elixir in Training Camp."""
    from bot.policy import Context
    bp = _blend(beta=50.0)                                    # even a model that massively prefers waiting
    chosen, _, _ = bp.choose(_state(elixir=9.6, hand=["hog", "golden_knight", "log", "witch"]), Context(now=0))
    assert chosen.kind == "play"


def test_waiting_at_full_bar_is_penalised():
    from bot.outcomes import label, leak_fn, tower_series
    log = [{"t": t / 10, "elixir": 10.0, "regen": 0.357, "towers": {}} for t in range(101)]
    wait = {"state": {"t": 0}, "action": {"kind": "wait", "card": None}}
    assert label(wait, tower_series(log), 10.0, leak_fn(log)) < -0.2       # ~3.6 elixir wasted


def test_goblin_barrel_drop_gets_the_log():
    """3 unknown units appearing at our tower (not walking in) = a barrel drop: Log them."""
    tx, ty = L.TOWERS["our_left"]
    gobs = walk(lambda t: [(tx - 30, ty - 90, 30, 1.0), (tx + 20, ty - 70, 30, 1.0), (tx, ty - 120, 30, 1.0)], 0.3).tracks
    act = Brain().decide(6, ["log", "tombstone", "golden_knight", "witch"], gobs, now=0)
    assert act[0] == "log"


def test_level15_enemy_badge_is_detected():
    """Level-15 badges are orange-red with yellow digits; run 061201 was blind to them."""
    found = vision.enemies(frame_1v1("1v1_level15_prince.jpg"))
    assert any(abs(x - 268) < 20 and abs(y - 824) < 20 for x, y, _, _ in found)


def test_sparky_gets_a_distraction_and_ground_only_threats_get_air():
    sparky = tracked([(300, 1250, 40, 1.0)], card="sparky")
    act = Brain().decide(7, ["minions", "tombstone", "golden_knight", "witch"], sparky, now=0)
    assert act[0] == "tombstone"                              # soaks the charged shot
    gg = tracked([(300, 1250, 40, 1.0)], card="goblin_giant")
    act = Brain().decide(7, ["minions", "golden_knight", "log", "witch"], gg, now=0)
    assert act[0] == "minions"                                # ground-only tank: air answer

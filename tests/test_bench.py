import json
import random

import royalesim

from bot.sim import OUR_DECK, TILE, Sim
from tools import sim_bench as B


def test_screen_tile_round_trip_and_anchors():
    for tx, ty in ((3.5, 6.5), (14.5, 25.5), (9.0, 15.0)):
        x, y = B.to_tile(*B.to_px(tx, ty))
        assert abs(x - tx) < 1e-6 and abs(y - ty) < 1e-6
    px, py = B.to_px(3.5, 6.5)                 # our left princess tower on the phone: (220, 1400)
    assert abs(px - 220) < 5 and abs(py - 1400) < 60


def test_random_player_only_plays_legal_moves():
    sim = Sim()
    sim.start(OUR_DECK, OUR_DECK)
    sim.step(200)
    st, match = sim.state(), B.Match()
    for side in (0, 1):
        for c in B.RandomPlayer(random.Random(0)).act(sim, st, side, match) if st["tick"] % B.THINK == (side * B.STEP) % B.THINK else []:
            assert sim.b.check_deploy(*c) == B.OK


def test_rule_player_maps_its_cards_by_id():
    sim = Sim()
    p = B.RulePlayer(sim)
    assert {p.key[sim.card_id(k)[0]] for k in OUR_DECK} == set(OUR_DECK)


def test_replay_player_rotates_blue_moves_to_red():
    sim = Sim()
    ev = {"side": "team", "kind": "play_card", "card_key": "knight", "replay_tick_20hz": 0,
          "coordinates": {"native_world_units": {"x": 3500, "y": 10500}}}
    knight = sim.card_id("knight")[0]
    sim.b.reset(seed=0, decks=[[knight] * 8, [knight] * 8], shuffle=0, start_tick=0, elixir_milli=[5000, 5000],
                tower_hp=None, spawns=[])
    sim.step(120)
    p = B.ReplayPlayer({"events": [ev]}, "team", B.Mapper(sim), random.Random(0))
    (side, slot, x, y), = p.act(sim, sim.state(), 1, B.Match())
    assert side == 1 and (x, y) == (18 * TILE - 3500 * 18, 32 * TILE - 10500 * 18)
    assert royalesim.DEPLOY_REASONS[sim.b.check_deploy(side, slot, x, y)] == "OK"

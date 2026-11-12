"""RoyaleSim adapter (bot/sim.py). Pinned engine: see requirements.txt."""
from bot.sim import OUR_DECK, OUR_LEVELS, TICKS_PER_S, Sim


def test_our_deck_loads_and_a_card_can_be_played():
    sim = Sim()
    st = sim.start(OUR_DECK, ["giant", "musketeer", "knight", "archers", "fireball", "arrows", "skeletons",
                              "goblin_barrel"], blue_levels=OUR_LEVELS, seed=0)
    assert len([u for u in sim.units(st) if u.tower >= 0]) == 6          # 3 towers per side
    sim.step(5 * TICKS_PER_S)                                            # opening lockout + elixir
    st = sim.state()
    slot = next(i for i, c in enumerate(sim.hand(st, 0)) if sim.cost[c] <= 5)
    assert sim.play(0, slot, 3.5, 12.0) == "OK"                          # own half, left lane


def test_engine_is_deterministic():
    def run():
        sim = Sim()
        sim.start(OUR_DECK, OUR_DECK, seed=7)
        sim.step(30 * TICKS_PER_S)
        return sim.state()["tick"], [p["elixir_milli"] for p in sim.state()["players"]]
    assert run() == run()


def test_replay_card_keys_map_to_the_engine():
    from tools.build_dataset import Mapper
    m = Mapper(Sim())
    for key in ["hog-rider", "battle-ram-ev1", "golden-knight", "the-log", "witch-ev1", "poison", "tombstone",
                "minions", "elite-barbarians-ev1", "guards", "sparky", "executioner", "skeleton-barrel-ev1"]:
        cid, form = m(key)
        assert cid is not None, key
    assert m("battle-ram-ev1")[1] == 1 and m("hog-rider")[1] == 0


def test_own_frame_rotates_the_red_side():
    from tools.build_dataset import own_frame
    assert own_frame(3.5, 30.0, 0) == (3.5, 30.0)
    assert own_frame(3.5, 30.0, 1) == (14.5, 2.0)          # red's own back-left = bottom-right of its view

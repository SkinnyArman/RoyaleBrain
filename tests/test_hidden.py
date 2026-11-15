"""bot.search.Hidden: a search copy holds only what we could know about the opponent."""
import json
import random

from bot.opponent import Opponent
from bot.search import Hidden
from bot.sim import OUR_DECK, Sim
from tools.build_dataset import ElixirCount

# spells and buildings cast on red's own side: nothing walks to our towers, so the match can't end
# before red has shown all 8 cards (our side doesn't defend in these tests)
RED = ["arrows", "fireball", "zap", "poison", "rage", "log", "tombstone", "inferno_tower"]
SPOTS = [(3.5, 28.5), (14.5, 28.5), (9.0, 25.5), (5.5, 26.5), (12.5, 26.5), (9.0, 30.5)]


def _play(sim, tracker, count, n, all_seen=False):
    """Red plays cards it hasn't shown yet first (so all 8 are seen before its troops end the match)."""
    while len(tracker.plays) < n or (all_seen and len(tracker.deck) < 8):
        st = sim.state()
        assert not st["game_over"], "match ended before the test could see enough plays"
        pl = st["players"][1]
        slot = min(range(4), key=lambda k: (pl["hand"][k] in tracker.deck, k))
        card = pl["hand"][slot]
        x, y = SPOTS[len(tracker.plays) % len(SPOTS)]
        if card >= 0 and sim.cost[card] * 1000 <= pl["elixir_milli"] and sim.play(1, slot, x, y, 1) == "OK":
            tracker.played(card)
            count.spend(sim.state()["tick"], 1000 * sim.cost[card])
        sim.step(20)


def test_copy_holds_only_what_we_know():
    sim = Sim()
    sim.start(OUR_DECK, RED, seed=1)
    sim.step(200)
    tracker, count, h = Opponent(), ElixirCount(), Hidden(sim)
    _play(sim, tracker, count, 2)
    before, tick = sim.b.state_hash(), sim.state()["tick"]
    d = json.loads(h.snapshot(sim.b, 1, tracker, count, tick, random.Random(0)))
    assert sim.b.state_hash() == before                                  # the real battle is untouched
    assert abs(d["players"][1]["mana"] / d["mana_unit"] * 1000 - count.value(tick)) < 1   # counted elixir
    seen = {sim.name(c) for c in tracker.deck}
    hidden_real = set(json.loads(sim.b.save())["decks"][1]) - seen       # 6 real cards we haven't seen
    assert seen <= set(d["decks"][1])
    leaked = 0
    for seed in range(20):                                               # unseen real cards appear only by luck
        d = json.loads(h.snapshot(sim.b, 1, tracker, count, tick, random.Random(seed)))
        leaked += len(hidden_real & set(d["decks"][1]))
    assert leaked / 20 < 1.0                                             # chance: 6 of 145 cards -> ~0.3


def test_copy_is_exact_once_everything_is_known():
    sim = Sim()
    sim.start(OUR_DECK, RED, seed=1)
    sim.step(200)
    tracker, count, h = Opponent(), ElixirCount(), Hidden(sim)
    _play(sim, tracker, count, 4, all_seen=True)
    assert len(tracker.deck) == 8
    sim.step(40)
    d = json.loads(h.snapshot(sim.b, 1, tracker, count, sim.state()["tick"], random.Random(0)))
    real = json.loads(sim.b.save())["players"][1]
    assert sorted(d["players"][1]["hand"]) == sorted(real["hand"]) and d["players"][1]["queue"] == real["queue"]

"""The opponent's cycle as we track it (bot/opponent.py), checked against RoyaleSim's real hands."""
import random

from bot.opponent import Opponent
from bot.sim import OUR_DECK, Sim


def test_queue_and_hand_from_plays():
    o = Opponent()
    for c in "abcdefgh":                      # 8 plays, all seen
        o.played(c)
    assert o.queue() == ["e", "f", "g", "h"]  # last 4, oldest first: e comes back next
    assert o.next_card() == "e"
    assert sorted(o.certain_hand()) == ["a", "b", "c", "d"] and o.unknown_hand_slots() == 0


def test_early_match_hand_is_unknown_but_narrowed():
    o = Opponent()
    o.played("a")
    o.played("b")
    assert o.queue() == [None, None, "a", "b"]      # 2 never-played cards come first
    assert o.certain_hand() == [] and o.unknown_hand_slots() == 4
    assert o.next_card() is None


def test_a_missed_play_makes_one_queue_slot_unknown():
    o = Opponent()
    for c in "abcdefg":
        o.played(c)
    o.played(None)                                  # vision missed this one
    assert o.queue() == ["e", "f", "g", None]
    # a, b, c, d are seen and not among the known queue cards, but one of them may be the missed play
    assert o.certain_hand() == [] and o.unknown_hand_slots() == 4
    assert sorted(o.hand_estimate()) == ["a", "b", "c", "d"]     # seen and possibly in hand


def test_sample_is_consistent_with_what_we_know():
    o = Opponent()
    for c in "abcde":
        o.played(c)
    pool = list("abcdefghijklmnop")
    for seed in range(20):
        hand, queue = o.sample(random.Random(seed), pool)
        assert queue[1:] == ["c", "d", "e"]          # known part of the queue
        assert len(hand) == 4 and len(set(hand + queue)) == 8
        assert "a" in hand and "b" not in queue[1:]  # a was played 5 plays ago: back in hand


def test_tracking_matches_the_engine_cycle():
    """Red plays 30 random cards; after every play our tracker's next card / hand match the engine's."""
    sim = Sim()
    red = ["giant", "musketeer", "knight", "archers", "fireball", "arrows", "skeletons", "goblin_barrel"]
    sim.start(OUR_DECK, red, seed=3)
    rng, o = random.Random(0), Opponent()
    sim.step(200)
    while len(o.plays) < 30 and sim.state()["tick"] < 5000:
        pl = sim.state()["players"][1]
        slot = rng.randrange(4)
        card = pl["hand"][slot]
        if card < 0 or sim.cost[card] * 1000 > pl["elixir_milli"]:     # -1: next card still sliding in
            sim.step(20)
            continue
        x = 3.5 if rng.random() < 0.5 else 14.5
        if sim.play(1, slot, x, 20.0, ticks=1) != "OK":
            continue
        o.played(card)
        sim.step(40)                                 # let the next card arrive in the hand
        pl = sim.state()["players"][1]
        if len(o.plays) >= 4:
            assert o.next_card() == pl["next_card"]
        assert set(o.certain_hand()) <= set(pl["hand"])
        if len(o.deck) == 8 and len(o.plays) >= 4:
            assert sorted(o.certain_hand()) == sorted(pl["hand"])
    assert len(o.deck) == 8                          # the test reached the fully-known state

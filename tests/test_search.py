import torch

from bot.model import RoyaleBrain
from bot.search import OK, Policy, Search
from bot.sim import OUR_DECK, Sim


def _setup():
    torch.manual_seed(0)
    sim = Sim()
    sim.start(OUR_DECK, OUR_DECK)
    sim.step(400)                                   # elixir to spend
    model = RoyaleBrain(sim.card_table()).eval()
    return sim, Search(Policy(model, sim.cost), horizon_s=2.0)


def test_search_leaves_the_real_battle_untouched_and_picks_a_legal_move():
    sim, search = _setup()
    before = sim.b.state_hash()
    st = sim.state()
    cands = search.candidates(sim.b, st, 0, set(), 0)
    assert cands[0] is None and len(cands) > 1          # WAIT is always an option
    c = search.choose(sim.b, st, 0, {0: set(), 1: set()}, [0, 0])
    assert sim.b.state_hash() == before                 # rollouts ran on copies
    assert c is None or c in cands
    if c is not None and c[1] < 4:
        assert sim.b.check_deploy(*c) == OK

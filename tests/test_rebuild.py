"""bot/rebuild.py: a live State becomes the right RoyaleSim battle (no phone, no model)."""
import royalesim

from bot.opponent import Opponent
from bot.rebuild import Rebuild
from bot.sim import TILE, Sim, to_px
from bot.state import State, Unit

from tools.build_dataset import Mapper

S = Sim()
M = Mapper(S)


def cid(key):                                   # as bot/live_model.ModelPolicy.cid
    try:
        return S.card_id(key)[0]
    except KeyError:
        return M(key.removeprefix("evo_"))[0]

F = {f: i for i, f in enumerate(royalesim.ENTITY_FIELDS)}


def unit(card, tx, ty, hp=1.0):
    x, y = to_px(tx, ty)
    return Unit(0, "enemy", card, x, y, 0, 0, hp, 20, "left", 99.0)


def test_rebuild_board_hands_elixir_towers():
    rb = Rebuild(cid)
    opp = Opponent()
    for k in ("mega_knight", "evo_witch", None):
        opp.played(k)
    ours = Opponent()
    ours.played(cid("hog"))
    st = State(t=30.0, elixir=6, regen=0.357, enemy_elixir=3.5, hand=["witch", None, "log", "poison"],
               enemy_hand=[], enemy_deck=sorted(opp.deck),
               enemies=[unit("evo_witch", 9, 20, 0.5), unit(None, 4, 16.0)],      # unnamed one in the river
               allies=[], towers={"our_left": 0.0, "our_right": 0.5, "enemy_left": 1.0, "enemy_right": None},
               our_units=[["hog", *to_px(3.5, 18)]])
    b, s, seen, counts, n = rb.build(st, st.enemies, opp, ours)
    assert n == 3
    p0, p1 = s["players"]
    assert p0["hand"][0] == cid("witch") and p0["hand"][2] == cid("log") and p0["hand"][3] == cid("poison")
    assert cid("hog") not in p0["hand"]                     # just played: in the queue
    assert p0["elixir_milli"] == 6000 and p1["elixir_milli"] == 3500
    assert p0["tower_hp"][1] == 0 and abs(p0["tower_hp"][2] - p0["tower_max_hp"][2] // 2) <= 1
    assert p0["king_active"] and not p1["king_active"]      # a fallen princess wakes our king
    assert cid("mega_knight") in p1["deck"] and cid("witch") in p1["deck"]
    assert s["tick"] == 600
    units = [e for e in s["entities"] if e[F["tower_slot"]] < 0]
    witch = [e for e in units if e[F["team"]] == 1 and e[F["card_id"]] == cid("witch")]
    assert witch and witch[0][F["hp"]] < witch[0][F["max_hp"]]
    stand_in = [e for e in units if e[F["team"]] == 1 and e is not witch[0]]
    assert stand_in and stand_in[0][F["card_id"]] == cid("knight")        # unnamed, play size unknown
    assert not 15 * TILE < stand_in[0][F["y"]] < 17 * TILE or abs(stand_in[0][F["x"]] / TILE - 3.5) < 1.5   # on land
    assert counts[1].value(600) == 3500 and cid("mega_knight") in seen[0]


def test_stand_in_by_play_size():
    from types import SimpleNamespace as NS
    rb = Rebuild(cid)
    x, y = to_px(9, 22)
    tr = lambda pi: NS(card=None, x=x, y=y, hp=1.0, play_index=pi)
    enemies = [tr(0), tr(1), tr(1), tr(2), tr(2), tr(2), tr(None)]
    st = State(t=10.0, elixir=5, regen=0.357, enemy_elixir=5, hand=["witch", "ram", "log", "poison"],
               enemy_hand=[], enemy_deck=[], towers={}, our_units=[])
    _, s, _, _, n = rb.build(st, enemies, Opponent(), Opponent())
    import json
    types = json.loads(rb.b.unit_types_json())
    got = sorted(types[e[F["unit_type"]]] for e in s["entities"] if e[F["tower_slot"]] < 0)
    assert got == sorted(["Knight", "Archer", "Archer", "Goblin_Stab", "Goblin_Stab", "Goblin_Stab", "Goblin_Stab"]), got

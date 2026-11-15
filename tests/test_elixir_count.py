from bot.sim import TICKS_PER_S
from tools.build_dataset import ElixirCount

S = TICKS_PER_S


def test_starts_at_5_and_regenerates():
    c = ElixirCount()
    assert c.value(0) == 5000
    assert abs(c.value(28 * S) - 10000) < 1          # 2.8 s per elixir: full after 14 s, capped


def test_cap_holds_while_they_wait_at_full():
    """They sit at 10 for a minute (elixir is lost), then play a 4: they have 6, not 10.
    The old count (5 + all regen - all spent, capped once at the end) said 10."""
    c = ElixirCount()
    c.spend(60 * S, 4000)
    assert abs(c.value(60 * S) - 6000) < 1


def test_double_elixir_after_two_minutes():
    c = ElixirCount()
    c.spend(120 * S, 10000)                          # empty at 2:00
    assert abs(c.value(120 * S + 14 * S) - 10000) < 1    # x2: full again after 14 s, not 28

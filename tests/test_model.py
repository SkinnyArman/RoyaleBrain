"""RoyaleBrain shapes and masking (CPU, random weights)."""
import torch

from bot.model import N_CELLS, RoyaleBrain, trim
from bot.sim import Sim


def test_forward_shapes_and_masked_hand_slots():
    m = RoyaleBrain(Sim().card_table(), d=32, layers=1, heads=2)
    B, P = 3, m.PAD
    unit_ids = torch.full((B, 48), P); unit_ids[:, :2] = 5
    units = torch.zeros(B, 48, 8)
    seen = torch.full((B, 8), P)
    hand = torch.tensor([[1, 2, 3, 4, 5], [1, 2, P, 4, 5], [1, 2, 3, 4, P]])
    unit_ids, units, seen = trim(unit_ids, units, seen, P)
    assert unit_ids.shape[1] == 2 and seen.shape[1] == 1
    sc = torch.zeros(B, 21); sc[0, 12] = 1.0                       # sample 0: ability ready
    out = m(unit_ids, units, sc, hand, seen)
    assert out["card"].shape == (B, 5) and out["tile"].shape == (B, N_CELLS)
    assert out["gate"].shape == (B,) and out["value"].shape == (B,)
    assert out["card"][1].argmax() != 2                     # an empty hand slot is never chosen
    assert out["card"][0, 4] > -1e8 and out["card"][1, 4] < -1e8   # ability only when ready

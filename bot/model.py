"""The policy/value network (R3): reads a board snapshot, outputs what to do and who is winning.

Input = one sample from tools/build_dataset.py, turned into TOKENS (a token = one thing on or around
the board, described by a vector of d numbers):
  1 global token     time, elixir (own + enemy count), 6 tower HP, crowns, overtime
  48 unit tokens     each unit on the board: its card + position, HP, size, flying, own/enemy
  5 hand tokens      the 4 cards in hand + the next card
  8 seen tokens      enemy cards seen so far
A card enters every token TWICE: as a learned identity vector (embedding: "this is Hog Rider") and
as its stats from the engine's card table (cost, HP, radius, kind...). The stats let the model
treat a card it rarely saw like similar cards ("cards as numbers", AGENTS.md).

A transformer lets every token look at every other token (attention), so e.g. a hand card can
"see" which enemies are near which tower. After 4 layers, four small HEADS read the result:
  gate   play now or wait                         (1 logit)
  card   which of the 4 hand cards, or (5th option) the champion/hero ability button
  tile   where, given the card                    (576 scores = 18 x 32 tiles)
  value  probability this player wins the match   (1 logit)
"""
import math

import torch
from torch import nn

N_UNITS, N_HAND, N_SEEN = 48, 5, 8
UNIT_F, N_SCALARS, CARD_F = 8, 21, 12
ABILITY_READY = (12, 16)        # scalar columns: ability button 0 / 1 ready (tools/build_dataset.ability_features)
ABILITY_SLOT = 4
W_TILES, H_TILES = 18, 32
N_CELLS = W_TILES * H_TILES


def trim(unit_ids, units, seen, pad):
    """Drop unit / seen slots that are empty in the WHOLE batch. Units are stored nearest-first, so
    the occupied slots come first. ~4 units per sample on average: 48 slots -> ~20, ~2.5x faster
    training on the Mac GPU (2026-11-11)."""
    nu = max(1, int((unit_ids != pad).sum(1).max()))
    ns = max(1, int((seen != pad).sum(1).max()))
    return unit_ids[:, :nu], units[:, :nu], seen[:, :ns]


class RoyaleBrain(nn.Module):
    def __init__(self, card_table, d=128, layers=4, heads=4):
        super().__init__()
        n_cards = len(card_table)
        self.PAD, self.UNK = n_cards, n_cards + 1          # extra ids: empty slot / unknown card
        table = torch.zeros(n_cards + 2, CARD_F)
        table[:n_cards] = torch.tensor(card_table, dtype=torch.float32)
        self.register_buffer("card_stats", table)          # fixed: the engine's numbers
        self.card_emb = nn.Embedding(n_cards + 2, d)       # learned: identity
        self.stats_in = nn.Linear(CARD_F, d)
        self.unit_in = nn.Linear(UNIT_F, d)
        self.scalar_in = nn.Linear(N_SCALARS, d)
        self.kind = nn.Embedding(4, d)                     # token kind: global / unit / hand / seen
        self.hand_pos = nn.Embedding(N_HAND, d)            # slot 0-3, 4 = next card
        layer = nn.TransformerEncoderLayer(d, heads, dim_feedforward=4 * d, dropout=0.1,
                                           batch_first=True, norm_first=True)
        self.encoder = nn.TransformerEncoder(layer, layers, enable_nested_tensor=False)
        self.norm = nn.LayerNorm(d)
        self.gate = nn.Linear(d, 1)
        self.card_q, self.card_k = nn.Linear(d, d), nn.Linear(d, d)
        self.ability = nn.Linear(d, 1)                     # score of "press the ability button"
        self.tile = nn.Sequential(nn.Linear(2 * d, 2 * d), nn.GELU(), nn.Linear(2 * d, N_CELLS))
        self.value = nn.Sequential(nn.Linear(d, d), nn.GELU(), nn.Linear(d, 1))

    def card(self, ids):
        return self.card_emb(ids) + self.stats_in(self.card_stats[ids])

    def forward(self, unit_ids, units, scalars, hand, seen, chosen_slot=None):
        """ids use self.PAD for empty / self.UNK for unknown. Returns a dict of logits.
        chosen_slot: the hand slot to condition the tile head on (teacher forcing in training);
        default = the card head's best guess."""
        B, dev = units.shape[0], units.device
        k = self.kind.weight
        g = (self.scalar_in(scalars) + k[0]).unsqueeze(1)
        u = self.card(unit_ids) + self.unit_in(units) + k[1]
        h = self.card(hand) + self.hand_pos.weight.unsqueeze(0) + k[2]
        s = self.card(seen) + k[3]
        x = torch.cat([g, u, h, s], 1)
        pad = torch.cat([torch.zeros(B, 1, dtype=torch.bool, device=dev),
                         unit_ids == self.PAD, hand == self.PAD, seen == self.PAD], 1)
        x = self.norm(self.encoder(x, src_key_padding_mask=pad))
        nu = unit_ids.shape[1]                            # units may be trimmed per batch (see trim())
        g, hand_tok = x[:, 0], x[:, 1 + nu:1 + nu + 4]
        card_logits = (self.card_q(g).unsqueeze(1) * self.card_k(hand_tok)).sum(-1) / math.sqrt(g.shape[-1])
        card_logits = card_logits.masked_fill(hand[:, :4] == self.PAD, -1e9)
        ready = (scalars[:, ABILITY_READY[0]] > 0.5) | (scalars[:, ABILITY_READY[1]] > 0.5)
        ability = self.ability(g).masked_fill(~ready.unsqueeze(-1), -1e9)     # only when a button is ready
        card_logits = torch.cat([card_logits, ability], -1)
        if chosen_slot is None:
            chosen_slot = card_logits.argmax(-1)
        chosen = hand_tok[torch.arange(B, device=dev), chosen_slot.clamp(min=0, max=3)]
        return {"gate": self.gate(g).squeeze(-1), "card": card_logits,
                "tile": self.tile(torch.cat([g, chosen], -1)), "value": self.value(g).squeeze(-1)}

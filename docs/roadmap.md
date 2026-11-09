# Roadmap

| Phase | Goal | Status |
|---|---|---|
| 0 | Repo, docs, knowledge base | done |
| 1 | Fast pipeline: scrcpy video capture + scrcpy touch control, per-match logging, measured latency | code written, offline-tested; **not yet run on the phone** |
| 2 | Vision: all 8 card templates, enemy detection checked on real frames, opponent elixir counter | counter, trackers (both teams), tower HP, opponent model written and offline-tested; 4/8 templates; enemy (red) bar colors unverified |
| 3 | Strategy rules (now priors): elixir trade, two-lane defence, supported pushes, counter-pushes, prediction | done (offline-tested), live-testing |
| L1 | Learning foundation: State, candidate actions, Policy interface, decision log, offline replay | done |
| L2 | Outcome labels per decision (tower HP / elixir trade over the next ~10s) + first learned scorer (LightGBM) blended with the rule prior | done (first model trained; beta grows with data) |
| L3a | TV Royale recorder (`./tvroyale N`): replays + both decks + result, saved to datasets/tv | done (tested live 2026-11-09) |
| L3b | tv_extract: both sides' plays (card, spot, time, elixir) from recordings -> outcome-labelled training data + placement spots | next |
| W | Watch mode for the owner's matches + Battle Log ground truth (results, decks) + deck-constrained labelling | done |
| L4 | A/B in practice matches: learned policy becomes default only where it measurably beats rules | later |
| 4 | Deck research from top players' battle logs (official Clash Royale API, needs a key from developer.clashroyale.com) | later |
| 5 | Native Android port (MediaProjection capture + on-device model + AccessibilityService taps) | later |
| - | 2v2 support | owner will specify the extra considerations |

## Useful game features

- **Practice** button on every Battle Log entry: replay against that opponent's exact deck (vs AI).
  Use it to test the bot and placements against real ladder decks (verified: button seen 2026-11-08).

## Known weak spots (2026-11-09)

- Decision quality is the bottleneck, not vision: ~250 logged plays is far too little for the learned
  scorer (held-out rank correlation ~0.3-0.4). TV Royale extraction is the main data source planned.
- No fixed benchmark yet: add one (same Training Camp opponent, N matches per version, wins / crowns /
  tower-damage diff) and require every change to move it.
- Recogniser: 27 classes, few examples each; answers ~31% of units at ~96% precision.

## Open questions

- Exact elixir regen rates and Training Camp card levels (measure from logs).
- Golden Knight ability: exact button position, when it is enabled, what it does.
- Can we identify enemy cards from the health-bar level badge/position alone, or do we need a trained detector (YOLO) for the opponent elixir counter to be accurate?

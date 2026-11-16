"""Plain model vs search on a recorded match's decision states (offline, no phone).

    .venv/bin/python -m tools.search_replay runs/<id> [--model models/r3.pt]

For every logged state where the bot played (the model's gate said play), print what was played then
(plain r3 + the spell guards) and what search picks from the same state (bot/rebuild.py +
bot/search.py). The enemy cycle is rebuilt from the state's seen deck only (no per-play history in
decisions.jsonl), our cycle from our logged plays. Enemy badges inside the layout masks are dropped
(ghosts fixed after the recording, e.g. our tower tops, experiments #37).
"""
import argparse
import json

from bot import layout as L
from bot.live_model import ModelPolicy
from bot.opponent import Opponent
from bot.state import State, Unit


def masked(u):
    return any(x0 <= u.x <= x1 and y0 <= u.y <= y1 for x0, y0, x1, y1 in L.ENEMY_TOWER_BODIES)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--model", default="models/r3.pt")
    a = ap.parse_args()
    opp = Opponent()
    pol = ModelPolicy(a.model, opp, search=True)
    plays = []
    for line in open(f"{a.run}/decisions.jsonl"):
        d = json.loads(line)
        s, act = d["state"], d["action"]
        if act["kind"] == "wait":
            continue
        st = State(**{k: v for k, v in s.items() if k not in ("enemies", "allies")},
                   enemies=[Unit(**u) for u in s["enemies"]], allies=[Unit(**u) for u in s["allies"]])
        st.enemies = [u for u in st.enemies if not masked(u)]
        opp.deck = set(s["enemy_deck"])
        pol.ours = Opponent()
        for c in plays:
            pol.ours.played(pol.cid(c))
        pol.last_think = pol.last_play = -1e9
        pol.last_info = {}
        try:
            enemies = st.enemies
            got, _, _ = pol.act(pol.think(st, enemies, opp, pol.ours, {}), st, 0.0)
            pick = got.card if got.kind == "play" else got.kind
            where = f"({got.x},{got.y})" if got.kind == "play" else ""
        except Exception as e:
            pick, where = f"ERROR {e!r}"[:60], ""
        then = act["card"] or act["kind"]
        foes = ", ".join(f"{u.card or '?'}@({int(u.x)},{int(u.y)}){'' if u.hp >= 0.99 else f' {u.hp:.0%}'}"
                         for u in st.enemies)
        print(f"{s['t']:6.1f}s el {s['elixir']:4.1f} them~{s['enemy_elixir']:4.1f}  then: {then:14s}"
              f" {'' if act['x'] is None else '(%d,%d)' % (act['x'], act['y']):12s}  search: {pick:14s} {where:12s}"
              f" [{pol.last_info.get('search_ms', '-')}ms]  enemies: {foes or '-'}")
        if act["card"] and act["kind"] == "play":
            plays.append(act["card"])


if __name__ == "__main__":
    main()

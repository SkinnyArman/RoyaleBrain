"""Ground truth for recorded matches from the official API: result, crowns, both decks.

    .venv/bin/python -m tools.battlelog            # fetch + attach to recent runs
Needs ~/Desktop/cr-bot/.env (git-ignored) with:
    CR_API_TOKEN=<key from developer.clashroyale.com, for this machine's IP>
    CR_PLAYER_TAG=#XXXXXXXX
Writes runs/<id>/battle.json for each run matched by time. The report and training use it for the
real result, and enemy-crop labelling uses the opponent's 8 cards as the only candidates.
"""
import datetime as dt
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MATCH_WINDOW_S = 5 * 60           # a battle belongs to the run whose start is nearest, within 5 min


def env():
    p = ROOT / ".env"
    vals = dict(os.environ)
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                vals.setdefault(k.strip(), v.strip())
    return vals


def card_key(api_name):
    """Official card name -> our snake_case key (bot/cards.py, recogniser labels)."""
    special = {"Hog Rider": "hog", "Battle Ram": "ram", "The Log": "log", "Mini P.E.K.K.A": "mini_pekka",
               "P.E.K.K.A": "pekka", "X-Bow": "x_bow"}
    if api_name in special:
        return special[api_name]
    return api_name.lower().replace(".", "").replace("-", "_").replace(" ", "_")


def fetch(token, tag):
    tag = "#" + tag.strip().lstrip("#").upper()          # in-game tags are shown with or without "#"
    url = f"https://api.clashroyale.com/v1/players/{urllib.parse.quote(tag)}/battlelog"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=30))
    except urllib.error.HTTPError as e:
        hint = {403: "the key doesn't allow this machine's IP (create a key for your current IP)",
                404: f"no player {tag} (check the tag in your in-game profile)",
                429: "rate limited, try again in a minute"}.get(e.code, e.read().decode(errors="replace")[:200])
        raise SystemExit(f"battle log API error {e.code}: {hint}")


def side(p):
    cards = []
    for c in p.get("cards", []):
        key = card_key(c["name"])
        if c.get("evolutionLevel"):
            key = "evo_" + key
        cards.append(key)
    return {"name": p.get("name"), "tag": p.get("tag"), "crowns": p.get("crowns", 0), "cards": cards}


def main():
    e = env()
    token, tag = e.get("CR_API_TOKEN"), e.get("CR_PLAYER_TAG")
    if not token or not tag:
        raise SystemExit("put CR_API_TOKEN and CR_PLAYER_TAG in ~/Desktop/cr-bot/.env (see this file's docstring)")
    battles = fetch(token, tag)
    runs = sorted(p for p in (ROOT / "runs").iterdir() if p.is_dir() and p.name != "replays"
                  and (p / "summary.json").exists())
    run_start = {r: dt.datetime.strptime(r.name, "%Y%m%d-%H%M%S").astimezone(dt.timezone.utc) for r in runs}
    # battleTime is the match START; a run can start before it (waiting for the match) or a little
    # after it (the watcher restarted while the owner was already in the next match). So: nearest
    # start time, each battle used once (2026-11-09: a one-sided window shifted every match by one).
    when = {i: dt.datetime.strptime(b["battleTime"], "%Y%m%dT%H%M%S.%fZ").replace(tzinfo=dt.timezone.utc)
            for i, b in enumerate(battles)}
    pairs = sorted((abs((when[i] - run_start[r]).total_seconds()), r.name, i) for r in runs for i in when)
    used_runs, used_battles, attached = set(), set(), 0
    for gap, run_name, i in pairs:
        if gap > MATCH_WINDOW_S or run_name in used_runs or i in used_battles:
            continue
        used_runs.add(run_name)
        used_battles.add(i)
        run, b = ROOT / "runs" / run_name, battles[i]
        us, them = side(b["team"][0]), side(b["opponent"][0])
        result = "win" if us["crowns"] > them["crowns"] else "loss" if us["crowns"] < them["crowns"] else "draw"
        (run / "battle.json").write_text(json.dumps({"battle_time": b["battleTime"], "type": b.get("type"),
                                                     "result": result, "us": us, "them": them}, indent=1))
        attached += 1
        print(f"{run.name}: {result} {us['crowns']}-{them['crowns']} vs {them['name']}  their deck: {', '.join(them['cards'])}")
    print(f"{attached} run(s) matched to battles")


if __name__ == "__main__":
    main()

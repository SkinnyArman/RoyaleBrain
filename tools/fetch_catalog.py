"""Refresh data/cards_api.json from the official API (names, elixir, rarity, evo/hero availability).

    CR_API_TOKEN=... .venv/bin/python -m tools.fetch_catalog

The token comes from developer.clashroyale.com and is locked to your IP. Never commit it: it is read
from the environment only.
"""
import json
import os
import time
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "cards_api.json"


def main():
    token = os.environ.get("CR_API_TOKEN")
    if not token:
        raise SystemExit("set CR_API_TOKEN (developer.clashroyale.com key for this machine's IP)")
    req = urllib.request.Request("https://api.clashroyale.com/v1/cards",
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    items = json.load(urllib.request.urlopen(req, timeout=30))["items"]
    cards = [{k: c[k] for k in ("name", "id", "elixirCost", "rarity", "maxLevel", "maxEvolutionLevel") if k in c}
             | {"hero": "heroMedium" in c.get("iconUrls", {}), "icon": c.get("iconUrls", {}).get("medium")}
             for c in items]
    OUT.write_text(json.dumps({"source": f"api.clashroyale.com/v1/cards, fetched {time.strftime('%Y-%m-%d')}",
                               "cards": cards}, indent=1))
    print(f"{len(cards)} cards -> {OUT}")


if __name__ == "__main__":
    main()

"""Download the IL_Replay pro-replay dataset (Hugging Face: VanguardX101/IL_Replay) to datasets/il_replay/.

    .venv/bin/python -m tools.fetch_replays            # all 52 replay shards (~0.83 GB)
    .venv/bin/python -m tools.fetch_replays --limit 4  # first 4 shards (20,000 replays)

Only the `replays/` shards are fetched: each replay's payload already holds every play (the
`actions/` shards are an expanded copy). Resumes partial files, retries, verifies each file's
SHA-256 against the Hub's listing. No license is stated on the dataset: personal research only.
"""
import argparse
import hashlib
import json
import subprocess
import urllib.request
from pathlib import Path

REPO = "VanguardX101/IL_Replay"
OUT = Path(__file__).resolve().parent.parent / "datasets" / "il_replay"


def listing():
    with urllib.request.urlopen(f"https://huggingface.co/api/datasets/{REPO}/tree/main/replays", timeout=60) as r:
        return sorted(json.load(r), key=lambda f: f["path"])


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    files = listing()[: a.limit]
    OUT.mkdir(parents=True, exist_ok=True)
    total = sum(f["size"] for f in files)
    print(f"{len(files)} shards, {total / 1e9:.2f} GB -> {OUT}", flush=True)
    done = 0
    for f in files:
        dest = OUT / Path(f["path"]).name
        want = f["lfs"]["oid"]
        if dest.exists() and dest.stat().st_size == f["size"] and sha256(dest) == want:
            done += f["size"]
            continue
        url = f"https://huggingface.co/datasets/{REPO}/resolve/main/{f['path']}"
        for attempt in range(8):
            subprocess.run(["curl", "-sfL", "-C", "-", "--max-time", "600", "-o", str(dest), url])
            if dest.exists() and dest.stat().st_size >= f["size"]:
                break
        if not dest.exists() or dest.stat().st_size != f["size"] or sha256(dest) != want:
            dest.unlink(missing_ok=True)
            raise SystemExit(f"{dest.name}: download failed or checksum mismatch; run again to retry")
        done += f["size"]
        print(f"  {dest.name} ok  ({done / total:.0%})", flush=True)
    print(f"done: {len(files)} shards verified")


if __name__ == "__main__":
    main()

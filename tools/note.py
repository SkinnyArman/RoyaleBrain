"""Owner feedback on a match moment -> label override for training + insights log. See ./note."""
import argparse
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", help="run id (default: the latest real match)")
    ap.add_argument("seconds", type=float, help="match time of the moment, in seconds from the start")
    ap.add_argument("verdict", choices=["good", "bad"])
    ap.add_argument("text", nargs="?", default="", help="optional: why (for the insights log, not the model)")
    a = ap.parse_args()
    runs = sorted((p for p in (ROOT / "runs").iterdir() if p.is_dir() and p.name != "replays"),
                  key=lambda p: p.stat().st_mtime)
    run = ROOT / "runs" / a.run if a.run else runs[-1]
    note = {"t": a.seconds, "verdict": a.verdict, "text": a.text, "added": time.strftime("%Y-%m-%d %H:%M")}
    with open(run / "notes.jsonl", "a") as f:
        f.write(json.dumps(note) + "\n")
    log = ROOT / "docs" / "insights-log.md"
    if not log.exists():
        log.write_text("# Owner insights log\n\nEvery `./note` lands here. Turn recurring ones into rules, "
                       "features or profile facts, and record that in experiments.md.\n\n")
    with open(log, "a") as f:
        f.write(f"- {note['added']} run {run.name} @ {a.seconds:.0f}s **{a.verdict}**: {a.text}\n")
    print(f"noted on {run.name} at {a.seconds:.0f}s ({a.verdict}). Decisions within 2s get this label "
          f"at the next training.")


if __name__ == "__main__":
    main()

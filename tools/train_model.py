"""Train RoyaleBrain (bot/model.py) on the replay samples (datasets/samples), on the Mac GPU.

    .venv/bin/python -m tools.train_model --steps 3000            # quick run
    .venv/bin/python -m tools.train_model --steps 40000 --name r3a
    .venv/bin/python -m tools.train_model --steps 20000 --name r3b --init models/r3a.pt   # new run from r3a
    ./train                 # the full run (wrapper): live progress bar, Ctrl+C saves, rerun continues
    ./train --status        # how far it is + the last held-out scores

Data: chunk files are streamed (one at a time, shuffled inside) so RAM stays small. Matches whose
global id % 50 == 0 are HELD OUT (never trained on) and used to measure the model honestly.

Loss = gate (play/wait, every sample) + card (plays) + tile (plays) + 0.5 x value (every sample).
Each sample is weighted by 1 / (1 + drift / 3): later, more-drifted moments count less (#21).
Phone realism: 50% of enemy unit ids and 30% of "enemy cards seen" are hidden as UNKNOWN/empty.

Writes models/<name>.pt (saved at every held-out check and on Ctrl+C) and models/<name>.json
(metrics per check). Running again with the same --name continues an unfinished run exactly where it
stopped (weights, optimizer, learning-rate schedule); the run's own settings are used, not new flags.
"""
import argparse
import json
import random
import signal
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from bot.model import H_TILES, W_TILES, RoyaleBrain, trim
from bot.sim import Sim

ROOT = Path(__file__).resolve().parent.parent
DATA, MODELS = ROOT / "datasets" / "samples", ROOT / "models"
VAL_EVERY = 50
WAIT_KEEP = 0.4             # keep 40% of wait samples (there are ~1.6 per play)


def to_tensors(d, idx, model, dev, train):
    """numpy chunk rows -> model inputs + labels on `dev`."""
    PAD, UNK = model.PAD, model.UNK
    unit_ids = torch.from_numpy(d["unit_ids"][idx].astype(np.int64))
    units = torch.from_numpy(d["units"][idx].astype(np.float32))
    hand = torch.from_numpy(d["hand"][idx].astype(np.int64))
    seen = torch.from_numpy(d["enemy_seen"][idx].astype(np.int64))
    if train:
        enemy = (units[..., 0] < 0.5) & (unit_ids >= 0)
        unit_ids[enemy & (torch.rand(unit_ids.shape) < 0.5)] = UNK          # live recognition misses
        seen[(seen >= 0) & (torch.rand(seen.shape) < 0.3)] = -1
    unit_ids[unit_ids < 0] = PAD
    hand[hand < 0] = PAD
    seen[seen < 0] = PAD
    slot = torch.from_numpy(d["label_slot"][idx].astype(np.int64))
    cx = np.clip((d["label_x"][idx] * W_TILES).astype(np.int64), 0, W_TILES - 1)
    cy = np.clip((d["label_y"][idx] * H_TILES).astype(np.int64), 0, H_TILES - 1)
    cell = torch.from_numpy(cy * W_TILES + cx)
    win = torch.from_numpy((d["result"][idx] > 0).astype(np.float32))
    w = torch.from_numpy((1.0 / (1.0 + d["drift"][idx] / 3.0)).astype(np.float32))
    unit_ids, units, seen = trim(unit_ids, units, seen, PAD)
    x = dict(unit_ids=unit_ids, units=units, scalars=torch.from_numpy(d["scalars"][idx].astype(np.float32)),
             hand=hand, seen=seen)
    y = dict(slot=slot, cell=cell, win=win, w=w)
    return ({k: v.to(dev) for k, v in x.items()}, {k: v.to(dev) for k, v in y.items()})


def losses(out, y):
    play = y["slot"] >= 0
    w = y["w"]
    gate = (F.binary_cross_entropy_with_logits(out["gate"], play.float(), reduction="none") * w).mean()
    value = (F.binary_cross_entropy_with_logits(out["value"], y["win"], reduction="none") * w).mean()
    placed = play & (y["slot"] < 4)                       # ability presses have no tile
    card = ((F.cross_entropy(out["card"][play], y["slot"][play], reduction="none") * w[play]).mean()
            if play.any() else torch.zeros((), device=w.device))
    tile = ((F.cross_entropy(out["tile"][placed], y["cell"][placed], reduction="none") * w[placed]).mean()
            if placed.any() else torch.zeros((), device=w.device))
    return gate + card + tile + 0.5 * value, dict(gate=gate, card=card, tile=tile, value=value)


def batches(files, model, dev, bs, train, rng):
    """Stream (inputs, labels): one chunk at a time, train or held-out rows only."""
    files = list(files)
    if train:
        rng.shuffle(files)
    for f in files:
        with np.load(f) as z:                     # decompress ONCE per chunk (lazy npz access re-reads every time)
            d = {k: z[k] for k in z.files}
        held = (d["replay"] % VAL_EVERY) == 0
        keep = ~held if train else held
        if train:
            keep &= (d["label_slot"] >= 0) | (np.random.default_rng(int(rng.random() * 1e9)).random(len(keep)) < WAIT_KEEP)
        idx = np.flatnonzero(keep)
        if train:
            np.random.default_rng(int(rng.random() * 1e9)).shuffle(idx)
        for i in range(0, len(idx), bs):
            yield to_tensors(d, idx[i:i + bs], model, dev, train)


@torch.no_grad()
def evaluate(model, files, dev, max_batches=200):
    """Held-out metrics: how often the model agrees with the pro, and how well it predicts winners."""
    model.eval()
    n = n_play = 0
    gate_ok = card_ok = tile_ok = near_ok = val_ok = n_ab = ab_ok = n_placed = 0
    brier = 0.0
    for b, (x, y) in enumerate(batches(files, model, dev, 1024, False, random.Random(0))):
        if b >= max_batches:
            break
        out = model(**x, chosen_slot=y["slot"].clamp(min=0, max=3))
        play = y["slot"] >= 0
        n += len(play)
        gate_ok += ((out["gate"] > 0) == play).sum().item()
        p = torch.sigmoid(out["value"])
        val_ok += ((p > 0.5) == (y["win"] > 0.5)).sum().item()
        brier += ((p - y["win"]) ** 2).sum().item()
        if play.any():
            n_play += play.sum().item()
            card_ok += (out["card"][play].argmax(-1) == y["slot"][play]).sum().item()
            ab = y["slot"] == 4
            n_ab += ab.sum().item()
            ab_ok += (out["card"][ab].argmax(-1) == 4).sum().item()
            placed = play & ~ab
            n_placed += placed.sum().item()
            pred = out["tile"][placed].argmax(-1)
            tile_ok += (pred == y["cell"][placed]).sum().item()
            dx = (pred % W_TILES - y["cell"][placed] % W_TILES).abs()
            dy = (pred // W_TILES - y["cell"][placed] // W_TILES).abs()
            near_ok += ((dx <= 1) & (dy <= 1)).sum().item()
    model.train()
    return dict(samples=n, plays=n_play, gate_acc=gate_ok / max(1, n), card_acc=card_ok / max(1, n_play),
                tile_exact=tile_ok / max(1, n_placed), tile_within_1=near_ok / max(1, n_placed),
                ability_presses=n_ab, ability_recall=ab_ok / max(1, n_ab),
                win_acc=val_ok / max(1, n), win_brier=brier / max(1, n))


def _hms(s):
    if s == float("inf"):
        return "?"
    s = int(s)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}"


def _bar(frac, width=30):
    return "[" + f"{'#' * int(frac * width):<{width}}" + "]"


def status(path):
    if not path.exists():
        print(f"{path.relative_to(ROOT)}: not started")
        return
    ck = torch.load(path, map_location="cpu", weights_only=False)
    step, total = ck.get("step", ck["args"]["steps"]), ck["args"]["steps"]
    print(f"{_bar(step / total)} {step / total:6.1%}  step {step:,}/{total:,}  "
          + ("finished" if step >= total else "stopped, ./train continues it"))
    hist = json.loads(path.with_suffix(".json").read_text()) if path.with_suffix(".json").exists() else []
    if hist:
        m = hist[-1]
        print(f"last held-out check (step {m['step']:,}): card {m['card_acc']:.1%}  tile within 1 {m['tile_within_1']:.1%}  "
              f"play/wait {m['gate_acc']:.1%}  winner {m['win_acc']:.1%}  ability {m['ability_recall']:.1%}")


def main():
    signal.signal(signal.SIGINT, signal.default_int_handler)
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=3000)
    ap.add_argument("--bs", type=int, default=512)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--d", type=int, default=128)
    ap.add_argument("--layers", type=int, default=4)
    ap.add_argument("--eval-every", type=int, default=1000)
    ap.add_argument("--name", default="r3")
    ap.add_argument("--init", help="start a NEW run from this checkpoint's weights (e.g. models/r3a.pt)")
    ap.add_argument("--status", action="store_true", help="only show how far models/<name>.pt is, then exit")
    a = ap.parse_args()
    path = MODELS / f"{a.name}.pt"
    if a.status:
        return status(path)
    dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    files = sorted(DATA.glob("shard-*-[0-9][0-9].npz"))
    if not files:
        raise SystemExit("no samples: run ./build first")

    # same name, unfinished -> continue that run exactly (weights, Adam, learning-rate schedule, step)
    resume = torch.load(path, map_location="cpu", weights_only=False) if path.exists() else None
    if resume and resume.get("step", resume["args"]["steps"]) >= resume["args"]["steps"]:
        raise SystemExit(f"{path.relative_to(ROOT)} is finished. Train more as a new run: "
                         f"--name {a.name}b --init {path.relative_to(ROOT)}")
    if resume:
        if a.init:
            raise SystemExit(f"{path.relative_to(ROOT)} already exists (unfinished): drop --init to continue it, or pick a new --name")
        keep = {k: a.__dict__[k] for k in ("status",)}
        a.__dict__.update(resume["args"])                   # the run's own settings, not today's flags
        a.__dict__.update(keep)
    rng = random.Random(0)
    torch.manual_seed(0)
    model = RoyaleBrain(Sim().card_table(), d=a.d, layers=a.layers).to(dev)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=0.01)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=a.lr, total_steps=a.steps, pct_start=0.05)
    history, step, prev = [], 0, 0
    if resume:
        model.load_state_dict(resume["model"])
        opt.load_state_dict(resume["optimizer"])
        sched.load_state_dict(resume["scheduler"])
        step, prev = resume["step"], resume["steps_total"] - resume["step"]
        rng = random.Random(step)                          # a different chunk order than the first part
        if path.with_suffix(".json").exists():
            history = json.loads(path.with_suffix(".json").read_text())
        print(f"continuing {path.relative_to(ROOT)} at step {step:,}/{a.steps:,}", flush=True)
    elif a.init:
        ck = torch.load(a.init, map_location="cpu", weights_only=False)
        if (ck["args"]["d"], ck["args"]["layers"]) != (a.d, a.layers):
            raise SystemExit(f"{a.init} has d={ck['args']['d']} layers={ck['args']['layers']}: pass the same --d/--layers")
        model.load_state_dict(ck["model"])
        if "optimizer" in ck:
            opt.load_state_dict(ck["optimizer"])             # keep Adam's running statistics too
            for g in opt.param_groups:
                g["lr"] = a.lr
            sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=a.lr, total_steps=a.steps, pct_start=0.05)
        prev = ck.get("steps_total", ck.get("step", ck["args"]["steps"]))
        print(f"new run from {a.init} (trained {prev:,} steps)", flush=True)
    params = sum(p.numel() for p in model.parameters())
    val_files = random.Random(0).sample(files, min(20, len(files)))     # held-out rows of these chunks
    MODELS.mkdir(exist_ok=True)
    print(f"{len(files)} chunks, model {params / 1e6:.2f}M parameters, device {dev}", flush=True)

    def save():
        torch.save({"model": model.state_dict(), "optimizer": opt.state_dict(), "scheduler": sched.state_dict(),
                    "args": vars(a), "card_table": Sim().card_table(), "init": a.init,
                    "step": step, "steps_total": prev + step}, MODELS / f"{a.name}.tmp")
        (MODELS / f"{a.name}.tmp").replace(path)          # atomic: a crash never leaves a broken checkpoint
        path.with_suffix(".json").write_text(json.dumps(history, indent=1))

    tty = sys.stdout.isatty()
    t0, step0, run, last_line, last_eval = time.time(), step, {}, 0.0, ""

    def draw(final=False):
        nonlocal last_line
        el = time.time() - t0
        rate = (step - step0) / el if el > 0 else 0.0
        eta = (a.steps - step) / rate if rate > 0 else float("inf")
        line = (f"{_bar(step / a.steps)} {step / a.steps:6.1%}  step {step:,}/{a.steps:,}  "
                + " ".join(f"{k} {v:.3f}" for k, v in run.items())
                + f"  {rate:.1f} steps/s  elapsed {_hms(el)}  ETA {_hms(eta)}" + last_eval)
        if tty:
            print("\r\033[K" + line, end="\n" if final else "", flush=True)
        elif final or time.time() - last_line >= 30:       # piped to a file: one line every 30s
            print(line, flush=True)
            last_line = time.time()

    try:
        while step < a.steps:
            for x, y in batches(files, model, dev, a.bs, True, rng):
                loss, parts = losses(model(**x, chosen_slot=y["slot"].clamp(min=0, max=3)), y)
                opt.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
                sched.step()
                step += 1
                if step % 20 == 0:                           # .item() makes the CPU wait for the GPU
                    for k, v in parts.items():
                        v = v.item()
                        run[k] = 0.8 * run.get(k, v) + 0.2 * v
                    draw()
                if step % a.eval_every == 0 or step == a.steps:
                    if tty:
                        print("\r\033[K  checking held-out matches...", end="", flush=True)
                    m = evaluate(model, val_files, dev)
                    m.update(step=step, minutes=round((time.time() - t0) / 60, 1))
                    history.append(m)
                    print(("\r\033[K" if tty else "") + f"  held-out @ {step:,}: "
                          + "  ".join(f"{k} {v:.3f}" if isinstance(v, float) else f"{k} {v}"
                                      for k, v in m.items() if k not in ("step", "minutes")), flush=True)
                    last_eval = f"  | held-out card {m['card_acc']:.1%}"
                    save()
                if step >= a.steps:
                    break
    except KeyboardInterrupt:
        save()
        print(("\r\033[K" if tty else "") + f"\nstopped at step {step:,}/{a.steps:,}: saved {path.relative_to(ROOT)}. "
              "Run the same command again to continue.", flush=True)
        return
    draw(final=True)
    print(f"done: {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

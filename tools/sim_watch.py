"""Play a battle in RoyaleSim and render it to a video you can watch.

    .venv/bin/python -m tools.sim_watch                       # our deck vs a sample deck -> sims/<ts>.mp4
    .venv/bin/python -m tools.sim_watch --red giant,musketeer,knight,archers,fireball,arrows,skeletons,goblin_barrel
    .venv/bin/python -m tools.sim_watch --seed 3 --speed 2 --open

Both sides are played by a simple placeholder player (no trained model exists yet): when it has
enough elixir it plays a random card - troops at a random spot in its own half near a bridge,
spells on the enemy unit closest to its towers. The point is to SEE the engine. Later this tool
takes a trained policy per side.

Rendering: top-down, blue (side 0, us) at the bottom. Circles = units (size = unit radius), bar =
HP, label = card. Squares = towers. Faint discs = spells; dots = projectiles. Header: clock, elixir,
crowns. Encoded with ffmpeg (H.264) so it plays in QuickTime and browsers.
"""
import argparse
import json
import random
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np
import royalesim

from bot.sim import H_TILES, MATCH_TICKS, OUR_DECK, OUR_LEVELS, TICKS_PER_S, TILE, W_TILES, Sim

ROOT = Path(__file__).resolve().parent.parent
PX = 26                                    # pixels per tile
HEADER = 70
BLUE, RED = (230, 140, 40), (60, 60, 225)  # BGR
SAMPLE_RED = ["giant", "musketeer", "knight", "archers", "fireball", "arrows", "skeletons", "goblin_barrel"]


def to_px(x, y):
    """Engine tiles -> image pixels; side 0 (blue) at the bottom, so flip y."""
    return int(x * PX), int(HEADER + (H_TILES - y) * PX)


def draw(sim, st, info):
    img = np.full((HEADER + H_TILES * PX, W_TILES * PX, 3), (88, 140, 70), np.uint8)       # grass
    for ty in range(H_TILES):
        for tx in range(W_TILES):
            if (tx + ty) % 2:
                x0, y0 = to_px(tx, ty + 1)
                cv2.rectangle(img, (x0, y0), (x0 + PX - 1, y0 + PX - 1), (82, 132, 64), -1)
    _, ry0 = to_px(0, 17)
    _, ry1 = to_px(0, 15)
    cv2.rectangle(img, (0, ry0), (W_TILES * PX, ry1), (200, 150, 60), -1)                  # river
    for bx in (3, 14):                                                                     # bridges
        x0, _ = to_px(bx, 0)
        cv2.rectangle(img, (x0, ry0), (x0 + PX, ry1), (70, 110, 150), -1)
    S = {f: i for i, f in enumerate(royalesim.SPELL_FIELDS)}
    for s in st.get("spells", []):
        cx, cy = to_px(s[S["x"]] / TILE, s[S["y"]] / TILE)
        ov = img.copy()
        cv2.circle(ov, (cx, cy), int(2.5 * PX), BLUE if s[S["team"]] == 0 else RED, -1)
        img = cv2.addWeighted(ov, 0.25, img, 0.75, 0)
        cv2.putText(img, sim.name(s[S["card_id"]]), (cx - 20, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
    for u in sorted(sim.units(st), key=lambda u: u.flying):
        cx, cy = to_px(u.x, u.y)
        col = BLUE if u.team == 0 else RED
        if u.tower >= 0:
            half = int(1.5 * PX) if u.tower == 0 else int(1.2 * PX)
            cv2.rectangle(img, (cx - half, cy - half), (cx + half, cy + half), col, -1)
            cv2.rectangle(img, (cx - half, cy - half), (cx + half, cy + half), (30, 30, 30), 2)
            cv2.putText(img, str(u.hp), (cx - half + 2, cy + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1)
            continue
        r = max(4, int(u.radius * PX))
        cv2.circle(img, (cx, cy), r, col if not u.deploying else (200, 200, 200), -1)
        cv2.circle(img, (cx, cy), r, (255, 255, 255) if u.flying else (20, 20, 20), 1)
        w = 2 * r
        frac = max(0.0, u.hp / max(1, u.max_hp))
        cv2.rectangle(img, (cx - r, cy - r - 6), (cx - r + w, cy - r - 3), (40, 40, 40), -1)
        cv2.rectangle(img, (cx - r, cy - r - 6), (cx - r + int(w * frac), cy - r - 3), (80, 220, 80), -1)
        cv2.putText(img, u.name[:10], (cx - r, cy - r - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (255, 255, 255), 1)
    P = {f: i for i, f in enumerate(royalesim.PROJECTILE_FIELDS)}
    for p in st.get("projectiles", []):
        cv2.circle(img, to_px(p[P["x"]] / TILE, p[P["y"]] / TILE), 3, (240, 240, 240), -1)
    # header
    cv2.rectangle(img, (0, 0), (img.shape[1], HEADER), (35, 35, 35), -1)
    left = max(0, MATCH_TICKS - st["tick"]) // TICKS_PER_S
    clock = f"{left // 60}:{left % 60:02d}" if not st["overtime"] else "overtime"
    pl = st["players"]
    cv2.putText(img, clock, (img.shape[1] // 2 - 30, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    cv2.putText(img, f"red  elixir {pl[1]['elixir_milli'] / 1000:4.1f}  crowns {pl[1]['crowns']}",
                (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.45, RED, 1)
    cv2.putText(img, f"blue elixir {pl[0]['elixir_milli'] / 1000:4.1f}  crowns {pl[0]['crowns']}",
                (8, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.45, BLUE, 1)
    if info:
        cv2.putText(img, info[-1], (8, HEADER - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (200, 200, 200), 1)
    return img


def placeholder_move(sim, st, side, rng):
    """Random affordable card: troops near a bridge in own half, spells on the enemy unit nearest us."""
    pl = st["players"][side]
    hand, elixir = pl["hand"], pl["elixir_milli"] / 1000
    options = [i for i, c in enumerate(hand) if c is not None and c >= 0 and sim.cost[c] <= elixir]
    if not options or elixir < 6.5 + rng.random() * 3:
        return None
    slot = rng.choice(options)
    card = hand[slot]
    kind = sim.catalogue[card][8]
    if kind == "SPELL":
        foes = [u for u in sim.units(st) if u.team != side and u.tower < 0]
        if not foes:
            return None
        u = min(foes, key=lambda u: u.y if side == 0 else -u.y)
        return slot, u.x, u.y
    lane_x = rng.choice([3.5, 14.5]) + rng.uniform(-1.5, 1.5)
    y = rng.uniform(10, 14.5) if side == 0 else rng.uniform(17.5, 22)
    return slot, lane_x, y


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blue", default=",".join(OUR_DECK))
    ap.add_argument("--red", default=",".join(SAMPLE_RED))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--speed", type=float, default=1.0, help="1 = real time, 2 = twice as fast")
    ap.add_argument("--open", action="store_true", help="open the video when done")
    a = ap.parse_args()

    sim, rng = Sim(), random.Random(a.seed)
    st = sim.start(a.blue.split(","), a.red.split(","), blue_levels=OUR_LEVELS, seed=a.seed)
    out = ROOT / "sims" / f"{time.strftime('%Y%m%d-%H%M%S')}_seed{a.seed}.mp4"
    out.parent.mkdir(exist_ok=True)
    fps = 20
    h, w = draw(sim, st, []).shape[:2]
    enc = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
                            "-s", f"{w}x{h}", "-r", str(fps), "-i", "-", "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", str(out)], stdin=subprocess.PIPE)
    ticks_per_frame = max(1, round(a.speed * TICKS_PER_S / fps))
    log, plays = [], 0
    while not st["game_over"] and st["tick"] < MATCH_TICKS + 3 * 60 * TICKS_PER_S:
        for side in (0, 1):
            if st["tick"] % 10 == side * 5:                       # each side thinks twice a second
                m = placeholder_move(sim, st, side, rng)
                if m:
                    slot, x, y = m
                    name = sim.name(st["players"][side]["hand"][slot])
                    why = sim.play(side, slot, x, y, ticks=0)
                    if why == "OK":
                        plays += 1
                        log.append(f"{'blue' if side == 0 else 'red'}: {name}")
        sim.step(ticks_per_frame)
        st = sim.state()
        enc.stdin.write(draw(sim, st, log).tobytes())
    for _ in range(fps * 2):                                       # hold the final frame
        enc.stdin.write(draw(sim, st, log + [f"winner: {['blue', 'red'][st['winner']] if st['winner'] in (0, 1) else 'draw'}"]).tobytes())
    enc.stdin.close()
    enc.wait()
    crowns = [p["crowns"] for p in st["players"]]
    print(f"{plays} plays, blue {crowns[0]} - {crowns[1]} red, {st['tick'] / TICKS_PER_S:.0f}s -> {out}")
    if a.open:
        subprocess.run(["open", str(out)])


if __name__ == "__main__":
    main()

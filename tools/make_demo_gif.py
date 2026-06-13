"""Render the hero mission to an animated GIF for the README.

Pure-Pillow renderer (no matplotlib/imageio needed): runs the default scenario
deterministically, draws each tick's map + a small HUD, and writes a looping GIF
that shows ~100 agents lose a third of the fleet to a shock wave and reorganize
to finish the mission.

    python tools/make_demo_gif.py [--strategy global] [--out docs/demo.gif]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ghost_commander.sim import PRESETS, run_scenario  # noqa: E402

# canvas
_W, _H = 540, 600
_HUD_H = 60
_PAD = 16
_BG = (14, 17, 23)
_PANEL = (22, 27, 37)

_STATUS = {
    "idle": (127, 140, 155),
    "moving": (58, 160, 255),
    "working": (39, 209, 124),
    "recharging": (176, 108, 255),
    "failed": (224, 72, 79),
}
_PRIO_R = {1: 3, 2: 4, 3: 5, 4: 6, 5: 7}


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in (("arialbd.ttf", "arial.ttf") if not bold else ("arialbd.ttf",)):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


_F_BIG = _font(26, bold=True)
_F_MED = _font(15)
_F_SHOCK = _font(30, bold=True)


def _to_px(x: float, y: float, w: float, h: float) -> tuple[float, float]:
    area = _H - _HUD_H - 2 * _PAD
    sx = _PAD + (x / w) * (_W - 2 * _PAD)
    sy = _HUD_H + _PAD + (1 - y / h) * area  # flip y so up is up
    return sx, sy


def _render_frame(frame: dict, shock: bool) -> Image.Image:
    world = frame["world"]
    w, h = world.get("width", 200.0), world.get("height", 200.0)
    m = frame["metrics"]
    img = Image.new("RGB", (_W, _H), _BG)
    d = ImageDraw.Draw(img)

    # HUD
    d.rectangle([0, 0, _W, _HUD_H], fill=_PANEL)
    d.text((_PAD, 8), "GHOST COMMANDER", font=_F_BIG, fill=(230, 235, 243))
    alive, total = m["agents_alive"], m["agents_total"]
    mc = m["mission_completion"] * 100
    sub = f"tick {m['tick']:>3}   ·   misión {mc:4.0f}%   ·   agentes {alive}/{total}"
    d.text((_PAD, 39), sub, font=_F_MED, fill=(154, 166, 184))
    # mission progress bar
    bar_x0, bar_w = _W - 180, 160
    d.rectangle([bar_x0, 24, bar_x0 + bar_w, 34], fill=(32, 40, 54))
    d.rectangle([bar_x0, 24, bar_x0 + int(bar_w * mc / 100), 34], fill=(39, 209, 124))

    # bases
    for bx, by in world.get("bases", []):
        px, py = _to_px(bx, by, w, h)
        d.polygon([(px, py - 7), (px + 7, py), (px, py + 7), (px - 7, py)],
                  fill=(25, 195, 214))

    # tasks: open = amber square, done = dim outline
    for t in world["tasks"]:
        px, py = _to_px(t["x"], t["y"], w, h)
        r = _PRIO_R.get(t["priority"], 4)
        if t["status"] == "done":
            d.rectangle([px - r, py - r, px + r, py + r], outline=(52, 64, 107))
        elif t["status"] == "failed":
            d.line([(px - r, py - r), (px + r, py + r)], fill=(224, 72, 79), width=2)
            d.line([(px - r, py + r), (px + r, py - r)], fill=(224, 72, 79), width=2)
        else:
            d.rectangle([px - r, py - r, px + r, py + r], fill=(244, 185, 66))

    # agents
    for a in world["agents"]:
        if a["status"] == "failed":
            continue  # vanished — the fleet visibly thins
        px, py = _to_px(a["x"], a["y"], w, h)
        c = _STATUS.get(a["status"], (200, 200, 200))
        d.ellipse([px - 2.6, py - 2.6, px + 2.6, py + 2.6], fill=c)

    if shock:
        d.rectangle([0, 0, _W - 1, _H - 1], outline=(224, 72, 79), width=4)
        txt = "ONDA DE CHOQUE"
        tw = d.textlength(txt, font=_F_SHOCK)
        d.text(((_W - tw) / 2, _H / 2 - 20), txt, font=_F_SHOCK, fill=(224, 72, 79))

    return img


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="global")
    ap.add_argument("--out", default="docs/demo.gif")
    ap.add_argument("--preset", default="default")
    args = ap.parse_args()

    rec = run_scenario(PRESETS[args.preset], args.strategy)
    shock_tick = PRESETS[args.preset].shock_tick

    frames: list[Image.Image] = []
    durations: list[int] = []
    for frame in rec.frames:
        tick = frame["tick"]
        is_shock = shock_tick is not None and shock_tick <= tick <= shock_tick + 1
        frames.append(_render_frame(frame, is_shock))
        durations.append(700 if is_shock else 90)
    # hold the final state
    frames += [frames[-1]] * 12
    durations += [120] * 12

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # quantize to keep the GIF small
    quant = [f.quantize(colors=128, method=Image.Quantize.FASTOCTREE) for f in frames]
    quant[0].save(out, save_all=True, append_images=quant[1:], duration=durations,
                  loop=0, optimize=True, disposal=2)
    kb = out.stat().st_size / 1024
    print(f"wrote {out} · {len(frames)} frames · {kb:.0f} KB")


if __name__ == "__main__":
    main()

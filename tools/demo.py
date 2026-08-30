#!/usr/bin/env python3
"""Render the tradesights demo from a real scan.

Every number in this animation came out of `tradesights scan` on a live run:
43 names, their actual z-scores, their actual divergences, and the headline
strings the tool actually generated. Regenerate `data.json` by re-running the
scan and the animation follows.

The scene order is the argument the tool is making, in order:

  layers    — three things you can know about a name, and the claim that the
              interesting information is the DISTANCE between them, not any one
              of them. Without this the rest is a table of numbers.

  scan      — the command, and the ranked answer.

  map       — the whole universe plotted, because the ranked list cannot tell
              you whether today is unusual. Five names above divergence 2 is
              either a market coming apart or a Tuesday, and the top of a table
              looks identical either way.

  caveat    — "a question, not a call". Ending on the disclaimer rather than
              burying it is the honest version of this demo, and it happens to
              be the more interesting claim.

Usage:  python3 tools/demo.py <data.json> <outdir>
        ffmpeg -framerate 20 -i <outdir>/%04d.png -c:v libx264 -pix_fmt yuv420p demo.mp4
"""
from __future__ import annotations

import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

W, H = 1000, 620
FPS = 20

BG      = (0x0F, 0x14, 0x19)
RAISED  = (0x17, 0x1D, 0x26)
LINE    = (0x23, 0x2B, 0x35)
HEADING = (0xE8, 0xED, 0xF2)
BODY    = (0xA8, 0xB3, 0xBF)
MUTED   = (0x7C, 0x88, 0x96)
FAINT   = (0x5A, 0x66, 0x73)
ACCENT  = (0x00, 0xD4, 0xAA)
UP      = (0x4A, 0xDE, 0x80)
WARN    = (0xE8, 0xB3, 0x39)
DOWN    = (0xE5, 0x48, 0x4D)

FONT_DIRS = [
    os.environ.get("TRADESIGHTS_FONTS", ""),
    "/usr/share/fonts/truetype/jetbrains-mono",
    os.path.expanduser("~/.local/share/fonts"),
]


def font(size: int, weight: str = "Regular") -> ImageFont.FreeTypeFont:
    for folder in FONT_DIRS:
        if folder:
            path = os.path.join(folder, f"JetBrainsMono-{weight}.ttf")
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
    fallback = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono%s.ttf" % (
        "-Bold" if weight != "Regular" else "")
    return (ImageFont.truetype(fallback, size) if os.path.exists(fallback)
            else ImageFont.load_default())


F_HERO = font(56, "ExtraBold")
F_H1   = font(30, "Bold")
F_H2   = font(21, "Bold")
F_BODY = font(18)
F_MONO = font(16)
F_SM   = font(14)
F_TINY = font(12)


def ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def mix(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


def mark(draw, x, y, size, colour=ACCENT):
    """Two brackets holding a lamp. Brackets at 55%, lamp solid."""
    u = size / 32
    dim = mix(BG, colour, 0.55)
    wgt = max(1, round(2.4 * u))
    for x0, x1 in ((12, 7.5), (20, 24.5)):
        draw.line([(x + x0 * u, y + 6.5 * u), (x + x1 * u, y + 6.5 * u)], dim, wgt)
        draw.line([(x + x1 * u, y + 6.5 * u), (x + x1 * u, y + 25.5 * u)], dim, wgt)
        draw.line([(x + x1 * u, y + 25.5 * u), (x + x0 * u, y + 25.5 * u)], dim, wgt)
    r = 3.5 * u
    draw.ellipse([x + 16 * u - r, y + 16 * u - r, x + 16 * u + r, y + 16 * u + r], fill=colour)


def frame():
    img = Image.new("RGB", (W, H), BG)
    return img, ImageDraw.Draw(img)


def chrome(d, label):
    d.rectangle([0, 0, W, 54], fill=RAISED)
    d.line([(0, 54), (W, 54)], LINE, 1)
    mark(d, 22, 13, 28)
    d.text((62, 16), "tradesights", HEADING, F_H2)
    d.text((W - 24, 20), label, MUTED, F_SM, anchor="ra")


def wrap(text, width):
    words, lines, cur = text.split(), [], ""
    for word in words:
        if len(cur) + len(word) + 1 > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    lines.append(cur)
    return lines


# ---------------------------------------------------------------------------

def scene_title(n):
    out = []
    for i in range(n):
        img, d = frame()
        mark(d, W // 2 - 30, 168, 60, mix(BG, ACCENT, ease(i / (n * 0.45))))
        d.text((W // 2, 280), "tradesights", mix(BG, HEADING, ease((i - 6) / (n * 0.4))),
               F_HERO, anchor="ma")
        d.text((W // 2, 354), "where price, positioning and talk stop agreeing",
               mix(BG, BODY, ease((i - 14) / (n * 0.4))), F_BODY, anchor="ma")
        f = ease((i - n * 0.45) / (n * 0.4))
        d.line([(W // 2 - 90, 396), (W // 2 + 90, 396)], mix(BG, LINE, f), 1)
        d.text((W // 2, 416), "CLANKER LABS", mix(BG, FAINT, f), F_SM, anchor="ma")
        out.append(img)
    return out


def scene_layers(n):
    """Three bars that agree, then stop agreeing. The premise, in one picture."""
    layers = [
        ("PRICE", "what it did", ACCENT),
        ("POSITIONING", "what the options market paid for", UP),
        ("TALK", "what people said", MUTED),
    ]
    out = []
    for i in range(n):
        img, d = frame()
        chrome(d, "three layers")
        d.text((60, 84), "Three things you can know about a name.", HEADING, F_H2)

        for k, (name, sub, colour) in enumerate(layers):
            f = ease((i - k * 9) / 14)
            y = 152 + k * 92
            d.text((60, y), name, mix(BG, colour, f), F_MONO)
            d.text((60, y + 24), sub, mix(BG, FAINT, f), F_SM)
            # They start aligned and separate. The separation IS the product.
            drift = ease((i - 52) / 40) * (k - 1) * 150
            x0 = 380 + drift
            d.rectangle([x0, y + 2, x0 + 200, y + 16], fill=mix(BG, colour, f * 0.75))

        if i > 96:
            f = ease((i - 96) / 18)
            d.text((60, H - 118), "The interesting part is the distance between them.",
                   mix(BG, HEADING, f), F_H2)
            d.text((60, H - 78),
                   "A price chart is the layer everybody already has. This measures",
                   mix(BG, MUTED, f), F_SM)
            d.text((60, H - 56), "how far it has drifted from the other two.",
                   mix(BG, MUTED, f), F_SM)
        out.append(img)
    return out


def scene_scan(data, n):
    picks = data["rows"][:4]
    cmd = "tradesights scan"
    out = []
    for i in range(n):
        img, d = frame()
        chrome(d, f"{data['n']} names")
        typed = cmd[:min(len(cmd), int(i / 1.4))]
        d.text((60, 92), "$", ACCENT, F_H1)
        d.text((92, 92), typed, HEADING, F_H1)
        if typed != cmd and (i // 5) % 2 == 0:
            d.rectangle([94 + len(typed) * 18, 94, 107 + len(typed) * 18, 124], fill=ACCENT)

        if typed == cmd:
            f = ease((i - 26) / 12)
            d.text((60, 148), f"scanned {data['n']} names, {data['n']} with usable "
                              f"option chains", mix(BG, FAINT, f), F_SM)

        shown = max(0, (i - 40) // 16)
        for k, row in enumerate(picks[:shown]):
            f = ease((i - 40 - k * 16) / 14)
            y = 190 + k * 96
            d.text((60, y), f"{k+1}.", mix(BG, ACCENT, f), F_MONO)
            head = wrap(row["headline"], 66)
            for li, line in enumerate(head[:2]):
                d.text((96, y + li * 24), line,
                       mix(BG, HEADING if li == 0 else BODY, f), F_MONO)
            d.text((96, y + 24 * min(2, len(head))),
                   f"divergence {row['divergence']:.2f}", mix(BG, FAINT, f), F_SM)
            # The bar makes the ranking legible without reading four decimals.
            span = int(row["divergence"] / picks[0]["divergence"] * 150)
            d.rectangle([W - 60 - span, y + 4, W - 60, y + 14],
                        fill=mix(BG, ACCENT, f * 0.5))
        out.append(img)
    return out


def scene_map(data, n):
    """The whole universe, so you can see whether today is unusual."""
    rows = data["rows"]
    span = max(2.0, max(max(abs(r["price_z"]), abs(r["money_z"])) for r in rows) * 1.1)
    L, R, T, B = 300, 60, 96, 64
    iw, ih = W - L - R, H - T - B

    def X(v):
        return L + (v + span) / (2 * span) * iw

    def Y(v):
        return T + ih - (v + span) / (2 * span) * ih

    ranked = sorted(rows, key=lambda r: -r["divergence"])
    named = {r["symbol"] for r in ranked[:5]}
    colour = {"contrarian_bid": UP, "hedged_rally": DOWN,
              "chase": MUTED, "fear": MUTED, "quiet": (0x4a, 0x50, 0x4a)}

    out = []
    for i in range(n):
        img, d = frame()
        chrome(d, "the whole universe")
        f0 = ease(i / 14)
        d.text((60, 100), "A ranked list", mix(BG, HEADING, f0), F_H2)
        for li, line in enumerate(wrap(
                "cannot tell you whether today is unusual. Five names above a "
                "divergence of 2 is either a market coming apart, or a Tuesday.", 26)):
            d.text((60, 138 + li * 24), line, mix(BG, BODY, ease((i - 10) / 16)), F_SM)
        # 310, not 268: the block above wraps to six lines and the two collided.
        # Nothing measures text here, so vertical budgets are counted by hand.
        for li, line in enumerate(wrap(
                "Plotting all 43 shows the difference at a glance.", 26)):
            d.text((60, 310 + li * 24), line, mix(BG, MUTED, ease((i - 30) / 16)), F_SM)

        cx, cy = X(0), Y(0)
        fg = ease((i - 6) / 20)
        d.rectangle([L, T, cx, cy], fill=mix(BG, UP, 0.05 * fg))
        d.rectangle([cx, cy, W - R, T + ih], fill=mix(BG, DOWN, 0.05 * fg))
        for v in (-2, -1, 1, 2):
            if abs(v) <= span:
                d.line([(X(v), T), (X(v), T + ih)], mix(BG, LINE, fg), 1)
                d.line([(L, Y(v)), (W - R, Y(v))], mix(BG, LINE, fg), 1)
        d.line([(L, cy), (W - R, cy)], mix(BG, MUTED, fg), 1)
        d.line([(cx, T), (cx, T + ih)], mix(BG, MUTED, fg), 1)

        shown = min(len(ranked), int(ease((i - 16) / (n * 0.5)) * len(ranked)))
        for row in reversed(ranked[:shown]):
            x, y = X(row["price_z"]), Y(row["money_z"])
            lead = row["symbol"] in named
            col = colour[row["quadrant"]]
            r = 6 if lead else 3.5
            d.ellipse([x - r, y - r, x + r, y + r], fill=col)
            if lead:
                anchor = "ra" if x > W * 0.70 else "la"
                d.text((x + (-11 if anchor == "ra" else 11), y - 8), row["symbol"],
                       HEADING, F_TINY, anchor=anchor)

        if i > n * 0.66:
            f = ease((i - n * 0.66) / (n * 0.24))
            d.text((L + 8, T + 10), "someone is paying for a bounce",
                   mix(BG, UP, f), F_TINY)
            d.text((W - R - 8, T + ih - 20), "holders are nervous",
                   mix(BG, DOWN, f), F_TINY, anchor="ra")
            d.text((L, H - 34), "price vs the market →", mix(BG, FAINT, f), F_TINY)
        out.append(img)
    return out


def scene_end(data, n):
    out = []
    for i in range(n):
        img, d = frame()
        f1 = ease(i / 14)
        mark(d, W // 2 - 22, 156, 44, mix(BG, ACCENT, f1))
        d.text((W // 2, 236), "a question,", mix(BG, HEADING, f1), F_H1, anchor="ma")
        d.text((W // 2, 278), "not a call", mix(BG, ACCENT, ease((i - 10) / 14)),
               F_H1, anchor="ma")
        f2 = ease((i - 26) / 16)
        d.text((W // 2, 348), "no order execution, and no path to a broker",
               mix(BG, MUTED, f2), F_BODY, anchor="ma")
        d.text((W // 2, 378), "that is a design rule, not a missing feature",
               mix(BG, FAINT, f2), F_SM, anchor="ma")
        f3 = ease((i - 42) / 16)
        d.line([(W // 2 - 110, 428), (W // 2 + 110, 428)], mix(BG, LINE, f3), 1)
        d.text((W // 2, 448), "CLANKER LABS", mix(BG, FAINT, f3), F_SM, anchor="ma")
        out.append(img)
    return out


def main():
    data = json.load(open(sys.argv[1]))
    outdir = sys.argv[2]
    os.makedirs(outdir, exist_ok=True)
    frames = (scene_title(int(FPS * 2.4))
              + scene_layers(int(FPS * 6.2))
              + scene_scan(data, int(FPS * 6.4))
              + scene_map(data, int(FPS * 6.0))
              + scene_end(data, int(FPS * 3.4)))
    for i, img in enumerate(frames):
        img.save(os.path.join(outdir, f"{i:04d}.png"))
    print(f"{len(frames)} frames → {outdir}  ({len(frames)/FPS:.1f}s at {FPS}fps)")


if __name__ == "__main__":
    main()

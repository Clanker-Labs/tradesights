"""The one chart worth drawing, and why the others were not.

The screener's output is a ranked list, and a ranked list is the right shape for
"what should I look at this morning". It is the wrong shape for one question the
list cannot answer: *is today unusual*. Five names with a divergence above 2 is
either a market coming apart or a Tuesday, and nothing in a top-five table tells
you which.

The quadrant map does, because it plots the whole universe rather than the top
of it. Price on one axis, positioning on the other, both z-scored against the
names scanned in the same run -- which is not a decorative choice, it is the
only reason a utility and a biotech can share a plot at all. A morning where
everything sits in the middle looks like a cloud around the origin. A morning
where the options market has stopped agreeing with price looks like two
diagonal wings, and you can see that in a second without reading a number.

Deliberately NOT drawn:

*A time series of divergence.* It would need history this tool does not keep,
and drawing it from a single day's snapshot would mean fabricating the past.

*Sector heatmaps.* Eleven coloured squares that say "tech is up", which is a
thing you already know, presented as though it were analysis.

*Anything with a price chart on it.* The whole premise here is that the price
chart is the layer everyone already has, and the interesting information is the
distance between it and the other two.

The output is a standalone SVG. No plotting library, no runtime, nothing to
install -- it opens in a browser, drops into a README, and prints.
"""

from __future__ import annotations

from tradesights.core.model import QUADRANT_SHORT, Quadrant

#: Porchlight. See Clanker-Labs/branding · brand/palette.md.
BG = "#101211"
LINE = "#272b28"
HEADING = "#e9ebe7"
BODY = "#a9aea8"
MUTED = "#7e847e"
FAINT = "#636963"
ACCENT = "#e79a4b"

#: Status is a separate axis from accent and is never decorative. Here it is
#: doing real work: the two quadrants where price and positioning DISAGREE are
#: the subject of the tool, and they are the only ones that get a colour.
QUADRANT_COLOUR = {
    Quadrant.CONTRARIAN_BID: "#6fbf8b",   # price down, money bullish
    Quadrant.HEDGED_RALLY: "#d4695f",     # price up, money bearish
    Quadrant.CHASE: "#7e847e",            # both up: agreement, not news
    Quadrant.FEAR: "#7e847e",             # both down: agreement, not news
    Quadrant.QUIET: "#4a504a",            # the middle, deliberately dim
}

W, H = 760, 620
PAD = {"t": 76, "r": 34, "b": 62, "l": 62}


def _escape(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def quadrant_svg(rows, title: str = "", label_top: int = 8) -> str:
    """Plot every scanned name. Label only the ones worth reading.

    `label_top` is a legibility budget, not a filter -- every name is plotted,
    but forty-three labels on one plot is a grey smear, so only the most
    divergent get named. The rest are still there as points, which is the whole
    point: they are the context that makes the outliers outliers.
    """
    if not rows:
        return _empty("nothing scanned")

    xs = [r.signals.price_z for r in rows]
    ys = [r.signals.money_z for r in rows]
    span = max(2.0, max(abs(v) for v in xs + ys) * 1.12)

    iw = W - PAD["l"] - PAD["r"]
    ih = H - PAD["t"] - PAD["b"]

    def X(v: float) -> float:
        return PAD["l"] + (v + span) / (2 * span) * iw

    def Y(v: float) -> float:
        return PAD["t"] + ih - (v + span) / (2 * span) * ih

    cx, cy = X(0), Y(0)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" '
        f'height="{H}" font-family="JetBrains Mono, ui-monospace, monospace" '
        f'role="img" aria-label="Price against options positioning for '
        f'{len(rows)} names, z-scored against each other">',
        f'<rect width="{W}" height="{H}" fill="{BG}"/>',
    ]

    if title:
        parts.append(f'<text x="{PAD["l"]}" y="34" fill="{HEADING}" font-size="17">'
                     f'{_escape(title)}</text>')
    parts.append(
        f'<text x="{PAD["l"]}" y="54" fill="{FAINT}" font-size="11">'
        f'every name scanned, z-scored against the others in the same run'
        f'</text>')

    # The two disagreement quadrants get a wash. The two agreement quadrants do
    # not, because a name whose price and options point the same way is the
    # normal case and shading it would give equal visual weight to the boring
    # half of the plot.
    parts.append(f'<rect x="{PAD["l"]}" y="{PAD["t"]}" width="{cx-PAD["l"]:.1f}" '
                 f'height="{cy-PAD["t"]:.1f}" fill="#6fbf8b" opacity="0.045"/>')
    parts.append(f'<rect x="{cx:.1f}" y="{cy:.1f}" width="{W-PAD["r"]-cx:.1f}" '
                 f'height="{PAD["t"]+ih-cy:.1f}" fill="#d4695f" opacity="0.045"/>')

    for v in (-2, -1, 1, 2):
        if abs(v) > span:
            continue
        parts.append(f'<line x1="{X(v):.1f}" y1="{PAD["t"]}" x2="{X(v):.1f}" '
                     f'y2="{PAD["t"]+ih}" stroke="{LINE}" stroke-width="1"/>')
        parts.append(f'<line x1="{PAD["l"]}" y1="{Y(v):.1f}" x2="{W-PAD["r"]}" '
                     f'y2="{Y(v):.1f}" stroke="{LINE}" stroke-width="1"/>')

    parts.append(f'<line x1="{PAD["l"]}" y1="{cy:.1f}" x2="{W-PAD["r"]}" y2="{cy:.1f}" '
                 f'stroke="{MUTED}" stroke-width="1"/>')
    parts.append(f'<line x1="{cx:.1f}" y1="{PAD["t"]}" x2="{cx:.1f}" y2="{PAD["t"]+ih}" '
                 f'stroke="{MUTED}" stroke-width="1"/>')

    corners = [
        (PAD["l"] + 10, PAD["t"] + 20, "start", "someone is paying for a bounce", "#6fbf8b"),
        (W - PAD["r"] - 10, PAD["t"] + 20, "end", "price and options agree", MUTED),
        (PAD["l"] + 10, PAD["t"] + ih - 12, "start", "price and options agree", MUTED),
        (W - PAD["r"] - 10, PAD["t"] + ih - 10, "end", "holders are nervous", "#d4695f"),
    ]
    for x, y, anchor, text, colour in corners:
        parts.append(f'<text x="{x:.0f}" y="{y:.0f}" fill="{colour}" font-size="10.5" '
                     f'text-anchor="{anchor}" opacity="0.9">{_escape(text)}</text>')

    ranked = sorted(rows, key=lambda r: -r.divergence)
    named = {r.symbol for r in ranked[:label_top]}

    for row in reversed(ranked):        # most divergent drawn last, on top
        x, y = X(row.signals.price_z), Y(row.signals.money_z)
        colour = QUADRANT_COLOUR[row.quadrant]
        lead = row.symbol in named
        r = 5.5 if lead else 3.2
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{colour}" '
                     f'opacity="{0.95 if lead else 0.5}"/>')
        if lead:
            anchor = "end" if x > W * 0.62 else "start"
            dx = -10 if anchor == "end" else 10
            parts.append(f'<text x="{x+dx:.1f}" y="{y+4:.1f}" fill="{HEADING}" '
                         f'font-size="12" text-anchor="{anchor}">'
                         f'{_escape(row.symbol)}</text>')

    parts.append(f'<text x="{W-PAD["r"]}" y="{PAD["t"]+ih+26:.0f}" fill="{MUTED}" '
                 f'font-size="11" text-anchor="end">← weaker   price vs the market   '
                 f'stronger →</text>')
    # Centred on the plot, not on its top edge: rotate(-90) turns a top-anchored
    # label into one that runs off the top of the frame, which is invisible in
    # the SVG source and obvious the moment anyone opens it.
    axis_mid = PAD["t"] + ih / 2
    parts.append(f'<text x="{PAD["l"]-24}" y="{axis_mid:.0f}" fill="{MUTED}" '
                 f'font-size="11" text-anchor="middle" '
                 f'transform="rotate(-90 {PAD["l"]-24} {axis_mid:.0f})">'
                 f'← bearish   options positioning   bullish →</text>')
    parts.append(f'<text x="{PAD["l"]}" y="{H-16}" fill="{FAINT}" font-size="10.5">'
                 f'{len(rows)} names · the middle is deliberately unnamed</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def _empty(message: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} 160" width="{W}" '
            f'height="160"><rect width="{W}" height="160" fill="{BG}"/>'
            f'<text x="24" y="86" fill="{MUTED}" font-size="14" '
            f'font-family="monospace">{_escape(message)}</text></svg>')


__all__ = ["QUADRANT_COLOUR", "QUADRANT_SHORT", "quadrant_svg"]

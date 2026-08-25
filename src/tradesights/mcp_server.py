"""tradesights as tools, so the agent can read the market and say something.

Modelled on the jinsen and chezmoi MCP servers next door: FastMCP over
streamable-HTTP, host network namespace, registered with LeClanker.

## What it can and cannot do

Read and report. There is no order-placing tool here and there will not be one.
The account this ecosystem runs has a broker connection with real money behind
it, in a different app, and the correct number of paths from a market-screening
MCP to that app is zero. A tool an agent can call is a tool an agent can call by
mistake.

`tradesights_digest` produces the morning message; LeClanker posts it through
its own Telegram connector. That separation is deliberate too: this server
formats, LeClanker delivers, and the thing that owns the bot token stays the
thing that owns the bot token.
"""

from __future__ import annotations

import os

from fastmcp import FastMCP

from tradesights.core.model import QUADRANT_PLAIN
from tradesights.core.scan import build_rows, interesting
from tradesights.ingest import macro
from tradesights.ingest.market import fetch_options, fetch_prices
from tradesights.ingest.talk import fetch_talk
from tradesights.universe import LIQUID, SECTORS

HOST = os.environ.get("MCP_HOST", "0.0.0.0")
PORT = int(os.environ.get("TRADESIGHTS_MCP_PORT", "8094"))

#: Where the digest belongs. Market talk in the market channel -- the general
#: chat is where everything else already lands, and a daily wall of tickers in
#: it is how a useful report becomes something people mute.
#:
#: Returned to the caller rather than posted from here. LeClanker owns the bot
#: token and every other outbound message; this server formats and it does not
#: deliver.
#
#: `or` rather than a get() default: compose passes
#: `TRADESIGHTS_TELEGRAM_CHAT: ${TRADESIGHTS_TELEGRAM_CHAT:-}`, which sets the
#: variable to the EMPTY STRING when it is absent from the env file. An empty
#: variable is a set variable, so the second argument to get() never runs and
#: the digest came back with nowhere to go.
TELEGRAM_CHAT = os.environ.get("TRADESIGHTS_TELEGRAM_CHAT") or "-1004498770577"

mcp = FastMCP(
    "tradesights",
    instructions=(
        "Market disagreement: where price, options positioning and talk stop "
        "agreeing. Use `tradesights_digest` for the morning summary Erwin asks "
        "for, `tradesights_rotation` for where money is moving by sector, and "
        "`tradesights_name` when he asks about one ticker. Everything here is a "
        "SCREENER — say where to look, never what to buy, and never imply a "
        "prediction. There is no tool here that can trade, by design."
    ),
)


def _scan(symbols: list[str], with_talk: bool = True):
    prices = fetch_prices(symbols)
    money = {s: m for s in symbols if (m := fetch_options(s))}
    talk = {}
    if with_talk:
        for s in list(money)[:15]:
            if (t := fetch_talk(s)):
                talk[s] = t
    return build_rows(prices, money, talk)


@mcp.tool
def tradesights_digest(limit: int = 5) -> dict:
    """The morning summary: regime, sector rotation, and the biggest disagreements.

    This is the one to call when asked for "the market this morning". It returns
    a ready-to-post `message` plus the structured rows behind it, so a reply can
    quote the message verbatim rather than paraphrasing numbers.
    """
    regime = macro.describe(macro.fetch_regime())
    sectors = _scan(list(SECTORS), with_talk=False)
    names = interesting(_scan(LIQUID), limit)

    moving = sorted(sectors, key=lambda r: r.rel_1m, reverse=True)
    lines = [f"TRADESIGHTS — {regime}", ""]

    if moving:
        into = ", ".join(SECTORS.get(r.symbol, r.symbol) for r in moving[:2])
        out = ", ".join(SECTORS.get(r.symbol, r.symbol) for r in moving[-2:])
        lines += [f"ROTATION  into {into} · out of {out}", ""]

    if names:
        lines.append("WHERE THE LAYERS DISAGREE")
        for i, r in enumerate(names, 1):
            lines.append(f"{i}. {r.headline}")
            lines += [f"   · {n}" for n in r.notes]
    else:
        # Said plainly rather than padded. A list that is always five long
        # teaches the reader that the length means nothing.
        lines.append("Nothing is stretched today — price and positioning agree across "
                     "the board. That is a finding, not a failure.")

    lines += ["", "A screener. Every name is a question, not a call."]

    return {
        "ok": True,
        "regime": regime,
        "message": "\n".join(lines),
        "post_to": TELEGRAM_CHAT,
        "names": [
            {"symbol": r.symbol, "quadrant": r.quadrant.value,
             "reading": QUADRANT_PLAIN[r.quadrant], "rel_1m": round(r.rel_1m, 4),
             "divergence": round(r.divergence, 2), "notes": r.notes}
            for r in names
        ],
    }


@mcp.tool
def tradesights_rotation() -> dict:
    """Sector performance against SPY, with what the options market thinks of it."""
    rows = _scan(list(SECTORS), with_talk=False)
    if not rows:
        return {"ok": False, "error": "no sector data — the price source may be unavailable"}
    return {
        "ok": True,
        "sectors": [
            {"sector": SECTORS.get(r.symbol, r.symbol), "symbol": r.symbol,
             "vs_spy": round(r.rel_1m, 4), "positioning": round(r.signals.money_z, 2),
             "reading": QUADRANT_PLAIN[r.quadrant]}
            for r in sorted(rows, key=lambda r: r.rel_1m, reverse=True)
        ],
    }


@mcp.tool
def tradesights_name(symbol: str) -> dict:
    """Price, options positioning and talk for one ticker.

    Reports each layer as measured or explicitly missing. A layer that could not
    be read is never returned as a neutral value — a name nobody discussed and a
    name nobody checked are different facts.
    """
    symbol = symbol.upper().strip()
    prices = fetch_prices([symbol])
    if symbol not in prices:
        return {"ok": False, "error": f"no price history for {symbol}"}

    p = prices[symbol]
    m = fetch_options(symbol)
    t = fetch_talk(symbol)

    return {
        "ok": True,
        "symbol": symbol,
        "price": {"return_1m": round(p.ret_1m, 4), "vs_spy": round(p.rel_1m, 4)},
        "options": None if m is None else {
            "skew": round(m.skew, 4),
            "call_put_volume": round(m.call_put_volume, 2),
            "volume_reliable": m.volume_reliable,
            "split": m.positioning_conflict > 1.5,
        },
        "talk": None if t is None else {
            "sentiment": round(t.sentiment, 3), "mentions": t.mentions, "source": t.source,
        },
        "caveat": "A screener. This says where to look, not what to do.",
    }


if __name__ == "__main__":
    print(f"tradesights MCP: http (streamable) on {HOST}:{PORT}/mcp", flush=True)
    mcp.run(transport="http", host=HOST, port=PORT)

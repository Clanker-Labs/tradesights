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

#: Leveraged funds and the index each one actually tracks. Kept in step with
#: dashboard/server.py: both read the same core, and a fund in one list and not
#: the other is a tool that answers for the dashboard and 404s for the agent.
LEVERAGED_UNDERLYING = {"TQQQ": "QQQ", "UPRO": "SPY", "SOXL": "SOXX", "QLD": "QQQ"}

mcp = FastMCP(
    "tradesights",
    instructions=(
        "Market disagreement: where price, options positioning and talk stop "
        "agreeing. Use `tradesights_digest` for the morning summary Erwin asks "
        "for, `tradesights_rotation` for where money is moving by sector, and "
        "`tradesights_name` when he asks about one ticker.\n\n"
        "The archive tools answer questions a single scan cannot. "
        "`tradesights_track` says whether a name has been stretched for a "
        "fortnight or arrived there this morning — check it before describing "
        "any name as newly interesting. `tradesights_resolve` reports what "
        "happened after past signals, and will usually answer that there is not "
        "enough history yet; report that plainly rather than hunting for a "
        "number. `tradesights_record` writes today's scan down and is the only "
        "tool here that changes anything.\n\n"
        "Everything here is a SCREENER — say where to look, never what to buy, "
        "and never imply a prediction. There is no tool here that can trade, by "
        "design. When quoting the archive, quote its caveats too: they are not "
        "hedging, they are the finding."
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


@mcp.tool
def tradesights_track(symbol: str) -> dict:
    """One name's readings across every stored session.

    The question a single scan structurally cannot answer: has this been
    stretched for a fortnight, or did it arrive there this morning? A name at
    the top of today's list is a different proposition depending on the answer,
    and the ranked list has no way to say which.

    Returns an empty history rather than an error when nothing is stored — an
    archive that has not been running is not a failure, it is a fact about how
    long the tool has been recording.
    """
    from tradesights import store

    symbol = symbol.upper().strip()
    rows = store.history(symbol)
    if not rows:
        return {
            "ok": True, "symbol": symbol, "sessions": 0, "history": [],
            "note": ("nothing recorded for this name yet. The archive only grows "
                     "forward — it cannot be backfilled, because option chains "
                     "are not retrievable after the fact."),
        }

    latest = rows[-1]
    streak = 0
    for row in reversed(rows):
        if row.quadrant != latest.quadrant:
            break
        streak += 1

    return {
        "ok": True,
        "symbol": symbol,
        "sessions": len(rows),
        "latest": {
            "session": latest.session, "quadrant": latest.quadrant,
            "divergence": round(latest.divergence, 3),
            "price_z": round(latest.price_z, 3),
            "money_z": round(latest.money_z, 3),
        },
        "streak_sessions": streak,
        "history": [
            {"session": r.session, "quadrant": r.quadrant,
             "divergence": round(r.divergence, 3)}
            for r in rows
        ],
        "caveat": ("A long streak means the disagreement has persisted, not that "
                   "it is about to resolve."),
    }


@mcp.tool
def tradesights_resolve(horizon_days: int = 5) -> dict:
    """What happened after past signals, grouped by quadrant.

    Read the `edge` figure, not `mean_return`. Edge is a quadrant's average
    forward return minus everything else's over the same sessions: in a rising
    market every quadrant looks predictive, and subtracting the universe is the
    only way to tell a signal from a tide.

    `reasons_not_to_believe` is the important field and is usually non-empty.
    For the first several months the honest answer is that there is not enough
    archive, and this returns that rather than a confident percentage.
    """
    from tradesights import store

    horizon_days = max(1, min(int(horizon_days), 60))
    outcomes = store.resolve(horizon_days)
    scores, reasons = store.score_quadrants(outcomes)

    if not scores:
        return {
            "ok": True, "horizon_days": horizon_days, "resolved": 0,
            "scores": [], "reasons_not_to_believe": reasons,
            "note": ("nothing has resolved yet. Say so — do not go looking for a "
                     "number somewhere else."),
        }

    return {
        "ok": True,
        "horizon_days": horizon_days,
        "resolved": len(outcomes),
        "sessions": len({o.session for o in outcomes}),
        "scores": [
            {"quadrant": s.quadrant, "n": s.n,
             "mean_return": round(s.mean_return, 5),
             "median_return": round(s.median_return, 5),
             "hit_rate": round(s.hit_rate, 3),
             "universe_baseline": round(s.baseline, 5),
             "edge": round(s.edge, 5)}
            for s in scores
        ],
        "reasons_not_to_believe": reasons,
        "caveat": ("A forward return after a signal is not a trade. There is no "
                   "entry rule, no stop, no size and no cost here, and the "
                   "difference between a drift and a profit is every part of "
                   "trading that is hard."),
    }


@mcp.tool
def tradesights_archive() -> dict:
    """What is in the archive, and whether it is enough to conclude anything."""
    from tradesights import store

    rows = store.sessions(limit=9999)
    enough = len(rows) >= 30
    return {
        "ok": True,
        "sessions": len(rows),
        "first": rows[-1]["session"] if rows else None,
        "latest": rows[0]["session"] if rows else None,
        "enough_to_conclude": enough,
        "note": (
            "The archive is large enough that resolution figures are worth "
            "reading, with their caveats." if enough else
            f"{len(rows)} sessions. Thirty is six trading weeks, and every name "
            "on the same day shares a market, so the effective sample grows far "
            "more slowly than the row count suggests."
        ),
    }


@mcp.tool
def tradesights_record() -> dict:
    """Write today's scan into the archive. The only tool here that changes state.

    Slow — it pulls the full option-chain universe, the same as a scan. Call it
    once a day at most; a session recorded twice replaces itself rather than
    double-counting, but the minutes are still spent.

    Normally a timer does this (see `deploy/` in the repo). Call it by hand when
    the timer has not run and the day would otherwise be lost: option chains are
    not retrievable after the fact, so a missed session is missed permanently.
    """
    from tradesights import store

    rows = _scan(LIQUID, with_talk=False)
    if not rows:
        return {"ok": False,
                "error": "no name had both price and options — nothing recorded"}

    prices = fetch_prices([r.symbol for r in rows])
    snapshot_id = store.save(rows, prices=prices,
                             regime=macro.describe(macro.fetch_regime()))
    stored = store.sessions(limit=9999)
    return {
        "ok": True, "snapshot": snapshot_id, "names": len(rows),
        "sessions_stored": len(stored),
        "note": ("Recorded. The archive only grows forward and says nothing "
                 "useful for months."),
    }


@mcp.tool
def tradesights_trend(symbol: str = "TQQQ") -> dict:
    """The 200-day rule for a leveraged ETF, with what would make it wrong.

    Use this for "what is TQQQ doing", "should I be in TQQQ", or the daily
    leveraged check. Known funds: TQQQ, UPRO, SOXL, QLD.

    Read the whole thing before summarising, and carry `notes` through — they
    are the conditions under which the rule fails, and a stance quoted without
    them is the half that gets somebody hurt. Say "the rule says", not "you
    should": this is a mechanical readout of two moving averages, there is no
    order execution anywhere in this repo, and the strategy is well known to
    whipsaw near the line.

    Every signal is computed on the UNDERLYING index, never on the leveraged
    fund itself — a 3x fund's own moving average moves with volatility decay as
    well as with the market, so a crossing of it can mean nothing happened.
    """
    from tradesights.core import trend as trendmod
    from tradesights.ingest.market import fetch_history

    sym = (symbol or "TQQQ").upper().strip()
    under = LEVERAGED_UNDERLYING.get(sym)
    if under is None:
        return {"error": f"{sym} is not known here. Try: "
                         + ", ".join(sorted(LEVERAGED_UNDERLYING))}
    series = fetch_history([sym, under])
    reading = trendmod.evaluate(
        symbol=sym, underlying=under,
        closes=(series.get(sym) or {}).get("closes") or [],
        under_closes=(series.get(under) or {}).get("closes") or [],
        dates=(series.get(under) or {}).get("dates") or [],
    )
    out = reading.as_dict()
    # The chart series is for the browser. Sending 260 points into a model's
    # context costs tokens and tells it nothing the numbers do not.
    out.pop("history", None)
    return out



if __name__ == "__main__":
    print(f"tradesights MCP: http (streamable) on {HOST}:{PORT}/mcp", flush=True)
    mcp.run(transport="http", host=HOST, port=PORT)

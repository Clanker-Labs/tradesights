"""The research dashboard. Reads the archive; cannot place an order.

There is no order execution anywhere in this repo and no path from it to a
broker, deliberately and permanently. Nothing here changes that: every route is
a read, and the only write is the one that records a scan.

**It reads the archive, not the market.** A live scan pulls 43 option chains and
takes minutes, which is not a thing to do inside an HTTP request — a page that
hangs for three minutes is a page nobody uses, and one that times out halfway
leaves a half-scanned universe that z-scores against itself. So the dashboard
serves stored snapshots, and `tradesights snapshot` (from a cron, or by hand)
puts them there. The consequence is honest and visible: an empty archive shows
as an empty archive with the command to fix it, rather than as a broken page.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from tradesights import store
from tradesights.core import analytics, backtest
from tradesights.core.model import QUADRANT_PLAIN, QUADRANT_SHORT, Quadrant

logger = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"

app = FastAPI(title="tradesights", docs_url="/api/docs",
              openapi_url="/api/openapi.json")

#: Colour is a separate axis from accent and is never decorative here. The two
#: quadrants where price and positioning DISAGREE are the subject of the tool;
#: the two where they agree are the normal case and stay grey.
QUADRANT_META = {
    Quadrant.CONTRARIAN_BID.value: {"colour": "#4ADE80", "disagreement": True},
    Quadrant.HEDGED_RALLY.value: {"colour": "#E5484D", "disagreement": True},
    Quadrant.CHASE.value: {"colour": "#7C8896", "disagreement": False},
    Quadrant.FEAR.value: {"colour": "#7C8896", "disagreement": False},
    Quadrant.QUIET.value: {"colour": "#4a504a", "disagreement": False},
}


def _observation(o: store.Observation) -> dict:
    meta = QUADRANT_META.get(o.quadrant, {})
    quadrant = Quadrant(o.quadrant)
    return {
        "symbol": o.symbol, "session": o.session,
        "price_z": round(o.price_z, 4), "money_z": round(o.money_z, 4),
        "talk_z": None if o.talk_z is None else round(o.talk_z, 4),
        "rel_1m": round(o.rel_1m, 5), "quadrant": o.quadrant,
        "quadrant_short": QUADRANT_SHORT[quadrant],
        "quadrant_plain": QUADRANT_PLAIN[quadrant],
        "divergence": round(o.divergence, 4),
        "positioning_conflict": round(o.positioning_conflict, 4),
        "price": round(o.price, 4),
        "colour": meta.get("colour", "#7C8896"),
        "disagreement": meta.get("disagreement", False),
    }


@app.get("/api/health")
def health() -> dict:
    rows = store.sessions(limit=1)
    return {"ok": True, "app": "tradesights", "can_trade": False,
            "sessions": len(store.sessions(limit=9999)),
            "latest": rows[0]["session"] if rows else None}


@app.get("/api/sessions")
def api_sessions(limit: int = Query(400, ge=1, le=2000)) -> dict:
    return {"sessions": store.sessions(limit=limit)}


@app.get("/api/snapshot")
def api_snapshot(session: str = Query("", description="YYYY-MM-DD; latest if blank")
                 ) -> dict:
    rows = store.snapshot(session or None)
    if not rows:
        raise HTTPException(404,
                            "no snapshot stored — run `tradesights snapshot` first")
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.quadrant] = counts.get(row.quadrant, 0) + 1
    return {
        "session": rows[0].session,
        "n": len(rows),
        "counts": counts,
        "has_talk": any(r.talk_z is not None for r in rows),
        "rows": [_observation(r) for r in rows],
    }


@app.get("/api/name/{symbol}")
def api_name(symbol: str) -> dict:
    """One name, and the thing a single scan structurally cannot tell you.

    A name at the top of today's list is a different proposition depending on
    whether it has been stretched for two weeks or arrived there this morning,
    and the ranked list has no way to say which.
    """
    rows = store.history(symbol)
    if not rows:
        raise HTTPException(404, f"no stored readings for {symbol.upper()}")
    latest = rows[-1]
    quadrants = [r.quadrant for r in rows]
    streak = 0
    for q in reversed(quadrants):
        if q != latest.quadrant:
            break
        streak += 1
    return {
        "symbol": latest.symbol,
        "latest": _observation(latest),
        "sessions": len(rows),
        "streak": streak,
        "history": [_observation(r) for r in rows],
    }


@app.get("/api/backtest")
def api_backtest(horizon: int = Query(5, ge=1, le=60)) -> dict:
    """What acting on the signals would have meant.

    Separate endpoint from /api/resolve rather than more fields on it, because
    they answer different questions and conflating them is how a "did the price
    move" number gets read as a P&L. resolve is direction-blind by design; this
    takes a side, and the side is an interpretation laid on the tool rather than
    something the tool claims. See core/backtest.DIRECTION.
    """
    outcomes = store.resolve(horizon)
    board = backtest.run(outcomes, horizon_days=horizon)
    corr = backtest.correlate_divergence(board)

    per_symbol: dict[str, dict] = {}
    for t in board.trades:
        d = per_symbol.setdefault(t.symbol, {"symbol": t.symbol, "n": 0, "wins": 0, "total": 0.0})
        d["n"] += 1
        d["wins"] += 1 if t.won else 0
        d["total"] += t.pnl_return
    ranked = sorted(per_symbol.values(), key=lambda d: d["total"], reverse=True)

    return {
        "horizon_days": horizon,
        "resolved": len(outcomes),
        "traded": board.n,
        "stood_aside": board.stood_aside,
        "wins": board.wins,
        "losses": board.losses,
        "hit_rate": board.hit_rate,
        "mean_return": board.mean_return,
        "total_return": board.total_return,
        # Always travels with the headline. Every strategy looks brilliant in a
        # month when everything went up.
        "baseline_return": board.baseline_return,
        "edge": board.edge,
        "best": _trade(board.best),
        "worst": _trade(board.worst),
        "curve": backtest.equity_curve(board),
        "by_symbol": ranked,
        "trades": [_trade(t) for t in board.trades],
        "correlation": {
            "n": corr.n, "r": corr.r, "rho": corr.rho,
            "hit_trend": corr.hit_trend, "buckets": corr.buckets,
            "note": corr.note, "reportable": corr.reportable,
        },
        "direction": {k: v for k, v in backtest.DIRECTION.items()},
    }


@app.get("/api/analytics")
def api_analytics(horizon: int = Query(5, ge=1, le=60),
                  shuffles: int = Query(200, ge=50, le=2000)) -> dict:
    """Why the winners won — and whether that reason survives contact with noise.

    The filter search is the dangerous half of this endpoint and the permutation
    test is why it is safe to expose. Shuffling which trades won destroys any
    real relationship while preserving the sample size, the factor distributions
    and the search itself, so whatever the search finds on shuffled data is
    exactly what it can manufacture from nothing. The p-value that falls out is
    served alongside the rule, never behind a flag, because a rule without it is
    the single most dangerous number this tool could publish.
    """
    board = backtest.run(store.resolve(horizon), horizon_days=horizon)
    risk = analytics.risk_metrics(board)
    factors = analytics.factor_reports(board)
    study = analytics.filter_study(board, shuffles=shuffles)

    return {
        "horizon_days": horizon,
        "risk": {
            "n": risk.n, "avg_win": risk.avg_win, "avg_loss": risk.avg_loss,
            "payoff_ratio": risk.payoff_ratio, "profit_factor": risk.profit_factor,
            "expectancy": risk.expectancy,
            "return_per_unit_risk": risk.return_per_unit_risk,
            "max_drawdown": risk.max_drawdown,
            "max_losing_streak": risk.max_losing_streak,
            "top_trade_share": risk.top_trade_share,
        },
        "factors": [
            {"name": f.name, "n": f.n, "ic": f.ic,
             "winner_mean": f.winner_mean, "loser_mean": f.loser_mean,
             "separation": f.separation, "quartiles": f.quartiles, "note": f.note}
            for f in factors
        ],
        "filters": {
            "baseline_mean": study.baseline_mean, "baseline_n": study.baseline_n,
            "tried": study.tried, "p_value": study.p_value,
            "verdict": study.verdict,
            "best": (None if study.best is None else {
                "factor": study.best.factor, "op": study.best.op,
                "threshold": study.best.threshold, "n": study.best.n,
                "hit_rate": study.best.hit_rate, "mean_return": study.best.mean_return,
                "lift": study.best.lift}),
            "rules": [{"factor": r.factor, "op": r.op, "threshold": r.threshold,
                       "n": r.n, "hit_rate": r.hit_rate,
                       "mean_return": r.mean_return, "lift": r.lift}
                      for r in study.rules],
            "null_best": study.null_best,
        },
    }


@app.get("/api/backtest/{symbol}")
def api_backtest_symbol(symbol: str, horizon: int = Query(5, ge=1, le=60)) -> dict:
    """One name's price line, with every signal marked on it.

    The series and the marks come from the same archive rows, so a mark always
    lands ON the line. Deriving the mark's y-value from a date lookup against a
    separately fetched series is how a chart ends up with alerts floating beside
    the price they were supposedly triggered at.
    """
    rows = store.history(symbol.upper())
    if not rows:
        raise HTTPException(status_code=404, detail=f"no history for {symbol.upper()}")
    board = backtest.run(store.resolve(horizon), horizon_days=horizon)
    return {
        "symbol": symbol.upper(),
        "horizon_days": horizon,
        "series": [{"session": r.session, "price": r.price,
                    "quadrant": r.quadrant, "divergence": r.divergence}
                   for r in rows if r.price > 0],
        "marks": backtest.marks_for(symbol.upper(), board),
    }


def _trade(t) -> dict | None:
    if t is None:
        return None
    return {
        "symbol": t.symbol, "session": t.session, "quadrant": t.quadrant,
        "direction": t.direction, "divergence": t.divergence,
        "entry_price": t.entry_price, "exit_price": t.exit_price,
        "price_return": t.price_return, "pnl_return": t.pnl_return, "won": t.won,
    }


@app.get("/api/resolve")
def api_resolve(horizon: int = Query(5, ge=1, le=60)) -> dict:
    """Did the disagreements go anywhere.

    The only question that makes an archive worth keeping, and the one the tool
    could not answer at all before there was one.
    """
    outcomes = store.resolve(horizon)
    scores, reasons = store.score_quadrants(outcomes)
    return {
        "horizon_days": horizon,
        "resolved": len(outcomes),
        "sessions": len({o.session for o in outcomes}),
        "reasons": reasons,
        "scores": [
            {"quadrant": s.quadrant,
             "short": QUADRANT_SHORT[Quadrant(s.quadrant)],
             "colour": QUADRANT_META.get(s.quadrant, {}).get("colour", "#7C8896"),
             "n": s.n, "mean_return": s.mean_return,
             "median_return": s.median_return, "hit_rate": s.hit_rate,
             "baseline": s.baseline, "edge": s.edge}
            for s in scores
        ],
        "outcomes": [
            {"symbol": o.symbol, "session": o.session, "quadrant": o.quadrant,
             "divergence": round(o.divergence, 3),
             "forward_return": round(o.forward_return, 5)}
            for o in sorted(outcomes, key=lambda o: o.session, reverse=True)[:400]
        ],
    }


@app.get("/api/quadrants")
def api_quadrants() -> dict:
    """The four situations, so the client does not hard-code them."""
    return {
        "quadrants": [
            {"name": q.value, "short": QUADRANT_SHORT[q], "plain": QUADRANT_PLAIN[q],
             **QUADRANT_META.get(q.value, {})}
            for q in Quadrant
        ]
    }


#: The leveraged funds this tab knows how to reason about, and the index each
#: one actually tracks. The mapping is the whole point: every signal is computed
#: on the UNDERLYING, because a 3x fund's own moving average moves with decay as
#: well as with the market. See core/trend.py.
LEVERAGED = {
    "TQQQ": "QQQ",
    "UPRO": "SPY",
    "SOXL": "SOXX",
    "QLD": "QQQ",
}

#: yfinance is scraped and rate-limits. One reading per symbol per 15 minutes is
#: far more often than a daily rule can change and far less often than a browser
#: tab left open would ask.
_TREND_CACHE: dict[str, tuple[float, dict]] = {}
_TREND_TTL = 900.0


@app.get("/api/trend/{symbol}")
def api_trend(symbol: str) -> dict:
    """Today's reading of the 200-day rule for one leveraged fund."""
    import time as _time

    from tradesights.core import trend as trendmod
    from tradesights.ingest.market import fetch_history

    sym = symbol.upper().strip()
    under = LEVERAGED.get(sym)
    if under is None:
        raise HTTPException(
            status_code=404,
            detail=f"{sym} is not one of {', '.join(sorted(LEVERAGED))}. "
                   "Add it to LEVERAGED with the index it tracks.",
        )

    hit = _TREND_CACHE.get(sym)
    if hit and (_time.time() - hit[0]) < _TREND_TTL:
        return hit[1]

    series = fetch_history([sym, under])
    lev = series.get(sym) or {}
    idx = series.get(under) or {}
    reading = trendmod.evaluate(
        symbol=sym,
        underlying=under,
        closes=lev.get("closes") or [],
        under_closes=idx.get("closes") or [],
        dates=idx.get("dates") or [],
    )
    payload = reading.as_dict()
    payload["universe"] = sorted(LEVERAGED)
    # Only cache a reading that actually has data — caching a failed scrape for
    # fifteen minutes turns a transient rate-limit into a quarter hour of "no
    # price data came back".
    if payload.get("sma_slow") is not None:
        _TREND_CACHE[sym] = (_time.time(), payload)
    return payload


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


if STATIC.exists():
    app.mount("/static", StaticFiles(directory=STATIC), name="static")


def serve(host: str = "127.0.0.1", port: int = 8095) -> None:
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="info")


__all__ = ["QUADRANT_META", "app", "serve"]

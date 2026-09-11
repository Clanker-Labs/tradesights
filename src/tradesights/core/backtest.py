"""What acting on the tool would actually have meant.

``store.resolve`` already answers "did the price move after we flagged this".
That is not the same question as "would we have made money", and the gap between
them is the whole of this module.

Three things have to be added to a forward return before it means anything.

**A direction.** A forward return of +3% is a win if the signal said buy and a
loss if it said sell. ``resolve`` deliberately does not take a side -- model.py
is explicit that every name the scanner surfaces "is a question rather than an
answer" -- so the mapping from quadrant to trade is an INTERPRETATION laid on
top of the tool, not something the tool claims. It lives in one dict below,
where it can be read, argued with and changed, rather than being spread through
the arithmetic where it would quietly become fact.

**A baseline.** Every strategy looks brilliant in a month when everything went
up. The only honest comparison is against having bought the same names on the
same days with no signal at all, so that is computed alongside and every headline
number carries it.

**A sample size.** This archive holds one snapshot per trading session and began
in August. Twelve sessions is not a track record, and a win rate quoted from
eleven resolved trades is a number with the shape of evidence and none of the
substance. Every result here reports ``n``, and the correlation refuses to
report at all below a floor rather than printing a coefficient nobody should
act on.
"""

from __future__ import annotations

import datetime as dt
import math
import statistics
from dataclasses import dataclass, field

from tradesights.core.model import Quadrant

#: How a quadrant becomes a position.
#:
#: +1 long, -1 short, 0 stand aside. Read these as "what a person acting on the
#: sentence in QUADRANT_PLAIN would do", because that is all they are:
#:
#:   contrarian_bid  someone is paying for a bounce            -> buy the bounce
#:   fear            put buyers agree with the drop            -> sell/avoid
#:   chase           confirmed and crowded                     -> stand aside
#:   hedged_rally    up, but holders are buying protection     -> sell/avoid
#:   quiet           nothing is stretched                      -> stand aside
#:
#: CHASE is 0 rather than +1 on purpose. "The trend is confirmed, and crowded"
#: is the one quadrant whose own description argues both ways, and taking a side
#: there would be inventing a claim the tool does not make. A backtest that
#: quietly assigns a direction to an ambiguous signal is measuring the author's
#: opinion, not the tool.
DIRECTION: dict[str, int] = {
    Quadrant.CONTRARIAN_BID: +1,
    Quadrant.FEAR: -1,
    Quadrant.CHASE: 0,
    Quadrant.HEDGED_RALLY: -1,
    Quadrant.QUIET: 0,
}


@dataclass(frozen=True)
class Trade:
    """One signal, acted on, and what it cost or paid."""

    symbol: str
    session: str
    quadrant: str
    direction: int
    #: How far out of line the name was when flagged. The independent variable
    #: for the question "does a bigger signal mean a bigger move".
    divergence: float
    horizon_days: int
    entry_price: float
    exit_price: float
    #: Raw price change, direction-blind. What `resolve` reports.
    price_return: float
    #: Price change signed by the position. THIS is the win or the loss.
    pnl_return: float
    #: Everything observable when the signal fired, carried through so the
    #: question "what separated the winners from the losers" can be asked of
    #: more than the one number that happened to do the ranking.
    factors: dict = field(default_factory=dict)

    @property
    def won(self) -> bool:
        return self.pnl_return > 0


@dataclass
class Scoreboard:
    """The record, with everything needed to distrust it."""

    trades: list[Trade] = field(default_factory=list)
    #: Signals that were flagged but carried no position (chase, quiet).
    stood_aside: int = 0
    #: Observations too recent to have an answer yet.
    unresolved: int = 0
    horizon_days: int = 5

    @property
    def n(self) -> int:
        return len(self.trades)

    @property
    def wins(self) -> int:
        return sum(1 for t in self.trades if t.won)

    @property
    def losses(self) -> int:
        return self.n - self.wins

    @property
    def hit_rate(self) -> float | None:
        return self.wins / self.n if self.n else None

    @property
    def mean_return(self) -> float | None:
        return statistics.fmean(t.pnl_return for t in self.trades) if self.n else None

    @property
    def total_return(self) -> float | None:
        """Sum of signed returns: one unit staked per signal, not compounded.

        Equal-weight and additive on purpose. Compounding would make the answer
        depend on the order the trades happened to arrive in, which is a
        property of the archive rather than of the strategy.
        """
        return sum(t.pnl_return for t in self.trades) if self.n else None

    @property
    def best(self) -> Trade | None:
        return max(self.trades, key=lambda t: t.pnl_return, default=None)

    @property
    def worst(self) -> Trade | None:
        return min(self.trades, key=lambda t: t.pnl_return, default=None)

    @property
    def baseline_return(self) -> float | None:
        """Buying every one of the same names on the same days, signal ignored.

        The number that stops a rising market being read as skill. If this is
        close to `mean_return`, the tool moved nothing -- it just happened to be
        pointing at a market that went up.
        """
        return statistics.fmean(t.price_return for t in self.trades) if self.n else None

    @property
    def edge(self) -> float | None:
        m, b = self.mean_return, self.baseline_return
        return None if m is None or b is None else m - b


#: Below this many trades, a correlation coefficient is noise with a decimal
#: point. Pearson's r over eight pairs will happily read 0.6 on random data.
MIN_CORRELATION_N = 25


@dataclass(frozen=True)
class Correlation:
    """Does a bigger signal mean a better result?

    Two coefficients, because they answer different questions and the first one
    alone was actively misleading.

    `r` (Pearson) asks whether a bigger signal means a bigger RETURN. It is
    dominated by outliers: one -25% trade drags it toward zero no matter how
    reliably the rest behaved, so a tool that is consistently right about
    DIRECTION and occasionally wrong about size reads as noise.

    `rho` (Spearman) ranks both series first, so a single catastrophic trade is
    just the worst rank rather than a lever. When rho is clearly positive and r
    is flat, the honest reading is "the ranking works, the sizing does not" —
    which is a real and useful finding that the Pearson number alone hides.

    `hit_trend` is the plainest version of the same question: does the hit rate
    climb as the signal gets more extreme.
    """

    n: int
    r: float | None
    rho: float | None
    #: Trades grouped by how extreme the signal was, weakest bucket first.
    buckets: list[dict]
    #: Hit rate of the strongest bucket minus the weakest. Positive means the
    #: ranking sorted winners from losers.
    hit_trend: float | None
    note: str

    @property
    def reportable(self) -> bool:
        return self.r is not None or self.rho is not None


def _rank(values: list[float]) -> list[float]:
    """Average ranks, ties shared. Ties matter: divergence has repeats."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        shared = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = shared
        i = j + 1
    return ranks


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    sx, sy = statistics.pstdev(xs), statistics.pstdev(ys)
    if sx == 0 or sy == 0:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n / (sx * sy)


def correlate_divergence(board: Scoreboard, buckets: int = 4) -> Correlation:
    """Does being further out of line pay, and in what sense.

    Reports rank correlation alongside the linear one because the linear one on
    its own said "no relationship" while the bucket table underneath it showed
    hit rate climbing 43% -> 47% -> 60% -> 67%. Both cannot be true, and the
    bucket table was right: Pearson was being flattened by a single -25% trade.
    A page that states two contradictory things is worse than one that states
    the unflattering one.

    Refuses below MIN_CORRELATION_N rather than returning numbers, because the
    numbers would be believed.
    """
    trades = board.trades
    xs = [t.divergence for t in trades]
    ys = [t.pnl_return for t in trades]
    n = len(xs)

    grouped: list[dict] = []
    hit_trend: float | None = None
    if n:
        order = sorted(trades, key=lambda t: t.divergence)
        size = max(1, n // max(1, buckets))
        edges = [i * size for i in range(buckets)] + [n]
        for a, b in zip(edges, edges[1:]):
            # The remainder joins the LAST bucket rather than forming its own.
            # 122 trades in 4 buckets of 30 left a bucket of 2 reading "+6.14%,
            # 100% hit" — a headline number resting on two trades.
            chunk = order[a:b]
            if not chunk:
                continue
            grouped.append({
                "from": round(chunk[0].divergence, 3),
                "to": round(chunk[-1].divergence, 3),
                "n": len(chunk),
                "mean_return": statistics.fmean(c.pnl_return for c in chunk),
                "hit_rate": sum(1 for c in chunk if c.won) / len(chunk),
            })
        if len(grouped) >= 2:
            hit_trend = grouped[-1]["hit_rate"] - grouped[0]["hit_rate"]

    if n < MIN_CORRELATION_N:
        return Correlation(
            n=n, r=None, rho=None, buckets=grouped, hit_trend=hit_trend,
            note=(f"{n} resolved trade(s) — too few to state a correlation. "
                  f"Below {MIN_CORRELATION_N} the coefficient moves more with "
                  f"which trades happened to resolve than with anything real."))

    r = _pearson(xs, ys)
    rho = _pearson(_rank(xs), _rank(ys))

    strong = lambda v: v is not None and abs(v) > 0.2
    if strong(rho) and rho > 0 and not (strong(r) and r > 0):
        note = ("the RANKING works but the sizing does not: more divergent names "
                "won more often, yet how much they won is not predictable from "
                "the score. Treat it as a sort order, not a position size.")
    elif strong(rho) and rho > 0:
        note = "more divergent names both won more often and won more."
    elif strong(rho) and rho < 0:
        note = "more divergent names did WORSE — the ranking is working against you."
    else:
        note = ("no relationship worth acting on: the score says where to look, "
                "not how much to size.")
    if hit_trend is not None and abs(hit_trend) >= 0.1:
        note += (f" Hit rate {'rises' if hit_trend > 0 else 'falls'} "
                 f"{abs(hit_trend) * 100:.0f} points from the weakest bucket to "
                 f"the strongest.")

    return Correlation(n=n, r=r, rho=rho, buckets=grouped,
                       hit_trend=hit_trend, note=note)


def run(outcomes, *, horizon_days: int = 5,
        direction: dict[str, int] | None = None) -> Scoreboard:
    """Turn resolved observations into a record of acting on them.

    `outcomes` is whatever `store.resolve` returned. Nothing is re-downloaded
    and nothing is re-priced: this reads the same archive rows, signs them, and
    counts.
    """
    table = direction or DIRECTION
    board = Scoreboard(horizon_days=horizon_days)
    for o in outcomes:
        d = table.get(o.quadrant, 0)
        if d == 0:
            board.stood_aside += 1
            continue
        board.trades.append(Trade(
            symbol=o.symbol, session=o.session, quadrant=o.quadrant, direction=d,
            divergence=o.divergence, horizon_days=horizon_days,
            entry_price=o.entry_price, exit_price=o.later_price,
            price_return=o.forward_return,
            pnl_return=o.forward_return * d,
            factors=dict(getattr(o, "factors", None) or {})))
    board.trades.sort(key=lambda t: (t.session, t.symbol))
    return board


def equity_curve(board: Scoreboard) -> list[dict]:
    """Cumulative signed return, in the order the signals were given.

    Additive rather than compounded, for the reason in `total_return`. The point
    of the curve is to show WHERE the record was made -- one good week carrying
    everything is a different tool from a steady drip, and a single number hides
    which one you have.
    """
    out: list[dict] = []
    running = 0.0
    for t in board.trades:
        running += t.pnl_return
        out.append({"session": t.session, "symbol": t.symbol,
                    "pnl_return": t.pnl_return, "cumulative": running})
    return out


def marks_for(symbol: str, board: Scoreboard) -> list[dict]:
    """Every signal on one name, for drawing on its price line.

    Carries the entry price so a mark sits ON the series rather than being
    guessed from a date lookup, and the outcome so the chart can colour it
    without recomputing anything.
    """
    return [{
        "session": t.session, "price": t.entry_price, "quadrant": t.quadrant,
        "direction": t.direction, "divergence": t.divergence,
        "pnl_return": t.pnl_return, "won": t.won, "exit_price": t.exit_price,
    } for t in board.trades if t.symbol == symbol]

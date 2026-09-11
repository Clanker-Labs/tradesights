"""Separating the winners from the losers, without inventing the separation.

The scoreboard says what happened. This module asks WHY, which is a far more
dangerous question, because a search over a small sample will always find an
answer and the answer will always look convincing.

122 trades and six observable factors is enough to produce a rule that turns a
+0.22% edge into something that looks like a strategy. It is nowhere near enough
to know whether that rule means anything. Both of those are true at once, and a
tool that reports the first without the second is not analytics, it is a
generator of confident mistakes.

So everything here comes in pairs: a number, and the reason to distrust it.

* **Factor strength** is reported as a rank correlation, not a linear one, for
  the reason core/backtest learned the hard way -- one catastrophic trade
  flattens Pearson while leaving the ordering intact.
* **Every threshold search reports how many rules it tried.** A best-of-60 rule
  is a different claim from a rule somebody proposed in advance, and the count
  is what lets a reader tell them apart.
* **The best rule is measured against shuffled labels.** Permute which trades
  won, re-run the identical search, and see how good the best rule looks when
  there is provably nothing to find. If the real rule does not clear that
  distribution, it is not a finding -- it is the search working as designed.

That last one is the whole point of this module. Without it, "root out the
losers" reliably produces a filter that would have worked and will not again.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, field

from tradesights.core.backtest import Scoreboard, Trade

#: Factors observable at signal time. `regime` is deliberately absent: it is one
#: value per session rather than per name, so "filter on regime" is a statement
#: about twelve days, not about 122 trades.
FACTORS: tuple[str, ...] = (
    "divergence", "price_z", "money_z", "talk_z", "rel_1m", "positioning_conflict",
)

#: A factor needs this many trades carrying a real value before it is scored at
#: all. talk_z is null for most names on most days, and a correlation over the
#: handful that have it is a statement about those names, not about the factor.
MIN_FACTOR_N = 30


def _rank(values: list[float]) -> list[float]:
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


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    return _pearson(_rank(xs), _rank(ys))


# ---------------------------------------------------------------------------
# risk: the shape of the record, not just its total
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RiskMetrics:
    """What a +0.67% mean hides.

    Two strategies with identical means are different trades if one wins small
    and often while the other wins huge and rarely, and the difference shows up
    as whether you can survive holding it.
    """

    n: int
    avg_win: float | None
    avg_loss: float | None
    #: avg_win / |avg_loss|. Below 1 means the winners are smaller than the
    #: losers and the hit rate is carrying the whole result.
    payoff_ratio: float | None
    #: Gross wins / gross losses. Below 1 means it lost money overall.
    profit_factor: float | None
    #: Mean outcome per trade, decomposed: hit*avg_win + (1-hit)*avg_loss.
    expectancy: float | None
    #: Mean / stdev of per-trade returns. NOT annualised: annualising 122 trades
    #: over 16 days produces a Sharpe in the double digits, which is a unit
    #: conversion pretending to be a discovery.
    return_per_unit_risk: float | None
    #: Worst peak-to-trough fall of the cumulative curve, in the same additive
    #: units as total_return.
    max_drawdown: float | None
    #: Longest run of consecutive losses. The number that decides whether a
    #: person actually keeps following the rule.
    max_losing_streak: int
    #: Share of total profit contributed by the single best trade. High means
    #: the record is one lucky name wearing a strategy's clothes.
    top_trade_share: float | None


def risk_metrics(board: Scoreboard) -> RiskMetrics:
    ts = board.trades
    if not ts:
        return RiskMetrics(0, None, None, None, None, None, None, None, 0, None)

    rs = [t.pnl_return for t in ts]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]

    avg_win = statistics.fmean(wins) if wins else None
    avg_loss = statistics.fmean(losses) if losses else None
    gross_win = sum(wins)
    gross_loss = -sum(losses)

    payoff = (avg_win / abs(avg_loss)) if (avg_win and avg_loss and avg_loss != 0) else None
    pf = (gross_win / gross_loss) if gross_loss > 0 else None
    hit = len(wins) / len(rs)
    expectancy = hit * (avg_win or 0.0) + (1 - hit) * (avg_loss or 0.0)

    sd = statistics.pstdev(rs)
    rpr = (statistics.fmean(rs) / sd) if sd > 0 else None

    peak = 0.0
    running = 0.0
    dd = 0.0
    streak = worst_streak = 0
    for r in rs:
        running += r
        peak = max(peak, running)
        dd = max(dd, peak - running)
        streak = streak + 1 if r <= 0 else 0
        worst_streak = max(worst_streak, streak)

    total = sum(rs)
    share = (max(rs) / total) if total > 0 else None

    return RiskMetrics(
        n=len(rs), avg_win=avg_win, avg_loss=avg_loss, payoff_ratio=payoff,
        profit_factor=pf, expectancy=expectancy, return_per_unit_risk=rpr,
        max_drawdown=dd, max_losing_streak=worst_streak, top_trade_share=share)


# ---------------------------------------------------------------------------
# factors: what actually separated them
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FactorReport:
    """One observable, scored against what happened."""

    name: str
    n: int
    #: Rank correlation with the signed return. The "information coefficient".
    ic: float | None
    #: Mean factor value among winners, and among losers.
    winner_mean: float | None
    loser_mean: float | None
    #: Difference in means over the pooled spread. Roughly "how many standard
    #: deviations apart the two groups sit" — a readable effect size that does
    #: not pretend to be a p-value.
    separation: float | None
    quartiles: list[dict] = field(default_factory=list)
    note: str = ""


def _values(board: Scoreboard, name: str) -> list[tuple[Trade, float]]:
    out = []
    for t in board.trades:
        v = (t.factors or {}).get(name) if hasattr(t, "factors") else None
        if v is None:
            continue
        try:
            out.append((t, float(v)))
        except (TypeError, ValueError):
            continue
    return out


def factor_reports(board: Scoreboard, factors=FACTORS) -> list[FactorReport]:
    """Score every observable against the outcome, strongest separation first."""
    reports: list[FactorReport] = []
    for name in factors:
        pairs = _values(board, name)
        n = len(pairs)
        if n < MIN_FACTOR_N:
            reports.append(FactorReport(
                name=name, n=n, ic=None, winner_mean=None, loser_mean=None,
                separation=None,
                note=(f"only {n} trade(s) carry this — below {MIN_FACTOR_N} it "
                      f"describes those names, not this factor.")))
            continue

        xs = [v for _, v in pairs]
        ys = [t.pnl_return for t, _ in pairs]
        w = [v for t, v in pairs if t.won]
        l = [v for t, v in pairs if not t.won]

        sep = None
        if w and l:
            pooled = statistics.pstdev(xs)
            if pooled > 0:
                sep = (statistics.fmean(w) - statistics.fmean(l)) / pooled

        order = sorted(pairs, key=lambda p: p[1])
        size = max(1, n // 4)
        edges = [i * size for i in range(4)] + [n]
        quarts = []
        for a, b in zip(edges, edges[1:]):
            chunk = order[a:b]
            if not chunk:
                continue
            quarts.append({
                "from": round(chunk[0][1], 3), "to": round(chunk[-1][1], 3),
                "n": len(chunk),
                "mean_return": statistics.fmean(t.pnl_return for t, _ in chunk),
                "hit_rate": sum(1 for t, _ in chunk if t.won) / len(chunk),
            })

        reports.append(FactorReport(
            name=name, n=n, ic=_spearman(xs, ys),
            winner_mean=statistics.fmean(w) if w else None,
            loser_mean=statistics.fmean(l) if l else None,
            separation=sep, quartiles=quarts))

    reports.sort(key=lambda r: abs(r.separation) if r.separation is not None else -1,
                 reverse=True)
    return reports


# ---------------------------------------------------------------------------
# filters: the part that will lie to you if you let it
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Rule:
    """A filter, and what taking only those trades would have returned."""

    factor: str
    op: str            # ">=" or "<="
    threshold: float
    n: int
    hit_rate: float
    mean_return: float
    total_return: float
    #: Improvement over taking every trade.
    lift: float


@dataclass(frozen=True)
class FilterStudy:
    """The best rule found, and the reason to disbelieve it."""

    baseline_mean: float
    baseline_n: int
    rules: list[Rule]
    best: Rule | None
    #: How many thresholds were evaluated to find `best`.
    tried: int
    #: Best lift found on each of N shuffles, where nothing is findable.
    null_best: list[float] = field(default_factory=list)
    #: Share of shuffles whose best rule beat the real best. This is a p-value
    #: in everything but name: 0.30 means three runs in ten do this well on
    #: noise.
    p_value: float | None = None
    verdict: str = ""


#: Minimum trades a rule must keep. A filter that leaves eight trades has not
#: found an edge, it has found eight trades.
MIN_RULE_N = 25


def _apply(pairs, op: str, thr: float):
    return [t for t, v in pairs if (v >= thr if op == ">=" else v <= thr)]


def _positions(board: Scoreboard) -> dict[int, int]:
    """Trade -> its index in board.trades, by identity.

    Keyed on id() because Trade is not hashable in a useful way here (two
    genuinely distinct trades can compare equal on every field), and board.trades
    holds a strong reference for the whole call so the ids cannot be recycled
    under us. Isolated in one function so that reasoning lives next to the trick
    rather than inline where it reads like a bug.
    """
    return {id(t): i for i, t in enumerate(board.trades)}


def filter_study(board: Scoreboard, factors=FACTORS, *, steps: int = 9,
                 shuffles: int = 200, seed: int = 0) -> FilterStudy:
    """Search for a rule that separates winners from losers, then try to break it.

    The search is exhaustive and small on purpose: deciles of each factor, both
    directions. The permutation test is the part that matters. Shuffling which
    trades won destroys any real relationship while preserving the sample size,
    the factor distributions and the search itself — so whatever the search finds
    on shuffled data is exactly what it can manufacture from nothing. A real rule
    has to beat that, and most do not.
    """
    base = board.trades
    if not base:
        return FilterStudy(0.0, 0, [], None, 0, verdict="no trades to study.")

    base_mean = statistics.fmean(t.pnl_return for t in base)
    rules: list[Rule] = []
    tried = 0
    # (factor, op, threshold) triples, evaluated once and reused for every shuffle
    # so the null search is provably the same search.
    grid: list[tuple[str, str, float, list[Trade]]] = []

    for name in factors:
        pairs = _values(board, name)
        if len(pairs) < MIN_FACTOR_N:
            continue
        vs = sorted(v for _, v in pairs)
        cuts = sorted({vs[int(len(vs) * i / (steps + 1))] for i in range(1, steps + 1)})
        for thr in cuts:
            for op in (">=", "<="):
                kept = _apply(pairs, op, thr)
                tried += 1
                if len(kept) < MIN_RULE_N:
                    continue
                grid.append((name, op, thr, kept))
                m = statistics.fmean(t.pnl_return for t in kept)
                rules.append(Rule(
                    factor=name, op=op, threshold=round(thr, 4), n=len(kept),
                    hit_rate=sum(1 for t in kept if t.won) / len(kept),
                    mean_return=m, total_return=sum(t.pnl_return for t in kept),
                    lift=m - base_mean))

    rules.sort(key=lambda r: r.lift, reverse=True)
    best = rules[0] if rules else None
    if best is None:
        return FilterStudy(base_mean, len(base), [], None, tried,
                           verdict=f"no rule kept at least {MIN_RULE_N} trades.")

    # --- the honesty machine -------------------------------------------------
    rng = random.Random(seed)
    returns = [t.pnl_return for t in base]
    pos = _positions(board)
    # Resolve each rule to the POSITIONS it keeps, once. The shuffle then only
    # has to index, and every permutation provably sees the identical search
    # rather than a re-derived one.
    kept_idx = [[pos[id(t)] for t in kept] for _name, _op, _thr, kept in grid]

    null_best: list[float] = []
    for _ in range(shuffles):
        shuffled = returns[:]
        rng.shuffle(shuffled)
        mean_all = statistics.fmean(shuffled)
        top = -math.inf
        for idxs in kept_idx:
            top = max(top, statistics.fmean([shuffled[i] for i in idxs]) - mean_all)
        null_best.append(top)

    beat = sum(1 for v in null_best if v >= best.lift)
    p = beat / len(null_best) if null_best else None

    if p is None:
        verdict = "no null distribution — cannot say."
    elif p <= 0.05:
        verdict = (f"the best rule beat {100 * (1 - p):.0f}% of searches over "
                   f"shuffled outcomes. Worth a second look — but it is still "
                   f"one sample of {len(base)} trades over {board.horizon_days} "
                   f"day horizons, and it was chosen BECAUSE it was best.")
    else:
        verdict = (f"{100 * p:.0f}% of searches over SHUFFLED outcomes found a "
                   f"rule at least this good. This rule is what the search "
                   f"manufactures from noise — not a finding. Taking it live "
                   f"would be fitting {tried} tried thresholds to "
                   f"{len(base)} trades.")

    return FilterStudy(base_mean, len(base), rules[:12], best, tried,
                       null_best=sorted(null_best)[-25:], p_value=p, verdict=verdict)

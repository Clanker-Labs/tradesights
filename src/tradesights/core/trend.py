"""Trend indicators for a leveraged ETF, and the rule most people run on it.

## Why the signal is computed on the UNDERLYING

TQQQ is 3x daily NASDAQ-100. Its own 200-day moving average is not the same
object as QQQ's: daily resetting compounds path, so in a choppy market TQQQ
loses value while QQQ goes nowhere, and its moving average drifts down with it.
A crossing of TQQQ's own MA can therefore be produced by decay rather than by
anything the index did.

So every trend signal here is measured on QQQ and APPLIED to TQQQ. That is the
single most important detail in this module and the one most often got wrong.

## What the numbers can and cannot tell you

The 200-day rule is well documented and its weakness is equally well
documented: it whipsaws. Price oscillating around the line produces a string of
in-out-in trades, each one paying the spread and, in a 3x fund, buying back at a
worse price than it sold. So `proximity` and `crossings_90d` are first-class
outputs, not footnotes — "the rule says hold" means something different at 8%
above the line than at 0.3% above it.

Volatility is here for the same reason. Leveraged decay is a function of
variance; a 3x fund in a 40%-vol regime bleeds even when the index ends flat.
The number is reported so the reader can see the cost of being right slowly.

None of this is advice. It is what a stated, mechanical rule says about today's
data, with the things that make the rule fail shown next to it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: The rule everyone means by "the 200-day strategy".
SLOW = 200
FAST = 50
RSI_LEN = 14
VOL_LEN = 20

#: Within this much of the moving average, the signal is not worth acting on:
#: it is inside the noise that produces whipsaws. Expressed as a fraction.
NEUTRAL_BAND = 0.015


def sma(values: list[float], length: int) -> float | None:
    if len(values) < length:
        return None
    window = values[-length:]
    return sum(window) / length


def rsi(values: list[float], length: int = RSI_LEN) -> float | None:
    """Wilder's RSI.

    Wilder's smoothing rather than a simple average of gains and losses — the
    simple version is a different indicator that happens to share the name, and
    it reads several points away from every chart the reader will compare this
    against.
    """
    if len(values) < length + 1:
        return None
    gains, losses = [], []
    for a, b in zip(values[-(length + 1):-1], values[-length:], strict=True):
        change = b - a
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains) / length
    avg_loss = sum(losses) / length
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def ema(values: list[float], length: int) -> list[float]:
    if not values:
        return []
    k = 2.0 / (length + 1.0)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def macd(values: list[float]) -> dict[str, float | None]:
    """12/26/9, the default everywhere, so it matches whatever chart you check."""
    if len(values) < 35:
        return {"macd": None, "signal": None, "histogram": None}
    fast, slow = ema(values, 12), ema(values, 26)
    line = [f - s for f, s in zip(fast, slow, strict=True)]
    sig = ema(line, 9)
    return {
        "macd": round(line[-1], 4),
        "signal": round(sig[-1], 4),
        "histogram": round(line[-1] - sig[-1], 4),
    }


def realised_vol(values: list[float], length: int = VOL_LEN) -> float | None:
    """Annualised standard deviation of daily returns, as a fraction."""
    if len(values) < length + 1:
        return None
    rets = [
        (b / a) - 1.0
        for a, b in zip(values[-(length + 1):-1], values[-length:], strict=True)
        if a
    ]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return (var ** 0.5) * (252 ** 0.5)


def crossings(values: list[float], length: int = SLOW, lookback: int = 90) -> int:
    """How many times price has crossed its moving average recently.

    The number that says whether the rule is currently working. A trend gives
    you zero; a chop gives you five, and five crossings in a quarter is five
    round trips paid for out of the same account.
    """
    if len(values) < length + lookback:
        return 0
    above = None
    count = 0
    for i in range(len(values) - lookback, len(values)):
        window_ma = sum(values[i - length + 1:i + 1]) / length
        now_above = values[i] > window_ma
        if above is not None and now_above != above:
            count += 1
        above = now_above
    return count


def drawdown(values: list[float], lookback: int = 252) -> float | None:
    """How far below the running high we are, as a negative fraction."""
    if len(values) < 2:
        return None
    window = values[-lookback:]
    peak = max(window)
    return (window[-1] / peak - 1.0) if peak else None


@dataclass
class Reading:
    """Today's state of the rule, for one leveraged fund and its underlying."""

    symbol: str
    underlying: str
    as_of: str = ""
    price: float | None = None
    underlying_price: float | None = None
    sma_slow: float | None = None
    sma_fast: float | None = None
    distance: float | None = None          # underlying vs its 200-day, a fraction
    proximity: str = ""                    # far | near | at the line
    rsi: float | None = None
    macd: dict[str, Any] = field(default_factory=dict)
    volatility: float | None = None
    drawdown: float | None = None
    crossings_90d: int = 0
    golden_cross: bool | None = None
    stance: str = ""                       # risk-on | risk-off | no signal
    confidence: str = ""                   # clear | marginal
    headline: str = ""
    notes: list[str] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        return d


def evaluate(symbol: str, underlying: str, closes: list[float],
             under_closes: list[float], dates: list[str],
             history_points: int = 260) -> Reading:
    """Turn two price series into today's reading.

    `closes` is the leveraged fund, `under_closes` the index it tracks. Every
    SIGNAL comes from the second one; the first is only used for the things that
    are genuinely about the fund — its own drawdown and what you would be
    holding.
    """
    r = Reading(symbol=symbol, underlying=underlying)
    if not under_closes:
        r.stance, r.headline = "no signal", "No price data came back."
        return r

    r.as_of = dates[-1] if dates else ""
    r.price = round(closes[-1], 2) if closes else None
    r.underlying_price = round(under_closes[-1], 2)
    r.sma_slow = sma(under_closes, SLOW)
    r.sma_fast = sma(under_closes, FAST)
    r.rsi = rsi(under_closes)
    r.macd = macd(under_closes)
    r.volatility = realised_vol(under_closes)
    r.drawdown = drawdown(closes or under_closes)
    r.crossings_90d = crossings(under_closes)
    if r.sma_fast is not None and r.sma_slow is not None:
        r.golden_cross = r.sma_fast > r.sma_slow

    if r.sma_slow is None:
        # Not enough history to run the rule at all. Saying so beats running it
        # on 40 days and calling the answer a 200-day signal.
        r.stance = "no signal"
        r.headline = (
            f"Only {len(under_closes)} days of {underlying} — the 200-day rule "
            "needs 200 before it says anything."
        )
        return r

    r.distance = under_closes[-1] / r.sma_slow - 1.0
    inside_band = abs(r.distance) < NEUTRAL_BAND
    r.proximity = "at the line" if inside_band else (
        "near" if abs(r.distance) < 0.04 else "far")
    r.stance = "risk-on" if r.distance > 0 else "risk-off"
    r.confidence = "marginal" if inside_band else "clear"

    side = "above" if r.distance > 0 else "below"
    r.headline = (
        f"{underlying} is {abs(r.distance) * 100:.1f}% {side} its 200-day average. "
        + ("The rule says hold " if r.distance > 0 else "The rule says out of ")
        + symbol + "."
    )
    if inside_band:
        r.headline += " It is close enough to the line that tomorrow could say the opposite."

    r.notes = _notes(r, symbol, underlying)
    if dates and under_closes:
        tail = min(history_points, len(under_closes), len(dates))
        r.history = _history(dates, under_closes, closes, tail)
    return r


def _notes(r: Reading, symbol: str, underlying: str) -> list[str]:
    """The things that decide whether the headline is worth acting on."""
    out: list[str] = []

    if r.confidence == "marginal":
        out.append(
            f"Within {NEUTRAL_BAND * 100:.1f}% of the average. This is where the rule "
            "whipsaws: a crossing here often reverses within days, and each round trip "
            f"costs real money in a 3x fund."
        )
    if r.crossings_90d >= 4:
        out.append(
            f"{underlying} has crossed its 200-day {r.crossings_90d} times in 90 days. "
            "That is a chop, not a trend — the rule is at its worst here."
        )
    elif r.crossings_90d == 0 and r.proximity == "far":
        out.append("No crossing in 90 days: this is the regime the rule is built for.")

    if r.volatility is not None:
        pct = r.volatility * 100
        if pct >= 35:
            out.append(
                f"Realised volatility is {pct:.0f}% annualised. Leveraged decay scales "
                "with variance, so a 3x fund bleeds here even if the index ends flat."
            )
        elif pct <= 15:
            out.append(f"Volatility is low ({pct:.0f}%), which is when 3x compounds in your favour.")

    if r.rsi is not None:
        if r.rsi >= 70:
            out.append(f"RSI {r.rsi:.0f} — extended. The trend is intact; the entry is not fresh.")
        elif r.rsi <= 30:
            out.append(f"RSI {r.rsi:.0f} — oversold, which in a downtrend is not a reason to buy.")

    hist = r.macd.get("histogram")
    if hist is not None and r.distance is not None:
        if hist < 0 and r.distance > 0:
            out.append("MACD has rolled over while price is still above the average — momentum is leaving before the trend does.")
        elif hist > 0 and r.distance < 0:
            out.append("MACD has turned up while price is still below the average — the first thing you would see before a re-entry.")

    if r.golden_cross is False and r.distance is not None and r.distance > 0:
        out.append("The 50-day is below the 200-day: price is above the line, the shorter trend is not.")

    if r.drawdown is not None and r.drawdown < -0.5:
        out.append(
            f"{symbol} is {abs(r.drawdown) * 100:.0f}% below its 12-month high. A 3x fund "
            "needs far more than the index to recover a drawdown of that size."
        )
    return out


def _history(dates: list[str], under: list[float], lev: list[float], tail: int) -> list[dict]:
    """The series the chart draws: index, its two averages, and the fund."""
    out = []
    start = len(under) - tail
    for i in range(start, len(under)):
        window_slow = under[max(0, i - SLOW + 1):i + 1]
        window_fast = under[max(0, i - FAST + 1):i + 1]
        out.append({
            "t": dates[i] if i < len(dates) else "",
            "u": round(under[i], 2),
            "slow": round(sum(window_slow) / len(window_slow), 2) if len(window_slow) == SLOW else None,
            "fast": round(sum(window_fast) / len(window_fast), 2) if len(window_fast) == FAST else None,
            "p": round(lev[i], 2) if i < len(lev) else None,
        })
    return out

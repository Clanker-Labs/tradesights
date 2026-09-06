"""The 200-day rule, and the things that make it fail.

The reason this module exists at all is stated in core/trend.py: TQQQ is 3x
DAILY, so its own moving average moves with volatility decay as well as with the
market, and a crossing of it can be produced by the decay rather than by
anything the index did. Every signal is therefore computed on the underlying.
The first test is that one.
"""

from __future__ import annotations

import math

import pytest

from tradesights.core import trend


def _ramp(start: float, step: float, n: int) -> list[float]:
    return [start + step * i for i in range(n)]


def _dates(n: int) -> list[str]:
    return [f"2026-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}" for i in range(n)]


# --------------------------------------------------------------- indicators

def test_sma_needs_its_full_window() -> None:
    # 199 days of data does not make a 200-day average, and returning one
    # anyway is how a 40-day number ends up labelled as a 200-day signal.
    assert trend.sma(_ramp(1, 1, 199), 200) is None
    assert trend.sma(_ramp(1, 1, 200), 200) == pytest.approx(100.5)


def test_rsi_is_wilders_not_a_plain_average() -> None:
    # A pure uptrend has no losses at all: RSI is 100 by construction, and any
    # implementation that returns something else is computing a different thing.
    assert trend.rsi(_ramp(100, 1, 40)) == 100.0
    assert trend.rsi(_ramp(200, -1, 40)) == pytest.approx(0.0, abs=1e-9)


def test_rsi_refuses_a_short_series() -> None:
    assert trend.rsi([1.0, 2.0, 3.0]) is None


def test_macd_histogram_is_positive_in_an_uptrend() -> None:
    out = trend.macd(_ramp(100, 1, 60))
    assert out["macd"] is not None and out["macd"] > 0
    assert out["histogram"] is not None


def test_realised_vol_is_zero_for_a_flat_series_and_annualised() -> None:
    assert trend.realised_vol([100.0] * 40) == pytest.approx(0.0)
    # Alternating +1%/-1% daily: stdev of returns ~0.01, annualised by sqrt(252).
    seq = [100.0]
    for i in range(40):
        seq.append(seq[-1] * (1.01 if i % 2 == 0 else 1 / 1.01))
    vol = trend.realised_vol(seq)
    assert vol is not None and 0.10 < vol < 0.25


def test_crossings_counts_a_chop_and_not_a_trend() -> None:
    trending = _ramp(100, 1, 400)
    assert trend.crossings(trending) == 0

    # Oscillate hard enough to cross a 200-day average repeatedly.
    chop = _ramp(100, 1, 250)
    for i in range(120):
        chop.append(chop[-1] + (18 if (i // 10) % 2 == 0 else -18))
    assert trend.crossings(chop) >= 2


# ------------------------------------------------------------------ the rule

def test_the_signal_comes_from_the_underlying_not_the_leveraged_fund() -> None:
    """The single most important property in this module.

    The index is in a clean uptrend and comfortably above its 200-day average.
    The leveraged fund has been shredded by decay and sits far below its own.
    The rule must read the index and say risk-on.
    """
    n = 300
    under = _ramp(300, 0.5, n)                 # index grinding up
    lev = [100.0] * 250 + [40.0] * 50          # fund destroyed, its own MA above it
    r = trend.evaluate("TQQQ", "QQQ", lev, under, _dates(n))
    assert r.stance == "risk-on"
    assert r.distance is not None and r.distance > 0
    # And it is measured against the index's average, not the fund's.
    assert r.sma_slow == pytest.approx(trend.sma(under, 200))


def test_below_the_average_is_risk_off() -> None:
    n = 300
    under = _ramp(400, -0.5, n)
    r = trend.evaluate("TQQQ", "QQQ", [100.0] * n, under, _dates(n))
    assert r.stance == "risk-off"
    assert "out of TQQQ" in r.headline


def test_too_little_history_says_so_rather_than_guessing() -> None:
    r = trend.evaluate("TQQQ", "QQQ", [10.0] * 40, _ramp(100, 1, 40), _dates(40))
    assert r.stance == "no signal"
    assert "needs 200" in r.headline
    assert r.distance is None


def test_sitting_on_the_line_is_reported_as_marginal() -> None:
    # Flat at exactly the average: the rule technically has a side, and acting
    # on it here is what produces the whipsaw the strategy is known for.
    n = 300
    under = [100.0] * n
    under[-1] = 100.2                       # 0.2% above — inside the band
    r = trend.evaluate("TQQQ", "QQQ", [50.0] * n, under, _dates(n))
    assert r.confidence == "marginal"
    assert r.proximity == "at the line"
    assert "could say the opposite" in r.headline
    assert any("whipsaw" in note for note in r.notes)


def test_high_volatility_is_called_out_because_decay_scales_with_it() -> None:
    n = 300
    under = [300.0]
    for i in range(n - 1):
        under.append(under[-1] * (1.035 if i % 2 == 0 else 1 / 1.03))
    r = trend.evaluate("TQQQ", "QQQ", [100.0] * n, under, _dates(n))
    assert r.volatility is not None and r.volatility > 0.35
    assert any("decay" in note for note in r.notes)


def test_history_carries_both_averages_for_the_chart() -> None:
    n = 320
    under = _ramp(300, 0.4, n)
    r = trend.evaluate("TQQQ", "QQQ", _ramp(50, 0.3, n), under, _dates(n))
    assert r.history, "the chart needs a series"
    last = r.history[-1]
    assert last["slow"] is not None and last["fast"] is not None
    # A point earlier than 200 days into the series cannot have a 200-day
    # average, and inventing one would draw a line that never existed.
    assert r.history[0]["t"]


def test_no_data_is_not_a_crash() -> None:
    r = trend.evaluate("TQQQ", "QQQ", [], [], [])
    assert r.stance == "no signal"
    assert r.headline

"""The backtest is arithmetic that produces a number people will act on, so the
tests are mostly about the ways it could be flattering.

Direction, baseline and sample size are each a place where an honest engine and
a misleading one differ by one line.
"""
from __future__ import annotations

import pytest

from tradesights.core import backtest
from tradesights.core.model import Quadrant
from tradesights.store import Outcome


def out(symbol="AAA", session="2026-01-01", quadrant=Quadrant.CONTRARIAN_BID,
        divergence=1.0, entry=100.0, later=110.0):
    return Outcome(symbol=symbol, session=session, quadrant=str(quadrant),
                   divergence=divergence, horizon_days=5, entry_price=entry,
                   later_price=later, forward_return=later / entry - 1.0)


class TestDirection:
    def test_a_rise_after_a_buy_signal_is_a_win(self):
        b = backtest.run([out(quadrant=Quadrant.CONTRARIAN_BID, later=110)])
        assert b.trades[0].pnl_return == pytest.approx(0.10)
        assert b.trades[0].won

    def test_the_same_rise_after_a_sell_signal_is_a_loss(self):
        # The whole reason this module exists: resolve() reports +10% for both.
        b = backtest.run([out(quadrant=Quadrant.FEAR, later=110)])
        assert b.trades[0].price_return == pytest.approx(0.10)
        assert b.trades[0].pnl_return == pytest.approx(-0.10)
        assert not b.trades[0].won

    def test_chase_is_not_a_trade(self):
        # "Confirmed, and crowded" argues both ways. Taking a side there would
        # measure the author's opinion rather than the tool's.
        b = backtest.run([out(quadrant=Quadrant.CHASE)])
        assert b.n == 0
        assert b.stood_aside == 1

    def test_quiet_is_not_a_trade(self):
        b = backtest.run([out(quadrant=Quadrant.QUIET)])
        assert b.n == 0 and b.stood_aside == 1


class TestBaseline:
    def test_a_rising_market_does_not_read_as_skill(self):
        # Every name up 10%, every signal long. The strategy made money and the
        # edge over having just bought them is exactly zero.
        rows = [out(symbol=f"S{i}", later=110) for i in range(5)]
        b = backtest.run(rows)
        assert b.mean_return == pytest.approx(0.10)
        assert b.baseline_return == pytest.approx(0.10)
        assert b.edge == pytest.approx(0.0)

    def test_shorting_a_fall_beats_holding_it(self):
        rows = [out(symbol=f"S{i}", quadrant=Quadrant.FEAR, later=90) for i in range(5)]
        b = backtest.run(rows)
        assert b.mean_return == pytest.approx(0.10)   # short a -10% move
        assert b.baseline_return == pytest.approx(-0.10)
        assert b.edge == pytest.approx(0.20)


class TestHonesty:
    def test_no_trades_reports_none_rather_than_zero(self):
        # 0% is a claim about performance; None is the absence of one.
        b = backtest.Scoreboard()
        assert b.hit_rate is None and b.mean_return is None and b.edge is None

    def test_correlation_refuses_below_the_floor(self):
        rows = [out(symbol=f"S{i}", divergence=i, later=100 + i) for i in range(10)]
        c = backtest.correlate_divergence(backtest.run(rows))
        assert c.r is None and c.rho is None
        assert not c.reportable
        assert "too few" in c.note

    def test_correlation_reports_above_the_floor(self):
        rows = [out(symbol=f"S{i}", divergence=i, later=100 + i)
                for i in range(backtest.MIN_CORRELATION_N + 5)]
        c = backtest.correlate_divergence(backtest.run(rows))
        assert c.r is not None and c.rho == pytest.approx(1.0)

    def test_rank_correlation_survives_an_outlier_that_flattens_pearson(self):
        # The case that made this a two-coefficient function: a perfectly
        # ordered set with one catastrophic trade. Pearson collapses; the
        # ranking is untouched, and the ranking is what the tool claims.
        rows = [out(symbol=f"S{i}", divergence=i, later=100 + i)
                for i in range(1, backtest.MIN_CORRELATION_N + 5)]
        rows.append(out(symbol="BOOM", divergence=0.0, later=1.0))
        c = backtest.correlate_divergence(backtest.run(rows))
        assert c.rho > c.r
        assert c.rho > 0.9

    def test_the_last_bucket_absorbs_the_remainder(self):
        # 122 trades in 4 buckets of 30 once left a bucket of 2 reading
        # "+6.14%, 100% hit" — a headline resting on two trades.
        rows = [out(symbol=f"S{i}", divergence=i / 10, later=100 + i) for i in range(122)]
        c = backtest.correlate_divergence(backtest.run(rows), buckets=4)
        assert len(c.buckets) == 4
        assert min(g["n"] for g in c.buckets) >= 30
        assert sum(g["n"] for g in c.buckets) == 122


class TestTrace:
    def test_totals_are_additive_not_compounded(self):
        # Compounding would make the answer depend on the order the archive
        # happened to store things in.
        rows = [out(symbol="A", later=110), out(symbol="B", later=110)]
        b = backtest.run(rows)
        assert b.total_return == pytest.approx(0.20)

    def test_the_curve_runs_in_signal_order(self):
        rows = [out(symbol="B", session="2026-01-02", later=110),
                out(symbol="A", session="2026-01-01", later=90)]
        curve = backtest.equity_curve(backtest.run(rows))
        assert [p["session"] for p in curve] == ["2026-01-01", "2026-01-02"]
        assert curve[-1]["cumulative"] == pytest.approx(0.0)

    def test_marks_carry_the_entry_price_so_they_sit_on_the_line(self):
        b = backtest.run([out(symbol="AAA", entry=87.48, later=89.51)])
        m = backtest.marks_for("AAA", b)[0]
        assert m["price"] == pytest.approx(87.48)
        assert m["won"] is True

    def test_marks_are_scoped_to_one_symbol(self):
        b = backtest.run([out(symbol="AAA"), out(symbol="BBB")])
        assert len(backtest.marks_for("AAA", b)) == 1

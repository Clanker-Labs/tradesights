"""These tests are mostly about the module refusing to find things.

Anything can compute a profit factor. The part worth pinning down is that the
filter search calls its own best rule noise when it is noise, because that is
the one behaviour standing between this tab and a confidently wrong trade.
"""
from __future__ import annotations

import random

import pytest

from tradesights.core import analytics, backtest
from tradesights.core.model import Quadrant
from tradesights.store import Outcome


def out(symbol="AAA", session="2026-01-01", quadrant=Quadrant.CONTRARIAN_BID,
        divergence=1.0, entry=100.0, later=110.0, **factors):
    f = {"divergence": divergence, "price_z": 0.0, "money_z": 0.0,
         "talk_z": None, "rel_1m": 0.0, "positioning_conflict": 0.0}
    f.update(factors)
    return Outcome(symbol=symbol, session=session, quadrant=str(quadrant),
                   divergence=divergence, horizon_days=5, entry_price=entry,
                   later_price=later, forward_return=later / entry - 1.0, factors=f)


def board_of(rows):
    return backtest.run(rows, horizon_days=5)


class TestRisk:
    def test_payoff_below_one_means_the_hit_rate_is_carrying_it(self):
        rows = [out(symbol="W", later=101)] * 3 + [out(symbol="L", later=95)]
        r = analytics.risk_metrics(board_of(rows))
        assert r.payoff_ratio < 1
        assert r.avg_win == pytest.approx(0.01)

    def test_drawdown_is_peak_to_trough_not_worst_trade(self):
        # Three consecutive -5% trades are a 15% drawdown even though no single
        # trade lost more than 5%.
        rows = [out(later=95), out(later=95), out(later=95)]
        r = analytics.risk_metrics(board_of(rows))
        assert r.max_drawdown == pytest.approx(0.15, abs=1e-9)
        assert r.max_losing_streak == 3

    def test_concentration_is_reported(self):
        # One name carrying the record is a lucky name, not an edge.
        rows = [out(symbol="BIG", later=200)] + [out(symbol=f"S{i}", later=101) for i in range(4)]
        r = analytics.risk_metrics(board_of(rows))
        assert r.top_trade_share > 0.9

    def test_empty_reports_none_rather_than_zero(self):
        r = analytics.risk_metrics(backtest.Scoreboard())
        assert r.n == 0 and r.profit_factor is None and r.max_drawdown is None


class TestFactors:
    def test_a_factor_almost_nothing_carries_is_refused(self):
        # talk_z is null for most names on most days.
        rows = [out(symbol=f"S{i}") for i in range(40)]
        rep = {f.name: f for f in analytics.factor_reports(board_of(rows))}
        assert rep["talk_z"].ic is None
        assert "below" in rep["talk_z"].note

    def test_a_real_separation_is_found(self):
        winners = [out(symbol=f"W{i}", later=110, price_z=2.0) for i in range(20)]
        losers = [out(symbol=f"L{i}", later=90, price_z=-2.0) for i in range(20)]
        rep = {f.name: f for f in analytics.factor_reports(board_of(winners + losers))}
        assert rep["price_z"].separation > 1.5
        assert rep["price_z"].winner_mean > rep["price_z"].loser_mean

    def test_a_factor_with_no_relationship_separates_near_zero(self):
        rng = random.Random(7)
        rows = [out(symbol=f"S{i}", later=100 + rng.choice([-8, 8]),
                    money_z=rng.gauss(0, 1)) for i in range(120)]
        rep = {f.name: f for f in analytics.factor_reports(board_of(rows))}
        assert abs(rep["money_z"].separation) < 0.6


class TestFilterHonesty:
    """The reason this module exists."""

    def test_a_search_over_pure_noise_is_called_noise(self):
        # Random factors, random outcomes. The search WILL find a rule with a
        # good-looking lift; the shuffle test must refuse to endorse it.
        rng = random.Random(11)
        rows = [out(symbol=f"S{i}",
                    later=100 * (1 + rng.gauss(0, 0.03)),
                    divergence=rng.random() * 4,
                    price_z=rng.gauss(0, 1),
                    money_z=rng.gauss(0, 1),
                    rel_1m=rng.gauss(0, 0.05),
                    positioning_conflict=rng.random())
                for i in range(150)]
        study = analytics.filter_study(board_of(rows), shuffles=200, seed=3)
        assert study.best is not None, "the search should still find a best rule"
        assert study.best.lift > 0, "on noise the best rule still looks positive"
        assert study.p_value > 0.05, "…and the shuffle test must say so"
        assert "noise" in study.verdict or "manufactures" in study.verdict

    def test_a_planted_edge_survives_the_shuffle(self):
        # A factor that genuinely determines the outcome must clear the null,
        # otherwise the test is just always saying no.
        rng = random.Random(5)
        rows = []
        for i in range(150):
            good = i % 2 == 0
            rows.append(out(symbol=f"S{i}",
                            later=100 * (1 + (0.05 if good else -0.05) + rng.gauss(0, 0.005)),
                            price_z=(2.0 if good else -2.0) + rng.gauss(0, 0.1),
                            divergence=rng.random() * 4,
                            money_z=rng.gauss(0, 1)))
        study = analytics.filter_study(board_of(rows), shuffles=200, seed=3)
        assert study.p_value <= 0.05
        assert study.best.factor == "price_z"

    def test_a_rule_that_keeps_too_few_trades_is_not_offered(self):
        rows = [out(symbol=f"S{i}", divergence=i, later=100 + i) for i in range(60)]
        study = analytics.filter_study(board_of(rows), shuffles=50)
        assert all(r.n >= analytics.MIN_RULE_N for r in study.rules)

    def test_the_number_of_thresholds_tried_is_reported(self):
        # A best-of-90 rule is a different claim from one proposed in advance.
        rows = [out(symbol=f"S{i}", divergence=i % 7, price_z=i % 5,
                    later=100 + (i % 11)) for i in range(120)]
        study = analytics.filter_study(board_of(rows), shuffles=50)
        assert study.tried > 20

    def test_no_trades_is_stated_not_scored(self):
        study = analytics.filter_study(backtest.Scoreboard())
        assert study.best is None and "no trades" in study.verdict

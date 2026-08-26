"""Tests for the archive, and especially for the parts that could flatter it.

An archive of a screener's own opinions is easy to make say whatever you want.
These pin the places where that would happen.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pytest

from tradesights import store
from tradesights.core.model import Quadrant, Signals


@dataclass
class FakeRow:
    symbol: str
    signals: Signals
    rel_1m: float
    quadrant: Quadrant
    divergence: float
    positioning_conflict: float = 0.0


@dataclass
class FakePrice:
    last: float


def row(symbol, price_z, money_z, quadrant=Quadrant.QUIET, divergence=1.0, talk_z=None):
    return FakeRow(symbol=symbol,
                   signals=Signals(symbol=symbol, price_z=price_z, money_z=money_z,
                                   talk_z=talk_z),
                   rel_1m=price_z / 10, quadrant=quadrant, divergence=divergence)


@pytest.fixture
def conn(tmp_path):
    connection = store.connect(tmp_path / "t.db")
    yield connection
    connection.close()


def test_a_snapshot_round_trips(conn):
    store.save([row("AAA", 1.0, -1.0, Quadrant.HEDGED_RALLY, 2.0)],
               prices={"AAA": FakePrice(100.0)}, session="2026-01-05", conn=conn)
    got = store.snapshot("2026-01-05", conn=conn)
    assert len(got) == 1
    assert got[0].symbol == "AAA"
    assert got[0].price == 100.0
    assert got[0].quadrant == "hedged_rally"


def test_saving_the_same_session_twice_replaces_it(conn):
    """A cron that fires twice would otherwise double-weight that day, silently."""
    for divergence in (1.0, 5.0):
        store.save([row("AAA", 1.0, -1.0, divergence=divergence)],
                   prices={"AAA": FakePrice(100.0)}, session="2026-01-05", conn=conn)
    assert len(store.sessions(conn=conn)) == 1
    assert store.snapshot("2026-01-05", conn=conn)[0].divergence == 5.0


def test_a_missing_price_is_zero_not_a_guess(conn):
    """A snapshot with no price can never be scored, and should say so."""
    store.save([row("AAA", 1.0, -1.0)], prices={}, session="2026-01-05", conn=conn)
    assert store.snapshot("2026-01-05", conn=conn)[0].price == 0.0


def test_history_comes_back_oldest_first(conn):
    for day in ("2026-01-07", "2026-01-05", "2026-01-06"):
        store.save([row("AAA", 1.0, -1.0)], prices={"AAA": FakePrice(100.0)},
                   session=day, conn=conn)
    assert [o.session for o in store.history("AAA", conn=conn)] == [
        "2026-01-05", "2026-01-06", "2026-01-07"]


def test_talk_absence_survives_the_round_trip(conn):
    """None must not become 0. A name nobody checked is not a neutral name."""
    store.save([row("AAA", 1.0, -1.0, talk_z=None)],
               prices={"AAA": FakePrice(100.0)}, session="2026-01-05", conn=conn)
    assert store.snapshot("2026-01-05", conn=conn)[0].talk_z is None


# --- resolution ------------------------------------------------------------

def seed(conn, prices_by_day, quadrant=Quadrant.CONTRARIAN_BID):
    for day, price in prices_by_day.items():
        store.save([row("AAA", -1.0, 1.0, quadrant, 2.0)],
                   prices={"AAA": FakePrice(price)}, session=day, conn=conn)


def test_nothing_resolves_until_a_later_session_exists(conn):
    seed(conn, {"2026-01-05": 100.0})
    assert store.resolve(5, conn=conn) == []


def test_a_forward_return_is_measured_against_a_stored_later_price(conn):
    seed(conn, {"2026-01-05": 100.0, "2026-01-12": 110.0})
    outcomes = store.resolve(5, conn=conn)
    assert len(outcomes) == 1
    assert outcomes[0].forward_return == pytest.approx(0.10)


def test_the_horizon_is_calendar_days_so_a_weekend_still_resolves(conn):
    """A five-day horizon landing on a Saturday should resolve on the Monday."""
    seed(conn, {"2026-01-05": 100.0, "2026-01-12": 105.0})
    assert len(store.resolve(5, conn=conn)) == 1
    assert store.resolve(30, conn=conn) == []


def test_an_observation_with_no_price_is_skipped_not_scored_as_flat(conn):
    store.save([row("AAA", -1.0, 1.0)], prices={}, session="2026-01-05", conn=conn)
    store.save([row("AAA", -1.0, 1.0)], prices={"AAA": FakePrice(110.0)},
               session="2026-01-12", conn=conn)
    assert store.resolve(5, conn=conn) == []


def test_quadrant_edge_subtracts_the_rest_of_the_universe(conn):
    """In a rising market every quadrant looks predictive. Edge removes the tide."""
    outcomes = [
        store.Outcome("A", "2026-01-05", "contrarian_bid", 2.0, 5, 100, 112, 0.12),
        store.Outcome("B", "2026-01-05", "fear", 2.0, 5, 100, 110, 0.10),
        store.Outcome("C", "2026-01-05", "fear", 2.0, 5, 100, 110, 0.10),
    ]
    scores, _reasons = store.score_quadrants(outcomes)
    top = next(s for s in scores if s.quadrant == "contrarian_bid")
    assert top.mean_return == pytest.approx(0.12)
    assert top.baseline == pytest.approx(0.10)
    assert top.edge == pytest.approx(0.02)


def test_an_empty_archive_says_so_rather_than_returning_zeroes():
    scores, reasons = store.score_quadrants([])
    assert scores == []
    assert any("archive" in r for r in reasons)


def test_a_thin_quadrant_is_called_arithmetic_not_evidence():
    outcomes = [store.Outcome(f"S{i}", "2026-01-05", "fear", 2.0, 5, 100, 101, 0.01)
                for i in range(5)]
    _scores, reasons = store.score_quadrants(outcomes)
    assert any("arithmetic" in r for r in reasons)


def test_a_single_session_is_not_counted_as_many_observations():
    """Every name on one day shares a market; n is not the sample size."""
    outcomes = [store.Outcome(f"S{i}", "2026-01-05", "fear", 2.0, 5, 100, 101, 0.01)
                for i in range(60)]
    _scores, reasons = store.score_quadrants(outcomes)
    assert any("independent observations" in r for r in reasons)


def test_a_rising_universe_is_flagged_before_any_quadrant_is_believed():
    outcomes = [store.Outcome(f"S{i}", f"2026-01-{5+i%20:02d}", "fear", 2.0, 5,
                              100, 108, 0.08) for i in range(60)]
    _scores, reasons = store.score_quadrants(outcomes)
    assert any("rising market" in r for r in reasons)


def test_sessions_are_listed_newest_first(conn):
    for day in ("2026-01-05", "2026-01-06", "2026-01-07"):
        store.save([row("AAA", 1.0, -1.0)], prices={"AAA": FakePrice(1.0)},
                   session=day, conn=conn)
    assert [s["session"] for s in store.sessions(conn=conn)] == [
        "2026-01-07", "2026-01-06", "2026-01-05"]


def test_the_latest_snapshot_is_returned_when_no_session_is_named(conn):
    store.save([row("OLD", 1.0, -1.0)], prices={"OLD": FakePrice(1.0)},
               session="2026-01-05", conn=conn)
    store.save([row("NEW", 1.0, -1.0)], prices={"NEW": FakePrice(1.0)},
               session="2026-01-09", conn=conn)
    assert store.snapshot(conn=conn)[0].symbol == "NEW"


def test_resolve_does_not_reach_across_symbols(conn):
    """A forward price must come from the same name, obviously — and provably."""
    store.save([row("AAA", 1.0, -1.0), row("BBB", 1.0, -1.0)],
               prices={"AAA": FakePrice(100.0), "BBB": FakePrice(50.0)},
               session="2026-01-05", conn=conn)
    store.save([row("AAA", 1.0, -1.0), row("BBB", 1.0, -1.0)],
               prices={"AAA": FakePrice(110.0), "BBB": FakePrice(25.0)},
               session="2026-01-12", conn=conn)
    by_symbol = {o.symbol: o.forward_return for o in store.resolve(5, conn=conn)}
    assert by_symbol["AAA"] == pytest.approx(0.10)
    assert by_symbol["BBB"] == pytest.approx(-0.50)


def test_dates_used_for_the_horizon_are_real_dates_not_string_prefixes(conn):
    """String comparison would make 2026-01-9 sort after 2026-01-10."""
    seed(conn, {"2026-01-28": 100.0, "2026-02-04": 110.0})
    outcomes = store.resolve(5, conn=conn)
    assert len(outcomes) == 1
    assert dt.date.fromisoformat(outcomes[0].session) == dt.date(2026, 1, 28)

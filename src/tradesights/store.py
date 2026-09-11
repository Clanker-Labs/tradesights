"""Snapshots, so the screener can be asked whether it was ever right.

Without this the tool is a thing that produces an opinion every morning and
forgets it by lunch. That is enough to decide what to look at, and it is not
enough to decide whether looking there was ever worth it — because the question
that matters is not "which names are stretched today" but **"when a name looked
like this before, what happened next?"**, and answering it needs yesterday.

So every scan can be written down: the z-scores, the quadrant, the divergence,
and — the field that makes the rest useful — the close it was measured against.
A snapshot without a price records only that a name looked interesting, never
whether it then went anywhere.

What this is NOT:

**Not a backtest.** It cannot be. The archive starts the day it is switched on,
so it accumulates forward in real time rather than reaching backward, and it
takes months before it can say anything. Nothing in here reconstructs history
from current data — that would be a backtest of a screener against its own
inputs, which is a machine for confirming whatever you already believe.

**Not a performance record.** A forward return after a signal is not a trade.
There is no entry rule, no stop, no size and no cost, and the difference between
"names in this quadrant drifted up 1.2% over five days" and "this made money" is
every part of trading that is hard.

What it is: a way to find out whether a quadrant means anything, and to be told
that it does not.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshot (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    taken_at    TEXT    NOT NULL,
    session     TEXT    NOT NULL,
    universe    INTEGER NOT NULL,
    regime      TEXT,
    has_talk    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS observation (
    snapshot_id          INTEGER NOT NULL REFERENCES snapshot(id) ON DELETE CASCADE,
    symbol               TEXT    NOT NULL,
    price_z              REAL    NOT NULL,
    money_z              REAL    NOT NULL,
    talk_z               REAL,
    rel_1m               REAL    NOT NULL,
    quadrant             TEXT    NOT NULL,
    divergence           REAL    NOT NULL,
    positioning_conflict REAL    NOT NULL DEFAULT 0,
    price                REAL    NOT NULL DEFAULT 0,
    PRIMARY KEY (snapshot_id, symbol)
);
CREATE INDEX IF NOT EXISTS observation_symbol ON observation(symbol);
CREATE INDEX IF NOT EXISTS observation_quadrant ON observation(quadrant);
CREATE UNIQUE INDEX IF NOT EXISTS snapshot_session ON snapshot(session);
"""

#: One snapshot per trading session, enforced by a unique index rather than by
#: convention. A cron that fires twice, or a person running `snapshot` after an
#: agent already did, would otherwise double-weight that day in every statistic
#: computed later -- and it would do so silently, which is the worst kind.
_REPLACE_NOTE = "replacing the existing snapshot for this session"


def db_path() -> Path:
    root = os.environ.get("TRADESIGHTS_DB") or str(
        Path.home() / ".tradesights" / "history.db")
    return Path(root).expanduser()


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


@dataclass(frozen=True)
class Observation:
    """One name in one snapshot."""

    snapshot_id: int
    session: str
    symbol: str
    price_z: float
    money_z: float
    talk_z: float | None
    rel_1m: float
    quadrant: str
    divergence: float
    positioning_conflict: float
    price: float


def save(rows: Sequence, *, prices: dict, regime: str | None = None,
         session: str | None = None, conn: sqlite3.Connection | None = None) -> int:
    """Write one scan. Returns the snapshot id.

    `session` defaults to today in exchange terms. Re-saving the same session
    replaces it rather than adding a second row: a scan run twice in a morning
    is one morning's opinion, not two.
    """
    owned = conn is None
    conn = conn or connect()
    try:
        session = session or dt.date.today().isoformat()
        has_talk = any(r.signals.talk_z is not None for r in rows)

        with conn:
            existing = conn.execute("SELECT id FROM snapshot WHERE session = ?",
                                    (session,)).fetchone()
            if existing:
                logger.info("%s (%s)", _REPLACE_NOTE, session)
                conn.execute("DELETE FROM observation WHERE snapshot_id = ?",
                             (existing["id"],))
                conn.execute("DELETE FROM snapshot WHERE id = ?", (existing["id"],))
            cursor = conn.execute(
                "INSERT INTO snapshot (taken_at, session, universe, regime, has_talk) "
                "VALUES (?, ?, ?, ?, ?)",
                (dt.datetime.now().astimezone().isoformat(), session, len(rows),
                 regime, int(has_talk)))
            snapshot_id = int(cursor.lastrowid)
            conn.executemany(
                "INSERT INTO observation (snapshot_id, symbol, price_z, money_z, "
                "talk_z, rel_1m, quadrant, divergence, positioning_conflict, price) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(snapshot_id, r.symbol, r.signals.price_z, r.signals.money_z,
                  r.signals.talk_z, r.rel_1m, r.quadrant.value, r.divergence,
                  r.positioning_conflict,
                  float(getattr(prices.get(r.symbol), "last", 0.0) or 0.0))
                 for r in rows])
        return snapshot_id
    finally:
        if owned:
            conn.close()


def sessions(conn: sqlite3.Connection | None = None, limit: int = 400) -> list[dict]:
    """Every stored session, newest first."""
    owned = conn is None
    conn = conn or connect()
    try:
        rows = conn.execute(
            "SELECT s.id, s.session, s.taken_at, s.universe, s.regime, s.has_talk, "
            "       (SELECT COUNT(*) FROM observation o WHERE o.snapshot_id = s.id) AS n "
            "FROM snapshot s ORDER BY s.session DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        if owned:
            conn.close()


def snapshot(session: str | None = None,
             conn: sqlite3.Connection | None = None) -> list[Observation]:
    """One session's observations, most divergent first. Latest if unspecified."""
    owned = conn is None
    conn = conn or connect()
    try:
        if session is None:
            row = conn.execute("SELECT session FROM snapshot "
                               "ORDER BY session DESC LIMIT 1").fetchone()
            if row is None:
                return []
            session = row["session"]
        rows = conn.execute(
            "SELECT o.*, s.session FROM observation o JOIN snapshot s "
            "ON s.id = o.snapshot_id WHERE s.session = ? "
            "ORDER BY o.divergence DESC", (session,)).fetchall()
        return [_observation(r) for r in rows]
    finally:
        if owned:
            conn.close()


def history(symbol: str, conn: sqlite3.Connection | None = None,
            limit: int = 400) -> list[Observation]:
    """Every stored reading for one name, oldest first.

    The view that answers "has this been stretched for a week, or did it happen
    this morning" -- which is the first thing worth knowing about a name at the
    top of a list, and which a single scan structurally cannot tell you.
    """
    owned = conn is None
    conn = conn or connect()
    try:
        rows = conn.execute(
            "SELECT o.*, s.session FROM observation o JOIN snapshot s "
            "ON s.id = o.snapshot_id WHERE o.symbol = ? "
            "ORDER BY s.session ASC LIMIT ?", (symbol.upper(), limit)).fetchall()
        return [_observation(r) for r in rows]
    finally:
        if owned:
            conn.close()


def _observation(row: sqlite3.Row) -> Observation:
    return Observation(
        snapshot_id=row["snapshot_id"], session=row["session"], symbol=row["symbol"],
        price_z=row["price_z"], money_z=row["money_z"], talk_z=row["talk_z"],
        rel_1m=row["rel_1m"], quadrant=row["quadrant"], divergence=row["divergence"],
        positioning_conflict=row["positioning_conflict"], price=row["price"])


# --------------------------------------------------------------------------
# Resolution: did the disagreement go anywhere
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Outcome:
    """What happened to one observation over one horizon."""

    symbol: str
    session: str
    quadrant: str
    divergence: float
    horizon_days: int
    entry_price: float
    later_price: float
    forward_return: float
    #: Everything else that was observable at signal time, keyed by name.
    #:
    #: Optional and defaulted so nothing that already builds an Outcome has to
    #: change. It exists so the question "what separated the winners from the
    #: losers" can be asked of more than the one number that happened to be in
    #: the ranking — divergence is a summary, and a summary cannot tell you
    #: which of its inputs was carrying it.
    factors: dict = field(default_factory=dict)


def resolve(horizon_days: int = 5, conn: sqlite3.Connection | None = None,
            ) -> list[Outcome]:
    """Score every observation old enough to have an answer, against the archive.

    The forward price comes from a LATER SNAPSHOT of the same name, not from a
    fresh download. That is deliberate and it is a real limitation: it means a
    name is only scored if it was still in the universe on the later day, and it
    means nothing resolves until enough sessions have accumulated.

    The alternative -- downloading the outcome now -- would be worse in a way
    that is easy to miss. It silently changes what is being measured from "what
    the tool saw and what then happened" to "what the tool saw and what today's
    revised, split-adjusted, survivorship-filtered data says happened". Using
    only stored prices keeps the archive a record rather than a reconstruction.
    """
    owned = conn is None
    conn = conn or connect()
    try:
        rows = conn.execute(
            "SELECT o.symbol, s.session, o.quadrant, o.divergence, o.price, "
            "       o.price_z, o.money_z, o.talk_z, o.rel_1m, "
            "       o.positioning_conflict, s.regime "
            "FROM observation o JOIN snapshot s ON s.id = o.snapshot_id "
            "WHERE o.price > 0 ORDER BY o.symbol, s.session").fetchall()

        by_symbol: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            by_symbol.setdefault(row["symbol"], []).append(row)

        out: list[Outcome] = []
        for symbol, series in by_symbol.items():
            dates = [dt.date.fromisoformat(r["session"]) for r in series]
            for i, row in enumerate(series):
                target = dates[i] + dt.timedelta(days=horizon_days)
                # The first stored session on or after the horizon. Calendar
                # days, not trading days: a horizon that lands on a Saturday
                # should resolve on the Monday rather than not at all.
                later = next((j for j in range(i + 1, len(series))
                              if dates[j] >= target), None)
                if later is None:
                    continue
                entry, exit_ = row["price"], series[later]["price"]
                if entry <= 0 or exit_ <= 0:
                    continue
                out.append(Outcome(
                    symbol=symbol, session=row["session"], quadrant=row["quadrant"],
                    divergence=row["divergence"], horizon_days=horizon_days,
                    entry_price=entry, later_price=exit_,
                    forward_return=exit_ / entry - 1.0,
                    factors={
                        "divergence": row["divergence"],
                        "price_z": row["price_z"],
                        "money_z": row["money_z"],
                        "talk_z": row["talk_z"],
                        "rel_1m": row["rel_1m"],
                        "positioning_conflict": row["positioning_conflict"],
                        "regime": row["regime"],
                    }))
        return out
    finally:
        if owned:
            conn.close()


@dataclass(frozen=True)
class QuadrantScore:
    """How one quadrant's names behaved, against the rest of the universe."""

    quadrant: str
    n: int
    mean_return: float
    median_return: float
    hit_rate: float
    #: Mean return of everything NOT in this quadrant over the same sessions.
    #: The comparison that stops a bull market being mistaken for a signal:
    #: every quadrant looks good when everything went up.
    baseline: float

    @property
    def edge(self) -> float:
        return self.mean_return - self.baseline


def score_quadrants(outcomes: Iterable[Outcome], min_n: int = 20
                    ) -> tuple[list[QuadrantScore], list[str]]:
    """Group outcomes by quadrant, and say plainly when there are too few.

    Returns the scores and a list of reasons not to believe them. The reasons
    are not decoration: this archive grows one row per name per day, so the
    honest answer for the first several months is that there is not enough of it.
    """
    import statistics

    outcomes = list(outcomes)
    reasons: list[str] = []
    if not outcomes:
        return [], ["nothing has resolved yet — the archive needs more sessions."]

    everything = statistics.fmean(o.forward_return for o in outcomes)
    grouped: dict[str, list[Outcome]] = {}
    for outcome in outcomes:
        grouped.setdefault(outcome.quadrant, []).append(outcome)

    scores = []
    for quadrant, members in grouped.items():
        returns = [o.forward_return for o in members]
        others = [o.forward_return for o in outcomes if o.quadrant != quadrant]
        scores.append(QuadrantScore(
            quadrant=quadrant, n=len(members),
            mean_return=statistics.fmean(returns),
            median_return=statistics.median(returns),
            hit_rate=sum(1 for r in returns if r > 0) / len(returns),
            baseline=statistics.fmean(others) if others else everything))
    scores.sort(key=lambda s: -s.edge)

    thin = [s.quadrant for s in scores if s.n < min_n]
    if thin:
        reasons.append(
            f"{', '.join(thin)} have fewer than {min_n} resolved observations. "
            "Those rows are arithmetic, not evidence.")
    sessions_seen = len({o.session for o in outcomes})
    if sessions_seen < 30:
        reasons.append(
            f"only {sessions_seen} distinct sessions have resolved. Every name "
            "on the same day shares a market, so this is closer to "
            f"{sessions_seen} independent observations than to {len(outcomes)}.")
    if everything > 0.01:
        reasons.append(
            f"the whole universe averaged {everything:+.1%} over this horizon. "
            "In a rising market every quadrant looks predictive; read the edge "
            "column, which subtracts it, and not the mean.")
    return scores, reasons


__all__ = ["Observation", "Outcome", "QuadrantScore", "SCHEMA", "connect",
           "db_path", "history", "resolve", "save", "score_quadrants",
           "sessions", "snapshot"]

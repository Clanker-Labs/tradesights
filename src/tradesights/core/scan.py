"""Turn three raw layers into one ranked list.

The only interesting decision in here is the z-scoring, and it is the reason the
tool works at all.

A raw skew of 0.04 is meaningless on its own. It is not high or low; it is high
or low *for that name, on that day, against the other names you could be looking
at instead*. A utility and a biotech do not share a scale, and neither do a
sleepy Tuesday and the morning after a CPI print. Scoring every layer against
the universe scanned in the same run makes those comparable, and makes the
output answer the only question a person actually has in the morning: of
everything I could look at, what is most out of line.

The cost is that the list is always relative. There is no absolute "nothing is
happening today" reading -- if the whole market is calm, the calmest names still
rank. The digest says so rather than pretending the top name is urgent.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass

from tradesights.core.model import QUADRANT_SHORT, Quadrant, Signals
from tradesights.ingest.market import MoneyLayer, PriceLayer

logger = logging.getLogger(__name__)

#: Fewer names than this and a z-score is arithmetic rather than information --
#: with four names the "most divergent" is just the biggest of four numbers.
MIN_UNIVERSE = 8


@dataclass(frozen=True)
class Row:
    """One name, scored, with everything the digest needs to explain itself."""

    symbol: str
    signals: Signals
    rel_1m: float
    quadrant: Quadrant
    divergence: float
    positioning_conflict: float
    talk_source: str | None
    mentions: int | None

    @property
    def headline(self) -> str:
        """The single line a person reads. No jargon, no greeks."""
        move = f"up {self.rel_1m:.0%}" if self.rel_1m > 0 else f"down {abs(self.rel_1m):.0%}"
        return f"{self.symbol}  {move} vs the market, {QUADRANT_SHORT[self.quadrant]}"

    @property
    def notes(self) -> list[str]:
        """The extra things worth saying, when there is anything."""
        out = []
        split = self.signals.talk_money_split
        if split:
            out.append(split)
        # Reported whenever it is large, because it is a different kind of
        # disagreement from the one the ranking is about: not price against
        # positioning, but the options market against itself.
        if self.positioning_conflict > 1.5:
            out.append("options market split — protection is being paid for while calls trade")
        if self.mentions is not None and self.mentions < 8:
            out.append(f"thinly discussed ({self.mentions} mentions) — the talk read is weak")
        return out


def _z(values: dict[str, float]) -> dict[str, float]:
    """Z-score a mapping, tolerating the degenerate cases.

    A universe where every value is identical has no spread to divide by. That
    happens for real -- every name in a sector moving together on an index day
    -- and it means "nothing distinguishes these", so every score is zero rather
    than an exception.
    """
    if len(values) < 2:
        return dict.fromkeys(values, 0.0)
    xs = list(values.values())
    mean = statistics.fmean(xs)
    sd = statistics.pstdev(xs)
    if sd == 0:
        return dict.fromkeys(values, 0.0)
    return {k: (v - mean) / sd for k, v in values.items()}


def build_rows(
    prices: dict[str, PriceLayer],
    money: dict[str, MoneyLayer],
    talk: dict[str, object] | None = None,
) -> list[Row]:
    """Score and rank. Most divergent first.

    A name needs BOTH price and options to be ranked at all. Talk is optional
    and its absence is carried through as None rather than filled in -- see
    core.model.Signals.
    """
    talk = talk or {}
    common = sorted(set(prices) & set(money))
    if len(common) < MIN_UNIVERSE:
        logger.warning(
            "only %d names have both price and options data (need %d) — "
            "z-scores would be arithmetic rather than information",
            len(common), MIN_UNIVERSE,
        )

    price_z = _z({s: prices[s].rel_1m for s in common})
    money_z = _z({s: money[s].bullishness for s in common})

    measured = {s: t for s, t in talk.items() if s in common and t is not None}
    talk_z = _z({s: getattr(t, "sentiment", 0.0) for s, t in measured.items()})

    rows: list[Row] = []
    for sym in common:
        sig = Signals(
            symbol=sym,
            price_z=price_z[sym],
            money_z=money_z[sym],
            talk_z=talk_z.get(sym),          # None when unmeasured, by design
        )
        t = measured.get(sym)
        rows.append(Row(
            symbol=sym,
            signals=sig,
            rel_1m=prices[sym].rel_1m,
            quadrant=sig.quadrant(),
            divergence=sig.divergence,
            positioning_conflict=money[sym].positioning_conflict,
            talk_source=getattr(t, "source", None),
            mentions=getattr(t, "mentions", None),
        ))

    rows.sort(key=lambda r: r.divergence, reverse=True)
    return rows


def interesting(rows: list[Row], limit: int = 5) -> list[Row]:
    """The ones worth putting in a message.

    Quiet names are dropped even when they rank, because a name whose price and
    positioning agree is exactly what this tool is built to ignore. If that
    leaves nothing, it leaves nothing -- a morning with no divergence is a real
    answer and padding the list to five would teach the reader that the list is
    always five long and therefore means nothing.
    """
    return [r for r in rows if r.quadrant is not Quadrant.QUIET][:limit]


__all__ = ["MIN_UNIVERSE", "Row", "build_rows", "interesting"]

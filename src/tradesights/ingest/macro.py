"""The regime. Not a signal -- the weather the signals happen in.

A stock diverging from its options market means something different when the
ten-year is at 4.7% than when it is at 2%, and a defensive rotation during a
growth scare is a different event from the same rotation during a rate scare.
So macro is reported at the top of the digest and used to decide which
divergences are worth mentioning first. It is never scored per name, because
"the ten-year moved" is not a fact about NVDA.

FRED, because it is free, official, has no rate limit worth worrying about, and
the account already has a key.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

FRED = "https://api.stlouisfed.org/fred/series/observations"

#: The smallest set that describes a regime. Every one of these changes what a
#: divergence means; anything else was decoration.
SERIES = {
    "DGS10": "10-year Treasury",
    "DGS2": "2-year Treasury",
    "T10Y2Y": "10y minus 2y",
    "VIXCLS": "VIX",
    "DFF": "Fed funds",
}


@dataclass(frozen=True)
class Reading:
    series: str
    label: str
    value: float
    change_1m: float | None
    date: str


def fetch_regime(api_key: str | None = None) -> list[Reading]:
    """Current level and one-month change for each series.

    Returns whatever it could get. A missing series is dropped rather than
    faked, and an empty list means the digest prints its market section without
    a regime line instead of not printing at all -- FRED being down is not a
    reason to skip the part of the report that came from somewhere else.
    """
    import httpx

    key = api_key or os.environ.get("FRED_API_KEY", "")
    if not key:
        logger.info("no FRED_API_KEY — the regime line will be omitted")
        return []

    out: list[Reading] = []
    with httpx.Client(timeout=20) as client:
        for series, label in SERIES.items():
            try:
                r = client.get(FRED, params={
                    "series_id": series, "api_key": key, "file_type": "json",
                    "limit": 30, "sort_order": "desc",
                })
                r.raise_for_status()
                obs = [o for o in r.json().get("observations", [])
                       if o.get("value") not in (".", None, "")]
            except Exception:  # noqa: BLE001 - one bad series must not lose the rest
                logger.info("FRED: could not read %s", series, exc_info=True)
                continue
            if not obs:
                continue
            latest = float(obs[0]["value"])
            month_ago = float(obs[-1]["value"]) if len(obs) > 20 else None
            out.append(Reading(
                series=series, label=label, value=latest,
                change_1m=(latest - month_ago) if month_ago is not None else None,
                date=obs[0]["date"],
            ))
    return out


def describe(readings: list[Reading]) -> str:
    """One line a person can read without knowing what T10Y2Y is.

    The digest gets one line for macro, not a table. Anyone who wants the table
    can ask for it; everyone else needs to know whether today is a day to trust
    a rally.
    """
    if not readings:
        return "regime unknown — no macro data"

    by = {r.series: r for r in readings}
    bits = []

    if "DGS10" in by:
        r = by["DGS10"]
        if r.change_1m is None:
            arrow = ""
        else:
            arrow = " ▲" if r.change_1m > 0.1 else " ▼" if r.change_1m < -0.1 else " flat"
        bits.append(f"10y {r.value:.2f}%{arrow}")

    if "T10Y2Y" in by:
        spread = by["T10Y2Y"].value
        # An inverted curve is the one macro fact worth saying in words rather
        # than a number, because it is the one most readers will not decode.
        bits.append("curve inverted" if spread < 0 else f"curve +{spread:.2f}")

    if "VIXCLS" in by:
        v = by["VIXCLS"].value
        mood = "calm" if v < 16 else "twitchy" if v < 24 else "stressed"
        bits.append(f"VIX {v:.1f} ({mood})")

    return " · ".join(bits)


__all__ = ["SERIES", "Reading", "describe", "fetch_regime"]

"""Price and options, both from Yahoo.

Kept in one module because they share a session and a symbol list, and because
splitting them would mean two places that each have to decide what a missing
name means.

## On the data source

`yfinance` is scraped, not licensed. It breaks without warning, it rate-limits
without saying so, and nobody owes us a fix. That is an acceptable trade for a
personal screener and it is not acceptable to pretend otherwise, so every
function here returns None on failure rather than a plausible zero. A morning
where Yahoo is unhappy should produce a shorter list, never a wrong one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: Below this many strikes in the moneyness window there is no average worth
#: taking, and a name with four contracts will happily produce a dramatic
#: number.
MIN_CONTRACTS = 6

#: Below this, the CALL/PUT VOLUME RATIO is noise -- forty contracts split
#: 30/10 is not a sentiment reading, it is three trades.
#:
#: It is deliberately NOT a floor on the whole name. Skew is a standing price
#: and stays meaningful when barely anything trades; the volume ratio is the
#: only half that degrades. Treating the floor as all-or-nothing silently
#: dropped three of the eleven sector ETFs from the rotation table -- XLY on 44
#: contracts, XLC on 89, XLRE on 107 -- and a rotation view missing three
#: sectors does not look broken, it looks like those sectors are fine.
MIN_VOLUME_FOR_RATIO = 200


@dataclass(frozen=True)
class PriceLayer:
    symbol: str
    ret_1m: float          # total return over ~1 month
    rel_1m: float          # that return minus the benchmark's
    avg_volume: float
    #: The close this reading was taken against.
    #:
    #: Carried so a stored snapshot can be scored later. Without it a saved scan
    #: records only that a name looked stretched, never whether it then went
    #: anywhere -- which is the only question that would make the archive worth
    #: keeping. Zero when the download did not give one.
    last: float = 0.0


@dataclass(frozen=True)
class MoneyLayer:
    """What the options market is being paid to believe.

    `skew` is mean OTM put IV minus mean OTM call IV. Positive means puts are
    the expensive side -- the market is paying up for downside. It is inverted
    into `bullishness` below so that, like every other layer here, more positive
    means more bullish; a scoring model where one input runs backwards is a
    model somebody eventually reads the wrong way round.
    """

    symbol: str
    skew: float                # + = puts expensive = fear
    call_put_volume: float     # > 1 = more call volume than put
    contracts: int
    #: False when too little traded for the ratio to mean anything. The name is
    #: still scored -- on skew alone -- rather than discarded.
    volume_reliable: bool = True

    @property
    def priced(self) -> float:
        """What protection COSTS. Positive when calls are the expensive side.

        Slow. Survives a quiet session, because it is a standing price rather
        than a day's activity.
        """
        return -self.skew * 10          # skew is small; bring it to a comparable scale

    @property
    def traded(self) -> float:
        """What actually CHANGED HANDS today. Positive when calls dominate.

        Logged, so twice the call volume and half the call volume come out equal
        and opposite instead of 2.0 against 0.5.
        """
        import math

        return math.log(max(self.call_put_volume, 0.01))

    @property
    def bullishness(self) -> float:
        """One number, positive when the options market leans bullish.

        Falls back to the priced half alone when volume was too thin to trust,
        rather than averaging a real number with a meaningless one.
        """
        if not self.volume_reliable:
            return self.priced
        return (self.priced + self.traded) / 2

    @property
    def positioning_conflict(self) -> float:  # noqa: D401
        """How far the two halves of the options signal disagree with EACH OTHER.

        Found by looking at real output rather than by reasoning: PFE came back
        up 12% against SPY with the most expensive puts in the sample AND six
        times more call volume than put. Protection was being paid for while
        calls were being bought hand over fist.

        Averaging those gave a mild bullish number and the name looked ordinary.
        For a tool whose entire premise is that disagreement is the signal,
        collapsing a disagreement into its mean is exactly the wrong move -- so
        the gap is kept and reported. It usually means the people buying calls
        and the people buying protection are not the same people, which is worth
        a look even though it says nothing about direction.
        """
        if not self.volume_reliable:
            return 0.0      # nothing to disagree with
        return abs(self.priced - self.traded)


def fetch_prices(symbols: list[str], benchmark: str = "SPY") -> dict[str, PriceLayer]:
    """One month of relative performance for each symbol.

    Relative to a benchmark rather than absolute, because "down 4%" in a week
    the whole market fell 5% is not a name that went down -- and the point of
    the tool is to find names doing something the market is not.
    """
    import yfinance as yf

    wanted = list(dict.fromkeys([*symbols, benchmark]))
    try:
        raw = yf.download(wanted, period="2mo", interval="1d",
                          progress=False, auto_adjust=True, threads=True)
    except Exception:  # noqa: BLE001 - the source is scraped; any failure is possible
        logger.warning("price download failed entirely", exc_info=True)
        return {}

    if raw is None or raw.empty:
        logger.warning("price download returned nothing")
        return {}

    # Explicit rather than raw.get(...): yfinance returns a MultiIndex frame for
    # several symbols and a flat one for a single symbol, and membership on a
    # MultiIndex tests the outer level. .get would be the same call by luck
    # rather than by contract, on the path where every number comes from.
    closes = raw["Close"] if "Close" in raw else raw  # noqa: SIM401
    volumes = raw["Volume"] if "Volume" in raw else None  # noqa: SIM401

    def last_close(sym: str) -> float:
        if sym not in closes:
            return 0.0
        series = closes[sym].dropna()
        return float(series.iloc[-1]) if len(series) else 0.0

    def total_return(sym: str) -> float | None:
        if sym not in closes:
            return None
        series = closes[sym].dropna()
        # ~21 trading days. Too few rows means a recent listing or a bad pull;
        # either way there is no one-month return to report.
        if len(series) < 22:
            return None
        return float(series.iloc[-1] / series.iloc[-22] - 1.0)

    bench = total_return(benchmark)
    if bench is None:
        logger.warning("benchmark %s has no usable history — cannot compute relatives", benchmark)
        return {}

    out: dict[str, PriceLayer] = {}
    for sym in symbols:
        ret = total_return(sym)
        if ret is None:
            continue
        avg_vol = 0.0
        if volumes is not None and sym in volumes:
            avg_vol = float(volumes[sym].dropna().tail(21).mean() or 0.0)
        out[sym] = PriceLayer(symbol=sym, ret_1m=ret, rel_1m=ret - bench,
                              avg_volume=avg_vol, last=last_close(sym))
    return out


def fetch_options(symbol: str, horizon_days: int = 30) -> MoneyLayer | None:
    """Skew and call/put volume for the expiry nearest `horizon_days` out.

    One expiry, not the whole surface. The front week is dominated by whatever
    happens this Friday and the far months barely trade; a single expiry about a
    month out is the part of the chain where there is enough volume to mean
    something and enough time for a view to be expressed.

    Returns None -- never a zero -- when the chain is missing or too thin. A
    name we could not measure must not enter the ranking as a name that measured
    neutral.
    """
    import datetime as dt

    import yfinance as yf

    try:
        ticker = yf.Ticker(symbol)
        expiries = ticker.options
        if not expiries:
            return None

        today = dt.date.today()
        target = today + dt.timedelta(days=horizon_days)
        expiry = min(expiries, key=lambda e: abs(dt.date.fromisoformat(e) - target))
        chain = ticker.option_chain(expiry)

        spot = None
        try:
            spot = ticker.fast_info.get("lastPrice")
        except Exception:  # noqa: BLE001
            spot = None
        if not spot:
            hist = ticker.history(period="1d")
            if hist.empty:
                return None
            spot = float(hist["Close"].iloc[-1])
        spot = float(spot)
    except Exception:  # noqa: BLE001
        logger.info("no option chain for %s", symbol, exc_info=True)
        return None

    calls, puts = chain.calls, chain.puts
    # A band either side of spot, rather than a single strike. Picking "the 25
    # delta" from a scraped chain means trusting a greek we did not compute; a
    # symmetric moneyness window needs only the strike, which is a fact.
    otm_calls = calls[(calls.strike > spot * 1.02) & (calls.strike < spot * 1.12)]
    otm_puts = puts[(puts.strike < spot * 0.98) & (puts.strike > spot * 0.88)]

    if len(otm_calls) < MIN_CONTRACTS // 2 or len(otm_puts) < MIN_CONTRACTS // 2:
        return None

    call_iv = float(otm_calls.impliedVolatility.mean())
    put_iv = float(otm_puts.impliedVolatility.mean())
    if not (call_iv > 0 and put_iv > 0):
        return None

    call_vol = float(calls.volume.fillna(0).sum())
    put_vol = float(puts.volume.fillna(0).sum())

    return MoneyLayer(
        symbol=symbol,
        skew=put_iv - call_iv,
        # +1 each side so a day with zero puts traded is a high ratio rather
        # than a division by zero.
        call_put_volume=(call_vol + 1) / (put_vol + 1),
        contracts=len(otm_calls) + len(otm_puts),
        volume_reliable=(call_vol + put_vol) >= MIN_VOLUME_FOR_RATIO,
    )


__all__ = ["MIN_CONTRACTS", "MIN_VOLUME_FOR_RATIO", "MoneyLayer", "PriceLayer",
           "fetch_options", "fetch_prices"]

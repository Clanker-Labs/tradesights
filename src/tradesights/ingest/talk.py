"""What people are SAYING, as opposed to what they paid for.

The cheapest layer, in both senses. Anyone can post; nobody clears a trade to do
it. That is exactly why it is interesting next to the options market and exactly
why it counts for half as much in the score.

Two sources behind one interface:

* **X**, via twitterapi.io, which is what the account has a key for. It is the
  layer the tool was actually designed around -- the question "is the timeline
  aligned with where the money is going" needs the timeline.
* **News headlines**, via NewsAPI, as the stand-in.

The interface exists because at the time of writing the X key returns
``402 Credits is not enough``. The layer is wired, it is tested, and it is inert
until somebody tops it up. Rather than leave the tool without a talk layer for
that reason, news fills the slot -- it is a worse proxy for crowd mood, being
written by outlets rather than by the crowd, and it is a real one.

Whatever the source, a name that could not be measured returns None, never a
neutral zero. See the note in core.model on why that distinction is load-bearing.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: Enough to swing a mood, small enough to be honest about. Below this the
#: "sentiment" is one person having a day.
MIN_MENTIONS = 5

_POSITIVE = {
    "beat", "beats", "surge", "surges", "rally", "rallies", "upgrade", "upgraded",
    "record", "strong", "soar", "soars", "jump", "jumps", "gain", "gains",
    "outperform", "bullish", "buy", "raises", "raised", "growth", "wins", "approval",
}
_NEGATIVE = {
    "miss", "misses", "plunge", "plunges", "fall", "falls", "downgrade", "downgraded",
    "weak", "slump", "slumps", "drop", "drops", "loss", "losses", "cut", "cuts",
    "underperform", "bearish", "sell", "lawsuit", "probe", "recall", "warning", "halt",
}


@dataclass(frozen=True)
class TalkLayer:
    symbol: str
    mentions: int
    sentiment: float      # -1 .. +1
    source: str


def _score(texts: list[str]) -> float:
    """Lexicon sentiment, and no apology for it.

    A transformer would be more accurate on any single headline and would not
    change a ranking built from z-scores across a universe. What matters here is
    the RELATIVE mood of one name against the others scanned this morning, and
    for that a word list is enough. It also has the property of being auditable:
    when a name is flagged as loud and bullish, you can see which words did it.
    """
    if not texts:
        return 0.0
    total = 0
    for text in texts:
        words = set(text.lower().replace(",", " ").replace(".", " ").split())
        total += len(words & _POSITIVE) - len(words & _NEGATIVE)
    return max(-1.0, min(1.0, total / (len(texts) * 2)))


def fetch_x(symbol: str, api_key: str | None = None) -> TalkLayer | None:
    """Recent cashtag mentions on X.

    Returns None on any failure, INCLUDING the out-of-credit 402, because a
    layer we could not read is not a layer that read neutral.
    """
    import httpx

    key = api_key or os.environ.get("TWITTERAPI_API_KEY", "")
    if not key:
        return None
    try:
        r = httpx.get(
            "https://api.twitterapi.io/twitter/tweet/advanced_search",
            params={"query": f"${symbol} lang:en", "queryType": "Latest"},
            headers={"X-API-Key": key}, timeout=20,
        )
        if r.status_code == 402:
            logger.warning("X layer is out of credits — "
                           "talk will be measured from news instead")
            return None
        r.raise_for_status()
        tweets = r.json().get("tweets") or []
    except Exception:  # noqa: BLE001
        logger.info("X: could not read %s", symbol, exc_info=True)
        return None

    texts = [t.get("text", "") for t in tweets if t.get("text")]
    if len(texts) < MIN_MENTIONS:
        return None
    return TalkLayer(symbol=symbol, mentions=len(texts), sentiment=_score(texts), source="x")


def fetch_news(
    symbol: str, company: str | None = None, api_key: str | None = None
) -> TalkLayer | None:
    """Recent headlines, as the stand-in for X."""
    import httpx

    key = api_key or os.environ.get("NEWSAPI_API_KEY", "")
    if not key:
        return None
    try:
        r = httpx.get(
            "https://newsapi.org/v2/everything",
            params={"q": company or symbol, "language": "en", "sortBy": "publishedAt",
                    "pageSize": 30, "searchIn": "title"},
            headers={"X-Api-Key": key}, timeout=20,
        )
        r.raise_for_status()
        articles = r.json().get("articles") or []
    except Exception:  # noqa: BLE001
        logger.info("news: could not read %s", symbol, exc_info=True)
        return None

    titles = [a.get("title", "") for a in articles if a.get("title")]
    if len(titles) < MIN_MENTIONS:
        return None
    return TalkLayer(symbol=symbol, mentions=len(titles), sentiment=_score(titles), source="news")


def fetch_talk(symbol: str, company: str | None = None) -> TalkLayer | None:
    """X when it is paid for, news when it is not, None when neither answers."""
    return fetch_x(symbol) or fetch_news(symbol, company)


__all__ = ["MIN_MENTIONS", "TalkLayer", "fetch_news", "fetch_talk", "fetch_x"]

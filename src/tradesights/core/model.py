"""The one idea this whole tool is built on.

Three things can be known about a stock, and they are not equally expensive to
say:

* **Price** is what already happened. It is a fact and it is free.
* **Talk** is what people say will happen. Also free, which is the problem.
* **Money** is what somebody paid to be right about. Options cost real money,
  and a trader who buys protection on a stock they are long is telling you
  something they would not say out loud.

When all three agree there is nothing here. The move happened, the crowd
noticed, the positioning confirms it, and by the time you can see that pattern
it is priced. The edge — such as it is — lives in the disagreement: the name
that ripped while somebody quietly bought puts, or the one everybody is
shouting about that no options desk will fund.

This module scores that disagreement. It does not predict anything, and every
name it surfaces is a question rather than an answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Quadrant(StrEnum):
    """Where a name sits once price and options positioning are crossed.

    The four names come from the video that prompted this tool and are kept
    because they are better than anything more precise would be: they describe
    the human situation rather than the arithmetic, and the whole point is that
    somebody who does not read options can act on them.
    """

    CONTRARIAN_BID = "contrarian_bid"   # price down, calls bid — paying for a bounce
    FEAR = "fear"                       # price down, puts bid — the drop is believed
    CHASE = "chase"                     # price up, calls bid — confirmed, and crowded
    HEDGED_RALLY = "hedged_rally"       # price up, puts bid — nervous holders
    QUIET = "quiet"                     # nothing is stretched enough to name


#: What each quadrant means, in the words a person would use. These strings are
#: user-facing: they go in the Telegram digest and on the web page, and they are
#: deliberately about what somebody is DOING rather than what the greeks say.
#:
#: Use these when the quadrant stands alone. When the sentence already says
#: which way the price went, use QUADRANT_SHORT instead -- the long form opens
#: by restating the direction, which reads as "down 9% vs the market -- down,
#: but call buyers are stepping in".
QUADRANT_PLAIN: dict[Quadrant, str] = {
    Quadrant.CONTRARIAN_BID:
        "down, but call buyers are stepping in — someone is paying for a bounce",
    Quadrant.FEAR: "down, and put buyers agree — the market believes the drop",
    Quadrant.CHASE: "up, and calls are bid — the trend is confirmed, and crowded",
    Quadrant.HEDGED_RALLY: "up, but protection is being bought — holders are nervous",
    Quadrant.QUIET: "price and positioning agree — nothing to look at",
}


#: The same readings with the leading price direction removed, for sentences
#: that have already said it.
QUADRANT_SHORT: dict[Quadrant, str] = {
    Quadrant.CONTRARIAN_BID: "but call buyers are stepping in — someone is paying for a bounce",
    Quadrant.FEAR: "and put buyers agree — the market believes the drop",
    Quadrant.CHASE: "and calls are bid — confirmed, and crowded",
    Quadrant.HEDGED_RALLY: "but protection is being bought — holders are nervous",
    Quadrant.QUIET: "and positioning agrees — nothing to look at",
}


@dataclass(frozen=True)
class Signals:
    """One name's three layers, already normalised.

    Every field is a z-score against the scanned universe rather than a raw
    number, because the question is never "is this skew high" in the abstract —
    it is "is this skew high compared to everything else I could be looking at
    this morning". A 30% IV means one thing in a utility and another in a
    biotech, and comparing a name to its peers today is the only version of
    that question with an answer.

    `talk` is optional and often None. The X layer needs credits this account
    does not currently have, and a missing signal must never be scored as a
    neutral one -- a name nobody is discussing and a name we could not check
    are different, and collapsing them would invent divergence that is not
    there.
    """

    symbol: str
    price_z: float            # relative return vs the benchmark, z-scored
    money_z: float            # options positioning, z-scored; + = bullish bets
    talk_z: float | None = None   # sentiment, z-scored; None = not measured

    def quadrant(self, deadzone: float = 0.4) -> Quadrant:
        """Which of the four situations this name is in.

        `deadzone` keeps the middle of the distribution unnamed. Without it,
        every name in the universe gets a dramatic label including the ones
        sitting at z = 0.02, and a list where everything is interesting is a
        list where nothing is.
        """
        if abs(self.price_z) < deadzone or abs(self.money_z) < deadzone:
            return Quadrant.QUIET
        if self.price_z < 0:
            return Quadrant.CONTRARIAN_BID if self.money_z > 0 else Quadrant.FEAR
        return Quadrant.CHASE if self.money_z > 0 else Quadrant.HEDGED_RALLY

    @property
    def divergence(self) -> float:
        """How far apart the layers are. Bigger means look harder.

        Price against money is the core distance and always counts. Talk is
        added at half weight when it exists, for the reason the module docstring
        gives: talk is free to produce, so it is weaker evidence than a filled
        options order, and weighting it equally would let a loud enough crowd
        outvote the people actually paying.

        Deliberately unsigned. Direction is what the quadrant is for; this
        answers only "how much do these disagree", which is what the list is
        ranked by.
        """
        gap = abs(self.price_z - self.money_z)
        if self.talk_z is not None:
            gap += 0.5 * abs(self.talk_z - self.money_z)
        return gap

    @property
    def talk_money_split(self) -> str | None:
        """The two situations that need the talk layer to be visible at all.

        Returns None when talk was not measured, rather than a cheerful
        "aligned" -- see the note on `talk` above.
        """
        if self.talk_z is None:
            return None
        if self.talk_z > 0.8 and self.money_z < -0.3:
            return "hype without money"
        if self.money_z > 0.8 and abs(self.talk_z) < 0.3:
            return "money without hype"
        return None


__all__ = ["QUADRANT_PLAIN", "QUADRANT_SHORT", "Quadrant", "Signals"]

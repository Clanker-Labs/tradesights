"""The scoring rules, pinned.

These are the decisions that make the list trustworthy or useless, so they get
tests rather than comments alone.
"""

import pytest

from tradesights.core.model import Quadrant, Signals


def s(price, money, talk=None):
    return Signals(symbol="TEST", price_z=price, money_z=money, talk_z=talk)


@pytest.mark.parametrize(
    "price,money,expected",
    [
        (-1.5,  1.2, Quadrant.CONTRARIAN_BID),  # down, calls bid
        (-1.5, -1.2, Quadrant.FEAR),            # down, puts bid
        ( 1.5,  1.2, Quadrant.CHASE),           # up, calls bid
        ( 1.5, -1.2, Quadrant.HEDGED_RALLY),    # up, puts bid
    ],
)
def test_the_four_situations(price, money, expected):
    assert s(price, money).quadrant() is expected


def test_the_middle_of_the_distribution_stays_unnamed():
    """A list where everything is interesting is a list where nothing is.

    Without a deadzone every name in the universe gets a dramatic label,
    including the ones sitting at z = 0.02, and the reader learns to skim past
    all of them.
    """
    assert s(0.1, 0.1).quadrant() is Quadrant.QUIET
    assert s(0.1, 2.0).quadrant() is Quadrant.QUIET, "one stretched axis is not a situation"
    assert s(2.0, 0.1).quadrant() is Quadrant.QUIET


def test_a_missing_talk_layer_is_not_a_neutral_one():
    """Not measured and measured-as-quiet are different facts.

    The X source needs credits this account does not have, so `talk` is None far
    more often than not. Scoring None as 0.0 would manufacture divergence
    against a signal nobody looked at -- the tool would confidently rank a name
    for disagreeing with silence.
    """
    unmeasured = s(2.0, -2.0)
    measured_quiet = s(2.0, -2.0, talk=0.0)

    assert unmeasured.divergence < measured_quiet.divergence
    assert unmeasured.talk_money_split is None


def test_talk_counts_for_less_than_money():
    """Talk is free to produce. A filled options order is not.

    Weighting them equally would let a loud enough crowd outvote the people
    actually paying, which is the exact failure this tool exists to avoid.
    """
    money_gap = s(2.0, -2.0).divergence               # 4.0 from price vs money
    talk_gap = s(0.0, 0.0, talk=2.0).divergence        # 2.0 of talk, halved

    assert money_gap == pytest.approx(4.0)
    assert talk_gap == pytest.approx(1.0)


def test_divergence_is_unsigned_because_direction_is_the_quadrants_job():
    assert s(2.0, -2.0).divergence == pytest.approx(s(-2.0, 2.0).divergence)


def test_the_two_splits_that_need_the_talk_layer():
    assert s(0.0, -1.0, talk=1.5).talk_money_split == "hype without money"
    assert s(0.0, 1.5, talk=0.1).talk_money_split == "money without hype"
    assert s(0.0, 1.5, talk=1.5).talk_money_split is None, "agreement is not a split"


def test_the_options_signal_keeps_its_own_disagreement():
    """Averaging away an internal conflict is the one thing this tool must not do.

    Found in real output, not in theory: PFE came back up 12% on SPY with the
    most expensive puts in the sample and six times more call volume than put.
    Protection being paid for, calls being bought hand over fist. The blend of
    those is a mild bullish number and the name reads as ordinary.

    Both of these have the same blend. Only one of them is interesting, and a
    tool built on "disagreement is the signal" has to be able to tell them
    apart.
    """
    from tradesights.ingest.market import MoneyLayer

    split = MoneyLayer(symbol="PFE", skew=0.041, call_put_volume=6.18, contracts=9)
    calm = MoneyLayer(symbol="JPM", skew=0.0067, call_put_volume=0.85, contracts=14)

    assert split.positioning_conflict > 2.0
    assert calm.positioning_conflict < 0.2
    assert split.bullishness > 0, "the blend alone calls this an ordinary bullish name"


def test_thin_volume_costs_you_half_the_signal_not_the_whole_name():
    """A rotation table missing three sectors does not look broken.

    It looks like those sectors are fine, which is worse. An all-or-nothing
    volume floor dropped XLY (44 contracts), XLC (89) and XLRE (107) out of the
    eleven-sector view entirely -- and XLRE was showing a contrarian bid nobody
    could see.

    Skew is a standing price and survives a quiet session. Only the call/put
    ratio degrades. So thin volume disables that half and the name is still
    scored on the other.
    """
    from tradesights.ingest.market import MoneyLayer

    thin = MoneyLayer(symbol="XLRE", skew=-0.048, call_put_volume=9.0,
                      contracts=8, volume_reliable=False)

    assert thin.bullishness == pytest.approx(thin.priced), "thin names score on skew alone"
    assert thin.bullishness != pytest.approx((thin.priced + thin.traded) / 2)
    # Nothing trustworthy to disagree with, so no conflict is claimed.
    assert thin.positioning_conflict == 0.0

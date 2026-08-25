# tradesights

**Talk is cheap. Options cost money.** This tool ranks the stocks where those
two stop agreeing.

Every morning it looks at the same three things for every name it covers — what
the price did, what the options market is being paid to believe, and what people
are saying — and puts the biggest disagreements at the top of one list. When all
three agree there is nothing here: the move happened, the crowd noticed, the
positioning confirms it, and you are reading the news. The interesting names are
the ones that rallied while somebody quietly bought protection, or that everyone
is shouting about while no options desk will fund the trade.

It is a screener. It tells you where to look and it does not tell you what to do.

## Why these three layers

**Price is what already happened.** It is a fact, it is free, and by the time a
chart looks obvious it is in the price.

**Options are what somebody paid to be right about.** A trader who is long a
stock and quietly buying puts against it is telling you something they would not
post. That is the signal worth the most, because it cost the person sending it
something.

**Talk is what people say will happen** — free to produce, which is the whole
problem with it. It counts here at half weight, never more, because a loud
enough crowd should not be able to outvote the people actually paying.

Macro is not a fourth signal. It is the weather: a rate-sensitive divergence
reads differently at a 4.7% ten-year than at 2%, so the regime is shown at the
top of the report and used to sort what matters, not scored per name.

## The four situations

Crossing price against positioning puts every name in one of four boxes. The
names are borrowed from [the video that prompted this](#credit) and kept because
they describe what a person is *doing* rather than what the greeks say:

| | price down | price up |
| :--- | :--- | :--- |
| **calls bid** | **Contrarian Bid** — someone is paying for a bounce | **Chase** — trend confirmed, and crowded |
| **puts bid** | **Fear** — the market believes the drop | **Hedged Rally** — holders are nervous |

Adding the talk layer gives two more that price and options alone cannot see:

- **Hype without money** — loud and bullish, with no positioning behind it.
- **Money without hype** — positioning hard, and nobody is discussing it.

## What it is not

**Not a prediction.** Every name it surfaces is a question. The list is ranked by
how far the layers disagree, which is a measure of how *interesting* a name is,
not of which way it goes.

**Not a trading system.** There is no order execution in this repo and no path
from it to a broker, deliberately and permanently. It reads and it reports.

**Not backtested, and carrying no performance claims.** Somebody else's six
months of trades is not evidence a method works, and this README is not going to
tell you a number to make the idea sound better than it is.

## Sharp edges

- **Option chains come from Yahoo via `yfinance`, which is scraped rather than
  licensed.** It breaks without warning and has no support contract. The tool
  reports a missing chain as missing rather than guessing around it, but a
  morning where Yahoo is unhappy is a morning with a shorter list.
- **Implied-volatility skew is a crude proxy for positioning.** It cannot see
  who is on which side of a trade, or whether a put was bought as a hedge or
  sold for income. It is directionally useful and it is not order flow.
- **The X layer needs credits.** Without them the talk layer is absent, and
  absent is scored as absent — never as neutral. A name nobody discussed and a
  name nobody checked are different facts, and treating them the same would
  invent divergence that is not there.
- **Thin names produce nonsense.** A stock with four option contracts and no
  volume will happily generate a dramatic skew. There is a liquidity floor and
  names below it are dropped rather than ranked.

## Credit

The core idea — pull price and options positioning for every name, and pay
attention where they disagree — is from
[@berttrading](https://www.instagram.com/reel/DcRZLiegCdz/), including the four
quadrant names. The social layer, the macro regime, the plain-English digest and
everything in this repo are ours.

## Licence

MIT.

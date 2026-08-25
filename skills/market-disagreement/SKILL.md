---
name: market-disagreement
description: Read the market the way tradesights does — price against options positioning against talk, ranked by disagreement. Use when asked about the market this morning, where money is rotating, whether a rally is trusted, or what the options market thinks of a specific ticker. Not for placing trades; this only ever says where to look.
---

# Reading the market by what disagrees

Three things can be known about a stock, and they do not cost the same to say.

**Price** is what already happened. Free, factual, and by the time a chart looks
obvious it is in the price.

**Options** are what somebody paid to be right about. Someone long a stock who
quietly buys puts against it is telling you something they would not post.

**Talk** is what people say will happen. Free to produce, which is the whole
problem with it.

When all three agree there is nothing here. The move happened, the crowd
noticed, positioning confirms it, and you are reading the news. **The interesting
names are where they disagree** — the stock that ripped while somebody bought
protection, or the one everyone is shouting about that no options desk will fund.

## How to answer

Run the tools rather than reasoning about the market from memory. Prices move
and your training data does not.

| they ask | run |
| :--- | :--- |
| "how's the market", "anything interesting" | `tradesights_digest` |
| "where is money going", "what's rotating" | `tradesights_rotation` |
| "what about NVDA" | `tradesights_name` |

`tradesights_digest` returns a ready-to-post `message`. **Post it as written.**
It was composed to be read on a phone at seven in the morning; rewriting it in
your own words reliably makes it longer, and the numbers are exact.

## The four situations

Crossing price against positioning puts a name in one of four boxes:

- **Contrarian Bid** — down, but calls are bid. Someone is paying for a bounce.
- **Fear** — down, and puts agree. The market believes the drop.
- **Chase** — up, and calls are bid. Confirmed, and crowded.
- **Hedged Rally** — up, but protection is being bought. Holders are nervous.

Two more come from the talk layer:

- **Hype without money** — loud and bullish, nothing behind it.
- **Money without hype** — positioning hard, nobody discussing it. The most
  interesting of the six, and the rarest.

## Rules

**Say where to look, never what to do.** Every name is a question. "UBER is up
14% and holders are hedging" is the finding. "Sell UBER" is not something this
data supports and not something to say.

**Never predict.** The ranking measures how far the layers disagree, which is a
measure of how *interesting* a name is, not of which way it goes.

**A missing layer is missing, not neutral.** When `talk` comes back null the
layer was not read — usually because the X source is out of credits. Say "not
measured". Never describe it as quiet, balanced, or neutral; a name nobody
discussed and a name nobody checked are different facts.

**Do not compute your own signals.** If a tool returns null for options, that
name has no usable chain. Do not substitute a guess from memory, and do not
reason about implied volatility you have not been given.

**Never touch the broker.** There is a separate app in this ecosystem that can
place real orders. It has nothing to do with this skill, and no request that
starts with a tradesights reading should end at it.

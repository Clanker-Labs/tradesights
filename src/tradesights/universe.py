"""What to scan.

Two defaults, because there are two different questions.

`SECTORS` is the eleven S&P sector ETFs. Scanning those answers "where is money
rotating" in one cheap pass -- eleven liquid names with deep option chains, and
the answer is the top line of the morning digest.

`LIQUID` is a hand-picked large-cap list. It exists because the alternative --
scanning the whole market -- is both slow against a scraped data source and
worse: a screener that ranks illiquid names by option skew produces confident
nonsense, and the liquidity floor in the ingest layer would drop most of them
anyway. Better to scan names that can support the analysis than to filter a
thousand and pretend the survivors were chosen.

Point it at your own list any time. This is a starting universe, not a claim
about what matters.
"""

SECTORS = {
    "XLK": "Info Tech", "XLV": "Health Care", "XLF": "Financials",
    "XLY": "Cons Disc", "XLP": "Staples", "XLE": "Energy",
    "XLI": "Industrials", "XLB": "Materials", "XLRE": "Real Estate",
    "XLU": "Utilities", "XLC": "Comm Svcs",
}

LIQUID = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "NFLX",
    "JPM", "BAC", "GS", "V", "MA", "BRK-B",
    "XOM", "CVX", "COP",
    "UNH", "JNJ", "LLY", "PFE", "MRK",
    "WMT", "COST", "HD", "MCD", "NKE",
    "CAT", "BA", "GE", "UPS",
    "DIS", "CRM", "ORCL", "INTC", "MU", "QCOM", "PLTR", "COIN", "UBER", "RDDT",
]

__all__ = ["LIQUID", "SECTORS"]

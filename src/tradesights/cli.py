"""The command line. Three verbs, because there are three questions.

    tradesights rotation   where is money moving, by sector
    tradesights scan       which names disagree with themselves
    tradesights name NVDA  everything known about one name

Output is a table meant to be read at seven in the morning by somebody who has
not had coffee and does not want to interpret a chart.
"""

from __future__ import annotations

import logging

import typer
from rich.console import Console
from rich.table import Table

from tradesights.core.model import QUADRANT_PLAIN
from tradesights.core.scan import build_rows, interesting
from tradesights.ingest import macro
from tradesights.ingest.market import fetch_options, fetch_prices
from tradesights.ingest.talk import fetch_talk
from tradesights.universe import LIQUID, SECTORS

app = typer.Typer(add_completion=False, help="Where price, positioning and talk stop agreeing.")
console = Console()


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )


def _gather(symbols: list[str], with_talk: bool):
    prices = fetch_prices(symbols)
    money, talk = {}, {}
    with console.status("[dim]reading option chains…"):
        for sym in symbols:
            m = fetch_options(sym)
            if m:
                money[sym] = m
    if with_talk:
        with console.status("[dim]reading the talk layer…"):
            for sym in list(money)[:20]:      # the slow layer; cap it
                t = fetch_talk(sym)
                if t:
                    talk[sym] = t
    return prices, money, talk


@app.command()
def rotation(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    """Where money is moving, by sector."""
    _setup_logging(verbose)
    console.print(f"[dim]{macro.describe(macro.fetch_regime())}[/dim]\n")

    prices, money, _ = _gather(list(SECTORS), with_talk=False)
    rows = build_rows(prices, money)
    if not rows:
        console.print("[yellow]No sector data. Yahoo may be unhappy; try again shortly.[/yellow]")
        raise typer.Exit(1)

    table = Table(title="Sector rotation — 1 month vs SPY", header_style="bold")
    table.add_column("Sector")
    table.add_column("vs SPY", justify="right")
    table.add_column("Positioning", justify="right")
    table.add_column("Reading")
    for r in sorted(rows, key=lambda r: r.rel_1m, reverse=True):
        colour = "green" if r.rel_1m > 0 else "red"
        table.add_row(
            SECTORS.get(r.symbol, r.symbol),
            f"[{colour}]{r.rel_1m:+.1%}[/{colour}]",
            f"{r.signals.money_z:+.2f}",
            QUADRANT_PLAIN[r.quadrant],
        )
    console.print(table)


@app.command()
def scan(
    limit: int = typer.Option(5, "--limit", "-n", help="how many names to show"),
    no_talk: bool = typer.Option(False, "--no-talk", help="skip the social layer (faster)"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """The names where the layers disagree most."""
    _setup_logging(verbose)
    console.print(f"[dim]{macro.describe(macro.fetch_regime())}[/dim]\n")

    prices, money, talk = _gather(LIQUID, with_talk=not no_talk)
    rows = build_rows(prices, money, talk)
    picks = interesting(rows, limit)

    console.print(f"[dim]scanned {len(prices)} names, {len(money)} with usable option chains"
                  f"{f', {len(talk)} with talk' if talk else ''}[/dim]\n")

    if not picks:
        # A real answer, and the reason `interesting` refuses to pad the list.
        console.print("[yellow]Nothing is stretched today — price and positioning agree "
                      "across the board. That is a finding, not a failure.[/yellow]")
        return

    for i, r in enumerate(picks, 1):
        console.print(f"[bold]{i}. {r.headline}[/bold]")
        for note in r.notes:
            console.print(f"   [dim]· {note}[/dim]")
        console.print(f"   [dim]divergence {r.divergence:.2f}[/dim]\n")

    console.print("[dim]This is a screener. Every name above is a question, not a call.[/dim]")


@app.command()
def name(symbol: str, verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    """Everything known about one name."""
    _setup_logging(verbose)
    symbol = symbol.upper()

    prices = fetch_prices([symbol])
    m = fetch_options(symbol)
    t = fetch_talk(symbol)

    if symbol not in prices:
        console.print(f"[red]No price history for {symbol}.[/red]")
        raise typer.Exit(1)

    p = prices[symbol]
    console.print(f"\n[bold]{symbol}[/bold]")
    console.print(f"  price      {p.ret_1m:+.1%} over a month, {p.rel_1m:+.1%} vs SPY")
    if m is None:
        console.print("  options    [yellow]no usable chain — too thin, or Yahoo declined[/yellow]")
    else:
        console.print(f"  options    skew {m.skew:+.4f} · call/put volume {m.call_put_volume:.2f}")
        console.print(f"             priced {m.priced:+.2f} vs traded {m.traded:+.2f}"
                      f"{'  [yellow](split)[/yellow]' if m.positioning_conflict > 1.5 else ''}")
    if t is None:
        console.print("  talk       [yellow]not measured[/yellow]")
    else:
        console.print(f"  talk       {t.sentiment:+.2f} across {t.mentions} {t.source} mentions")
    console.print()


if __name__ == "__main__":
    app()

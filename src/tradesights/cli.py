"""The command line. Three verbs, because there are three questions.

    tradesights rotation   where is money moving, by sector
    tradesights scan       which names disagree with themselves
    tradesights name NVDA  everything known about one name
    tradesights chart      the whole universe, plotted, to see if today is unusual
    tradesights snapshot   write today's scan down, so it can be scored later
    tradesights resolve    did the disagreements go anywhere
    tradesights dashboard  the research view

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
def chart(
    out: str = typer.Option("quadrants.svg", "--out", "-o", help="where to write the SVG"),
    label: int = typer.Option(8, "--label", help="how many names to label"),
    no_talk: bool = typer.Option(True, "--no-talk/--talk", help="skip the social layer"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Plot every scanned name, to answer the question the list cannot.

    The ranked list says what to look at. It cannot say whether today is
    unusual -- five names above a divergence of 2 is either a market coming
    apart or an ordinary Tuesday, and the top of a table looks identical either
    way. Plotting the whole universe shows the difference at a glance: a cloud
    around the origin, or two diagonal wings.
    """
    from pathlib import Path

    from tradesights.chart import quadrant_svg

    _setup_logging(verbose)
    prices, money, talk = _gather(LIQUID, with_talk=not no_talk)
    rows = build_rows(prices, money, talk)
    if not rows:
        console.print("[yellow]Nothing to plot — no name had both price and options.[/]")
        raise typer.Exit(1)

    svg = quadrant_svg(rows, title=f"{len(rows)} names · price against positioning",
                       label_top=label)
    Path(out).write_text(svg)
    spread = {q: sum(1 for r in rows if r.quadrant.value == q)
              for q in {r.quadrant.value for r in rows}}
    console.print(f"[green]{out}[/] — {len(rows)} names")
    console.print("[dim]" + " · ".join(f"{v} {k.replace('_', ' ')}"
                                       for k, v in sorted(spread.items(), key=lambda kv: -kv[1]))
                  + "[/dim]")


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


@app.command()
def snapshot(
    no_talk: bool = typer.Option(True, "--no-talk/--talk"),
    session: str = typer.Option("", help="YYYY-MM-DD. Defaults to today."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Record today's scan, so it can be asked later whether it was right.

    Without an archive this tool produces an opinion every morning and forgets
    it by lunch -- which is enough to decide what to look at and not enough to
    decide whether looking there was ever worth it. Run it from a cron on
    trading days; re-running replaces that session rather than double-counting
    it.
    """
    from tradesights import store

    _setup_logging(verbose)
    prices, money, talk = _gather(LIQUID, with_talk=not no_talk)
    rows = build_rows(prices, money, talk)
    if not rows:
        console.print("[yellow]Nothing to record — no name had both price and "
                      "options.[/] Not written.")
        raise typer.Exit(1)

    regime = macro.describe(macro.fetch_regime())
    snapshot_id = store.save(rows, prices=prices, regime=regime,
                             session=session or None)
    kept = store.sessions(limit=9999)
    console.print(f"[green]recorded[/] {len(rows)} names as snapshot {snapshot_id}")
    console.print(f"[dim]{len(kept)} sessions stored · {store.db_path()}[/dim]")
    if len(kept) < 30:
        console.print(f"[yellow]{len(kept)} sessions is not enough to conclude "
                      "anything.[/] The archive only grows forward — it cannot be "
                      "backfilled without reconstructing history from today's "
                      "revised data, which would confirm whatever you already "
                      "believe.")


@app.command()
def resolve(
    horizon: int = typer.Option(5, "--horizon", help="Calendar days ahead."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Score the archive: when a name looked like this, what happened next."""
    from tradesights import store

    _setup_logging(verbose)
    outcomes = store.resolve(horizon)
    scores, reasons = store.score_quadrants(outcomes)

    if not scores:
        for reason in reasons:
            console.print(f"[yellow]{reason}[/]")
        raise typer.Exit(1)

    table = Table(title=f"{len(outcomes)} observations resolved over {horizon} days",
                  title_justify="left")
    table.add_column("quadrant")
    for column in ("n", "mean", "median", "hit rate", "universe", "edge"):
        table.add_column(column, justify="right")
    for score in scores:
        style = "green" if score.edge > 0 else "red"
        table.add_row(score.quadrant.replace("_", " "), str(score.n),
                      f"{score.mean_return:+.2%}", f"{score.median_return:+.2%}",
                      f"{score.hit_rate:.0%}", f"{score.baseline:+.2%}",
                      f"[{style}]{score.edge:+.2%}[/]")
    console.print(table)
    console.print()
    console.print("[dim]edge = this quadrant's mean minus everything else's over the "
                  "same sessions. Read that column, not the mean: in a rising "
                  "market every quadrant looks predictive.[/dim]")
    if reasons:
        console.print()
        console.print("[bold yellow]Reasons not to believe this yet:[/]")
        for reason in reasons:
            console.print(f"  • {reason}")
    console.print()
    console.print("[dim]A forward return after a signal is not a trade. There is no "
                  "entry rule, no stop, no size and no cost here, and the gap "
                  "between the two is every part of trading that is hard.[/dim]")


@app.command()
def backtest(
    horizon: int = typer.Option(5, "--horizon", help="Calendar days ahead."),
    shuffles: int = typer.Option(200, "--shuffles",
                                 help="Permutations for the filter test."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """What acting on the signals would have meant, and why — with the search
    that finds a filter tested against the same search over shuffled outcomes."""
    from tradesights import store
    from tradesights.core import analytics
    from tradesights.core import backtest as bt

    _setup_logging(verbose)
    board = bt.run(store.resolve(horizon), horizon_days=horizon)
    if not board.n:
        console.print("[yellow]Nothing has resolved into a position at this "
                      "horizon.[/] Chase and quiet are deliberately not trades.")
        raise typer.Exit(1)

    # The headline never ships without its baseline. In a rising market every
    # strategy looks predictive, and the mean alone is how that gets believed.
    console.print(f"\n[bold]{board.n}[/] trades over {horizon} days  "
                  f"[dim]({board.wins}W/{board.losses}L, "
                  f"{board.stood_aside} stood aside)[/]")
    console.print(f"  hit rate      {board.hit_rate:.0%}")
    console.print(f"  mean/trade    {board.mean_return:+.2%}")
    console.print(f"  baseline      {board.baseline_return:+.2%}  "
                  f"[dim]same names, same days, signal ignored[/]")
    style = "green" if board.edge > 0 else "red"
    console.print(f"  edge          [{style}]{board.edge:+.2%}[/]")

    risk = analytics.risk_metrics(board)
    console.print(f"\n[bold]Shape[/]")
    console.print(f"  profit factor {risk.profit_factor:.2f}   "
                  f"payoff {risk.payoff_ratio:.2f}   "
                  f"ret/risk {risk.return_per_unit_risk:.3f}")
    console.print(f"  max drawdown  {risk.max_drawdown:.1%}   "
                  f"worst streak {risk.max_losing_streak}   "
                  f"top trade {risk.top_trade_share:.0%} of profit")

    table = Table(title="What separated the winners", title_justify="left")
    table.add_column("factor")
    for column in ("n", "IC", "separation", "winners", "losers"):
        table.add_column(column, justify="right")
    for f in analytics.factor_reports(board):
        if f.ic is None:
            table.add_row(f.name, str(f.n), "—", "—", "—", "—")
            continue
        table.add_row(f.name, str(f.n), f"{f.ic:+.3f}", f"{f.separation:+.3f}",
                      f"{f.winner_mean:+.2f}", f"{f.loser_mean:+.2f}")
    console.print()
    console.print(table)

    study = analytics.filter_study(board, shuffles=shuffles)
    console.print()
    if study.best is None:
        console.print(f"[yellow]{study.verdict}[/]")
        return
    dead = study.p_value is not None and study.p_value > 0.05
    rule = (f"{study.best.factor} {study.best.op} {study.best.threshold}")
    console.print(f"[bold]Best of {study.tried} thresholds tried:[/] "
                  f"{'[strike]' if dead else '[green]'}{rule}"
                  f"{'[/strike]' if dead else '[/]'}")
    console.print(f"  keeps {study.best.n} trades, hit {study.best.hit_rate:.0%}, "
                  f"mean {study.best.mean_return:+.2%} "
                  f"(lift {study.best.lift:+.2%})")
    console.print(f"  p = {study.p_value:.3f}")
    console.print()
    console.print(f"[{'red' if dead else 'green'}]{study.verdict}[/]")
    console.print()
    console.print("[dim]A forward return after a signal is not a trade. There is "
                  "no entry rule, no stop, no size and no cost here, and the gap "
                  "between the two is every part of trading that is hard.[/dim]")


@app.command()
def sessions(limit: int = typer.Option(20, help="How many to list.")) -> None:
    """What is in the archive."""
    from tradesights import store

    rows = store.sessions(limit=limit)
    if not rows:
        console.print("[yellow]The archive is empty.[/] Run `tradesights snapshot`.")
        raise typer.Exit(1)
    table = Table(title=f"{store.db_path()}", title_justify="left")
    table.add_column("session")
    table.add_column("names", justify="right")
    table.add_column("talk")
    table.add_column("regime")
    for row in rows:
        table.add_row(row["session"], str(row["n"]),
                      "yes" if row["has_talk"] else "—", row["regime"] or "—")
    console.print(table)


@app.command()
def dashboard(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8095),
) -> None:
    """Serve the research dashboard. Loopback by default; it is not authenticated."""
    from tradesights.dashboard.server import serve

    serve(host=host, port=port)


if __name__ == "__main__":
    app()

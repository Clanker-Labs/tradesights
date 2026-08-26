# Running the snapshot on a schedule

The archive is the difference between a tool that has an opinion every morning
and one that can be asked whether the opinions were ever worth anything. It only
grows forward: **a session missed is a session that can never be recovered**,
because option chains are not retrievable after the fact and reconstructing them
from today's data would be a backtest of a screener against its own inputs.

So it wants a timer.

```bash
sudo cp deploy/tradesights-snapshot.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tradesights-snapshot.timer
systemctl list-timers tradesights-snapshot.timer
```

It runs as `jarvis`, not root — recording a scan needs a network connection and
a writable `~/.tradesights`, and nothing else.

Weekdays only, 16:30 New York. Running at the weekend would store Friday's
numbers again under Saturday's date, and the schema's one-snapshot-per-session
rule would not catch it, because Saturday is a different session string. That
would quietly double-weight Friday in every statistic computed later — which is
the worst kind of wrong, since nothing would look broken.

Check what accumulated:

```bash
tradesights sessions
tradesights resolve --horizon 5
```

The honest expectation: `resolve` says nothing useful for months. Thirty
sessions is six trading weeks, and every name on the same day shares a market,
so the effective sample grows far more slowly than the row count suggests.

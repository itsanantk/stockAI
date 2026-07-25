"""End-of-day summary: deterministic stats + the day's AI session summary.

Free to generate (no AI call). Stored in the DB and shown on the dashboard.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from .broker import Broker
from .config import Config

TZ = ZoneInfo("America/Toronto")


def build_daily_summary(broker: Broker, cfg: Config) -> str:
    today = dt.datetime.now(TZ).strftime("%Y-%m-%d")
    perf = broker.performance()

    snaps = [dict(r) for r in broker.db.execute(
        "SELECT * FROM snapshots ORDER BY ts")]
    todays = [s for s in snaps if s["ts"].startswith(today)]
    prior = [s for s in snaps if not s["ts"].startswith(today)]
    prev_equity = prior[-1]["equity"] if prior else broker.starting_cash
    equity_now = perf["equity"]
    day_pnl = equity_now - prev_equity
    day_pct = (equity_now / prev_equity - 1) * 100 if prev_equity else 0.0

    zsp_day = None
    if todays and prior and todays[-1]["bench_sp500_cad"] and prior[-1]["bench_sp500_cad"]:
        zsp_day = (todays[-1]["bench_sp500_cad"] / prior[-1]["bench_sp500_cad"] - 1) * 100

    trades = [dict(r) for r in broker.db.execute(
        "SELECT * FROM trades WHERE ts LIKE ? ORDER BY id", (today + "%",))]

    session_summary = broker.db.execute(
        "SELECT content FROM journal WHERE kind='summary' AND ts LIKE ? ORDER BY id DESC LIMIT 1",
        (today + "%",)).fetchone()

    lines = [f"# Daily summary — {today}", ""]
    lines.append(f"Equity ${equity_now:,.2f}  |  day P&L {day_pnl:+,.2f} ({day_pct:+.2f}%)"
                 + (f"  |  ZSP.TO today {zsp_day:+.2f}%" if zsp_day is not None else ""))
    lines.append(f"Since inception: {perf['return_pct']:+.2f}% vs "
                 f"S&P 500 {perf['benchmarks'].get(cfg.benchmark_sp500_cad, {}).get('return_pct', 0):+.2f}% "
                 f"(alpha {perf.get('alpha_vs_sp500_pct', 0):+.2f}%)  |  cash ${perf['cash']:,.2f}")
    lines.append("")

    if trades:
        lines.append(f"## Trades today ({len(trades)})")
        for t in trades:
            pnl = f"  [realized {t['realized_pnl']:+,.2f}]" if t["realized_pnl"] is not None else ""
            lines.append(f"- {t['side'].upper()} {t['shares']} {t['ticker']} @ {t['price']:.3f}{pnl}")
            if t["reason"]:
                lines.append(f"  - {t['reason'][:300]}")
    else:
        lines.append("## Trades today\n- none")
    lines.append("")

    positions = broker.positions_with_prices()
    if positions:
        lines.append("## Open positions")
        for p in positions:
            if "last" in p:
                lines.append(f"- {p['ticker']}: {p['shares']} sh @ {p['avg_cost']:.2f}, "
                             f"last {p['last']:.2f}, P&L {p['unrealized_pnl']:+,.2f} "
                             f"({p['unrealized_pct']:+.2f}%)")
            else:
                lines.append(f"- {p['ticker']}: {p['shares']} sh @ {p['avg_cost']:.2f}")
    else:
        lines.append("## Open positions\n- none (all cash)")
    pending = broker.pending()
    if pending:
        lines.append("")
        lines.append("## Pending market-on-open orders")
        for o in pending:
            size = f"${o['amount_cad']:,.0f}" if o["amount_cad"] else f"{o['shares']} sh"
            lines.append(f"- {o['side'].upper()} {o['ticker']} {size}")
    lines.append("")

    if session_summary:
        lines.append("## AI session recap")
        lines.append(session_summary["content"])

    content = "\n".join(lines)
    broker.save_daily_summary(today, content)
    return content

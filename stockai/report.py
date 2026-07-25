"""Performance reporting: portfolio vs S&P 500 (CAD) and TSX Composite."""

from __future__ import annotations

import json

from .broker import Broker
from .config import Config


def _fmt_money(x) -> str:
    return f"${x:,.2f}" if x is not None else "-"


def print_portfolio(broker: Broker):
    perf = broker.performance()
    print("=" * 62)
    print(f"  Equity: {_fmt_money(perf['equity'])}   Cash: {_fmt_money(perf['cash'])}   "
          f"Return: {perf['return_pct']:+.2f}%")
    print("=" * 62)
    positions = broker.positions_with_prices()
    if not positions:
        print("  (no open positions)")
    for p in positions:
        if "last" in p:
            print(f"  {p['ticker']:<12} {p['shares']:>6} sh @ {p['avg_cost']:<8.2f} "
                  f"last {p['last']:<8.2f} P&L {p['unrealized_pnl']:>+10.2f} "
                  f"({p['unrealized_pct']:+.2f}%)")
        else:
            print(f"  {p['ticker']:<12} {p['shares']:>6} sh @ {p['avg_cost']:<8.2f} "
                  f"(price unavailable: {p.get('price_error', '?')})")
    pending = broker.pending()
    if pending:
        print("-" * 62)
        print("  Pending market-on-open orders:")
        for o in pending:
            size = f"${o['amount_cad']:,.0f}" if o["amount_cad"] else f"{o['shares']} sh"
            print(f"    {o['side'].upper():<5} {o['ticker']:<12} {size}  (placed {o['created_ts']})")


def print_report(broker: Broker, cfg: Config):
    perf = broker.performance()
    print("\n" + "=" * 62)
    print("  stockAI performance report")
    print("=" * 62)
    print(f"  Starting capital : {_fmt_money(perf['starting_cash'])}")
    print(f"  Current equity   : {_fmt_money(perf['equity'])}")
    print(f"  Total return     : {perf['return_pct']:+.2f}%")
    print("-" * 62)
    for sym, b in perf["benchmarks"].items():
        label = "S&P 500 (CAD, ZSP.TO)" if sym == cfg.benchmark_sp500_cad else "TSX Composite"
        print(f"  {label:<24}: {b['return_pct']:+.2f}%  ({b['inception']:.2f} -> {b['now']:.2f})")
    if "alpha_vs_sp500_pct" in perf:
        verdict = "BEATING" if perf["alpha_vs_sp500_pct"] > 0 else "TRAILING"
        print(f"\n  Alpha vs S&P 500 : {perf['alpha_vs_sp500_pct']:+.2f}%  [{verdict}]")
    print("-" * 62)

    trades = [dict(r) for r in broker.db.execute("SELECT * FROM trades ORDER BY id")]
    sells = [t for t in trades if t["side"] == "sell" and t["realized_pnl"] is not None]
    realized = sum(t["realized_pnl"] for t in sells)
    commissions = sum(t["commission"] for t in trades)
    print(f"  Trades           : {len(trades)} total "
          f"({sum(1 for t in trades if t['side'] == 'buy')} buys, {len(sells)} sells)")
    if sells:
        wins = sum(1 for t in sells if t["realized_pnl"] > 0)
        print(f"  Realized P&L     : {_fmt_money(realized)}   "
              f"win rate {wins}/{len(sells)} ({wins / len(sells):.0%})")
    print(f"  Commissions paid : {_fmt_money(commissions)}")

    print("-" * 62)
    print("  Equity snapshots:")
    rows = list(broker.db.execute(
        "SELECT ts, equity, bench_sp500_cad FROM snapshots ORDER BY ts DESC LIMIT 12"))
    for r in reversed(rows):
        print(f"    {r['ts']}   equity {_fmt_money(r['equity'])}   "
              f"ZSP {r['bench_sp500_cad'] if r['bench_sp500_cad'] else '-'}")
    print("=" * 62)
    print_portfolio(broker)


def print_trades(broker: Broker, n: int = 30):
    trades = broker.recent_trades(n)
    if not trades:
        print("No trades yet.")
        return
    for t in reversed(trades):
        pnl = f"  realized {t['realized_pnl']:+.2f}" if t["realized_pnl"] is not None else ""
        print(f"{t['ts']}  {t['side'].upper():<4} {t['ticker']:<12} "
              f"{t['shares']} sh @ {t['price']:.3f}  comm {t['commission']:.2f}{pnl}")
        if t["reason"]:
            print(f"    reason: {t['reason']}")

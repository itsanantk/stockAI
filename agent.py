"""stockAI CLI.

  python agent.py init                    Create the account ($100k CAD) and record benchmarks
  python agent.py run [-m "instruction"]  Run one AI trading session
  python agent.py report                  Performance vs S&P 500 (ZSP.TO) and TSX
  python agent.py portfolio               Quick portfolio view
  python agent.py trades                  Trade log with reasons
  python agent.py quote TICKER            Live quote (e.g. SHOP, RY, TOI.V)
  python agent.py fill-pending            Fill queued market-on-open orders (run also does this)
"""

import argparse
import json
import sys

# Windows consoles default to cp1252 — the AI's output is full of Unicode.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

from stockai import broker as broker_mod
from stockai import market, report
from stockai.config import load_config


def main():
    parser = argparse.ArgumentParser(description="stockAI — AI trading agent for the Canadian market")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init")
    p_run = sub.add_parser("run")
    p_run.add_argument("-m", "--message", default=None,
                       help="Optional extra instruction for the AI this session")
    p_run.add_argument("--skip-if-closed", action="store_true",
                       help="Exit without a session when the TSX is closed (for schedulers)")
    sub.add_parser("daily")
    sub.add_parser("report")
    sub.add_parser("portfolio")
    sub.add_parser("trades")
    p_quote = sub.add_parser("quote")
    p_quote.add_argument("ticker")
    sub.add_parser("fill-pending")
    sub.add_parser("dashboard")

    args = parser.parse_args()
    cfg = load_config()

    if args.command == "quote":
        print(json.dumps(market.get_quote(args.ticker, include_book=True), indent=2))
        return

    broker = broker_mod.Broker(cfg)

    if args.command == "init":
        broker.init_account()
        broker.snapshot()
        print(f"Account created with ${cfg.starting_cash:,.2f} CAD.")
        print("Benchmark inception levels recorded (ZSP.TO, ^GSPTSE).")
        print("Run 'python agent.py run' to start the first AI trading session.")
        return

    if not broker.is_initialized():
        print("No account yet — run 'python agent.py init' first.")
        sys.exit(1)

    if args.command == "fill-pending":
        results = broker.fill_pending_orders()
        if not results:
            print("Nothing filled (no pending orders, or market closed).")
        for r in results:
            print(json.dumps(r, indent=2, default=str))
        return

    if args.command == "portfolio":
        report.print_portfolio(broker)
        return

    if args.command == "report":
        report.print_report(broker, cfg)
        return

    if args.command == "trades":
        report.print_trades(broker)
        return

    if args.command == "dashboard":
        from stockai import dashboard
        path = dashboard.generate(broker, cfg)
        print(f"Dashboard written to {path}")
        try:
            import os
            os.startfile(path)
        except OSError:
            pass
        return

    if args.command == "daily":
        from stockai import daily, dashboard
        content = daily.build_daily_summary(broker, cfg)
        print(content)
        try:
            dashboard.generate(broker, cfg)
        except Exception as e:
            print(f"[dashboard] generation failed: {e}")
        return

    if args.command == "run":
        from stockai.brain import run_session

        if args.skip_if_closed and not market.market_status()["is_open"]:
            print("Market closed and --skip-if-closed set; no session run.")
            return

        filled = broker.fill_pending_orders()
        for f in filled:
            r = f["result"]
            print(f"[pending] {f['order']['side']} {f['order']['ticker']}: {r['status']}"
                  + (f" @ {r.get('price')}" if r["status"] == "filled" else f" ({r.get('reason', '')})"))
        broker.snapshot()

        summary = run_session(broker, cfg, extra_instruction=args.message)

        broker.snapshot()
        print("\n" + "=" * 62)
        print("SESSION SUMMARY")
        print("=" * 62)
        print(summary or "(none)")
        print()
        report.print_portfolio(broker)
        try:
            from stockai import dashboard
            path = dashboard.generate(broker, cfg)
            print(f"\nDashboard updated: {path}")
        except Exception as e:
            print(f"[dashboard] generation failed: {e}")


if __name__ == "__main__":
    main()

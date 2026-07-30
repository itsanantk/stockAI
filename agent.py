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


def resolve_mode(mode, status, now, deep_done, mins_since_last=None):
    """Resolve --mode auto against the market clock.

    GitHub's cron is best-effort — firings run late or get dropped outright —
    so the workflow fires a BARRAGE of redundant crons and this function
    decides which firings actually do AI work. Returns (mode, skip_reason):
      - pre-market firing, deep session already ran  -> skip (no-op)
      - pre-market firing, none ran yet              -> premarket deep session
      - market open, no deep session yet today       -> promote to full session
      - market open, last session < 50 min ago       -> skip (rate gate; the
        caller still fills pending orders + snapshots so data stays fresh)
      - market open otherwise                        -> checkin
    Net effect: exactly one deep session and ~hourly check-ins per day, no
    matter how many crons fire or how many get dropped.
    """
    import datetime as dt
    is_premarket_window = (status["detail"] == "pre-market"
                           and now.time() >= dt.time(7, 30))
    if mode == "auto":
        if status["is_open"]:
            if not deep_done:
                mode = "full"
            elif mins_since_last is not None and mins_since_last < 50:
                return mode, (f"last session ran {mins_since_last:.0f} min ago — "
                              "check-ins are ~hourly; skipping the AI call this firing")
            else:
                mode = "checkin"
        elif is_premarket_window:
            if deep_done:
                return mode, "pre-market session already ran today; duplicate firing skipped"
            mode = "premarket"
    return mode, None


def main():
    parser = argparse.ArgumentParser(description="stockAI — AI trading agent for the Canadian market")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init")
    p_run = sub.add_parser("run")
    p_run.add_argument("-m", "--message", default=None,
                       help="Optional extra instruction for the AI this session")
    p_run.add_argument("--skip-if-closed", action="store_true",
                       help="Exit without a session when the TSX is closed (for schedulers)")
    p_run.add_argument("--mode", choices=["full", "checkin", "premarket", "auto"],
                       default="full",
                       help="full = deep research session; checkin = quick monitoring pass "
                            "on a cheaper model; premarket = full session before the open "
                            "that queues orders for the opening auction; auto = premarket "
                            "before the bell, checkin while open, skip otherwise")
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
        import datetime as dt
        from zoneinfo import ZoneInfo

        from stockai.brain import run_session

        status = market.market_status()
        now = dt.datetime.now(ZoneInfo("America/Toronto"))
        deep_done = broker.had_deep_session(now.strftime("%Y-%m-%d"))

        mode, skip_reason = resolve_mode(args.mode, status, now, deep_done,
                                         broker.minutes_since_last_session())
        if skip_reason:
            print(f"[run] {skip_reason}")
            if status["is_open"]:
                # still keep the book and site fresh: fill queued orders,
                # snapshot equity (the workflow's daily step redeploys the page)
                for f in broker.fill_pending_orders():
                    r = f["result"]
                    print(f"[pending] {f['order']['side']} {f['order']['ticker']}: {r['status']}")
                broker.snapshot()
            return
        if args.mode == "auto" and mode == "full":
            print("[run] pre-market session was missed today — promoting this "
                  "run to the daily full session")

        if args.skip_if_closed and not status["is_open"] and mode != "premarket":
            print("Market closed and --skip-if-closed set; no session run.")
            return

        extra = args.message
        if mode == "premarket":
            premarket_note = (
                "PRE-MARKET SESSION: the TSX opens at 9:30 ET. Do your full research "
                "now — overnight and weekend news, your holdings, the movers and "
                "catalysts — and queue any buy/sell orders in this session. Queued "
                "orders fill at today's opening auction price, so place them as if "
                "buying/selling at the open."
            )
            extra = f"{premarket_note}\n\n{extra}" if extra else premarket_note
        elif mode == "checkin":
            cfg.cc_model = cfg.checkin_model
            cfg.effort = "medium"
            cfg.max_web_searches = cfg.checkin_max_searches
            checkin_note = (
                "MONITORING CHECK-IN, not a full session. Review the portfolio and "
                "check news on your current holdings and watchlist only. Act only if a "
                "position hit its stop or target, a thesis-breaking headline appeared, "
                "or a clearly material new catalyst emerged on a watchlist name. "
                "Otherwise change nothing. No full market scans, no new research "
                "threads, no note updates unless something changed. Keep the summary "
                "to a few lines."
            )
            extra = f"{checkin_note}\n\n{extra}" if extra else checkin_note
        print(f"[run] mode={mode}")
        broker.log(f"cli-{now.strftime('%Y%m%d%H%M%S')}", "mode", mode)

        filled = broker.fill_pending_orders()
        for f in filled:
            r = f["result"]
            print(f"[pending] {f['order']['side']} {f['order']['ticker']}: {r['status']}"
                  + (f" @ {r.get('price')}" if r["status"] == "filled" else f" ({r.get('reason', '')})"))
        broker.snapshot()

        summary = run_session(broker, cfg, extra_instruction=extra)

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

"""Backend-agnostic session core: tool logic, system prompt, opening message.

Both brains (API tool-runner and Claude Code subscription) wrap these functions
with their own tool decorators, so trading behavior is identical either way.
"""

from __future__ import annotations

import json

from . import market
from .broker import Broker
from .config import Config

# Module-level context so plain tool functions can reach the broker/session.
# Set by the active backend's run_session().
ctx: dict = {"broker": None, "session_id": None, "cfg": None}


# ---------------------------------------------------------------- tool logic

def t_portfolio() -> str:
    b: Broker = ctx["broker"]
    return json.dumps({
        "performance": b.performance(),
        "positions": b.positions_with_prices(),
        "pending_orders": b.pending(),
        "recent_trades": b.recent_trades(10),
    }, default=str)


def t_quote(ticker: str) -> str:
    try:
        return json.dumps(market.get_quote(ticker))
    except Exception as e:
        return json.dumps({"error": str(e)})


def t_history(ticker: str, period: str = "1mo", interval: str = "1d") -> str:
    try:
        return json.dumps(market.get_history(ticker, period, interval))
    except Exception as e:
        return json.dumps({"error": str(e)})


def t_snapshot() -> str:
    try:
        return json.dumps({
            "market_status": market.market_status(),
            "indices": market.index_snapshot(ctx["cfg"]),
            "movers": market.top_movers(),
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


def t_buy(ticker: str, amount_cad: float, reason: str) -> str:
    b: Broker = ctx["broker"]
    result = b.buy(ticker, float(amount_cad), reason, ctx["session_id"])
    b.log(ctx["session_id"], "trade", json.dumps(
        {"call": "buy", "ticker": ticker, "amount_cad": amount_cad,
         "reason": reason, "result": result}))
    return json.dumps(result)


def t_sell(ticker: str, shares, reason: str) -> str:
    b: Broker = ctx["broker"]
    result = b.sell(ticker, shares, reason, ctx["session_id"])
    b.log(ctx["session_id"], "trade", json.dumps(
        {"call": "sell", "ticker": ticker, "shares": shares,
         "reason": reason, "result": result}))
    return json.dumps(result)


def t_note(content: str) -> str:
    b: Broker = ctx["broker"]
    b.save_note(content, ctx["session_id"])
    return json.dumps({"status": "saved"})


# ---------------------------------------------------------------- prompt

SYSTEM_PROMPT = """You are the portfolio manager of a Canadian equity trading account. You have full, autonomous discretion over it.

## Mandate
- Universe: TSX and TSX Venture listings only (CAD).
- Objective: beat the S&P 500 (measured against ZSP.TO, the S&P 500 ETF in CAD) on both an absolute and risk-aware basis.
- Horizon: swing trades — returns expected in days to one month. You are not a day trader and not a buy-and-forever investor.
- You trade real market prices with real commissions and spreads. Treat the capital as real money.

## Process for each session
1. Review the portfolio and any pending orders. For every open position, check for fresh news and re-verify the thesis. Exit when a thesis is broken or a stop level is breached — do not hope.
2. Scan the market snapshot for what is moving and why.
3. Research candidates with web search: earnings surprises and guidance changes, analyst actions, sector momentum (energy, gold, uranium, tech), insider buying, contract wins, M&A. Prefer names with a concrete near-term catalyst, not just a story.
4. For any candidate, check the quote and price history before buying: liquidity, trend, and where today's price sits vs the recent range.
5. Size positions deliberately: high-conviction catalyst trades larger (10-20% of equity), speculative ideas smaller (3-7%). Diversify across 4-10 positions when invested. Holding cash is a position — if nothing has edge, wait.
6. End every session by calling save_note with: watchlist + entry levels, each open position's thesis with target and stop, and anything you learned.

## Search discipline
For anything where current information changes the answer — news, prices, earnings dates, analyst moves — search before concluding rather than answering from memory. Verify any TSXV small-cap story with at least two independent results; low-float Venture names are frequent pump-and-dump targets, and promotional press releases are not catalysts.

## Hard rules (enforced by the broker — orders violating them are rejected)
- Long only, no margin, no shorting, CAD listings only.
- Max 20% of equity per position at cost; order size capped at 5% of a stock's 20-day average dollar volume; min share price $0.50.
- Orders placed while the market is closed queue as market-on-open.

## Style
Work decisively. Every buy/sell needs a written reason with catalyst, timeline, and exit plan. Keep your final summary brief: what you did, why, and what you're watching — a few sentences per decision, no filler."""


def build_opening_message(broker: Broker, cfg: Config) -> str:
    status = market.market_status()
    perf = broker.performance()
    notes = broker.latest_notes(3)
    parts = [
        f"Trading session — {status['now_toronto']}. Market is {status['session']} ({status['detail']}).",
        f"\nAccount: equity ${perf['equity']:,.2f} | cash ${perf['cash']:,.2f} | "
        f"return since inception {perf['return_pct']:+.2f}%",
    ]
    sp = perf["benchmarks"].get(cfg.benchmark_sp500_cad)
    if sp:
        parts.append(f"Benchmark ZSP.TO since inception: {sp['return_pct']:+.2f}% "
                     f"(your alpha: {perf.get('alpha_vs_sp500_pct', 0):+.2f}%)")
    positions = broker.positions_with_prices()
    if positions:
        parts.append("\nOpen positions:\n" + json.dumps(positions, default=str))
    else:
        parts.append("\nNo open positions.")
    pending = broker.pending()
    if pending:
        parts.append("\nPending market-on-open orders:\n" + json.dumps(pending, default=str))
    if notes:
        parts.append("\nYour notes from previous sessions (newest first):")
        for n in notes:
            parts.append(f"--- {n['ts']} ---\n{n['content']}")
    else:
        parts.append("\nNo previous notes — this is your first session.")
    parts.append(
        "\nRun your session now: review positions, research the market and news, "
        "trade where you have edge, and finish with save_note and a brief summary."
    )
    return "\n".join(parts)

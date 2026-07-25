"""AI portfolio manager — Claude API backend + backend dispatcher.

Two interchangeable backends run the same session (same prompt, same tools):
  - "api"         Anthropic API tool runner (needs API credits)
  - "claude-code" Your Claude Code subscription via the Claude Agent SDK
  - "auto"        Try the API; fall back to claude-code on billing/auth errors

The Python tool runner does not auto-resume `pause_turn` from server-side web
search, so the API session loop mirrors history and restarts the runner when a
turn pauses.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import uuid
from zoneinfo import ZoneInfo

from . import core
from .broker import Broker
from .config import Config

TZ = ZoneInfo("America/Toronto")


def _new_session_id() -> str:
    return dt.datetime.now(TZ).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


# ---------------------------------------------------------------- dispatcher

def run_session(broker: Broker, cfg: Config, extra_instruction: str | None = None) -> str:
    backend = getattr(cfg, "backend", "auto")
    if backend == "claude-code":
        from .brain_cc import run_session_cc
        return run_session_cc(broker, cfg, extra_instruction)
    if backend == "api":
        return run_session_api(broker, cfg, extra_instruction)

    # auto: API first, subscription fallback on billing/auth problems
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print("[brain] no API credentials — using the Claude Code subscription backend.")
        from .brain_cc import run_session_cc
        return run_session_cc(broker, cfg, extra_instruction)

    import anthropic
    try:
        return run_session_api(broker, cfg, extra_instruction)
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
        print(f"\n[brain] API auth failed ({e.__class__.__name__}); "
              "falling back to your Claude Code subscription...")
    except anthropic.BadRequestError as e:
        if "credit balance" not in str(e).lower():
            raise
        print("\n[brain] API account has no credits; "
              "falling back to your Claude Code subscription...")
    from .brain_cc import run_session_cc
    return run_session_cc(broker, cfg, extra_instruction)


# ---------------------------------------------------------------- API backend

def _api_tools(cfg: Config) -> list:
    from anthropic import beta_tool

    @beta_tool
    def get_portfolio() -> str:
        """Get the current portfolio: cash, equity, open positions with live P&L,
        pending orders, recent trades, and performance vs the S&P 500 (ZSP.TO)
        and TSX Composite benchmarks."""
        return core.t_portfolio()

    @beta_tool
    def get_quote(ticker: str) -> str:
        """Get a live quote for a Canadian stock (price, day change, volume,
        52-week range, market cap).

        Args:
            ticker: Symbol, e.g. 'SHOP', 'RY.TO', 'TOI.V'. TSX assumed if no suffix.
        """
        return core.t_quote(ticker)

    @beta_tool
    def get_history(ticker: str, period: str = "1mo", interval: str = "1d") -> str:
        """Get recent OHLCV price history and liquidity stats for a stock.

        Args:
            ticker: Symbol, e.g. 'CNQ' or 'TOI.V'.
            period: Lookback window: '5d', '1mo', '3mo', '6mo', '1y'.
            interval: Bar size: '1d', '1h', '30m'.
        """
        return core.t_history(ticker, period, interval)

    @beta_tool
    def get_market_snapshot() -> str:
        """Get a Canadian market overview: index/commodity levels (TSX, S&P 500,
        USDCAD, oil, gold) and today's top gainers, losers, and most-traded
        names across ~150 liquid TSX/TSXV stocks."""
        return core.t_snapshot()

    @beta_tool
    def buy(ticker: str, amount_cad: float, reason: str) -> str:
        """Buy a Canadian stock with a market order sized in CAD. Fills at the
        real current offer (or queues for the next open if the market is
        closed). Hard broker rules: TSX/TSXV only, max 20% of equity per
        position, order size capped vs real liquidity, min price $0.50.

        Args:
            ticker: Symbol, e.g. 'WELL' or 'TOI.V'.
            amount_cad: Approximate CAD amount to invest (converted to whole shares).
            reason: Your thesis in 1-3 sentences: catalyst, timeline, exit plan.
        """
        return core.t_buy(ticker, amount_cad, reason)

    @beta_tool
    def sell(ticker: str, shares: str, reason: str) -> str:
        """Sell shares you hold with a market order. Fills at the real current
        bid (or queues for the next open if the market is closed). No shorting.

        Args:
            ticker: Symbol of a stock you currently hold.
            shares: Number of shares to sell, or 'all' to close the position.
            reason: Why you are selling. Stored in the trade log.
        """
        return core.t_sell(ticker, shares, reason)

    @beta_tool
    def save_note(content: str) -> str:
        """Save a note to your persistent memory, shown at the start of your
        next session. Use for: watchlist with entry levels, open-position
        theses with targets and stops, and lessons learned.

        Args:
            content: The note text (markdown fine). Keep it under ~400 words.
        """
        return core.t_note(content)

    return [
        get_portfolio, get_quote, get_history, get_market_snapshot,
        buy, sell, save_note,
        {"type": "web_search_20260209", "name": "web_search",
         "max_uses": cfg.max_web_searches},
    ]


def run_session_api(broker: Broker, cfg: Config, extra_instruction: str | None = None) -> str:
    import anthropic

    session_id = _new_session_id()
    core.ctx.update(broker=broker, session_id=session_id, cfg=cfg)
    client = anthropic.Anthropic()

    opening = core.build_opening_message(broker, cfg)
    if extra_instruction:
        opening += f"\n\nOperator instruction for this session: {extra_instruction}"
    messages: list = [{"role": "user", "content": opening}]
    broker.log(session_id, "opening", opening)
    print(f"[session {session_id}] backend=api model={cfg.model} effort={cfg.effort}",
          flush=True)

    runner_kwargs = dict(
        model=cfg.model,
        max_tokens=cfg.max_tokens,
        system=core.SYSTEM_PROMPT,
        tools=_api_tools(cfg),
        output_config={"effort": cfg.effort},
        betas=["server-side-fallback-2026-06-01"],
        fallbacks=[{"model": "claude-opus-4-8"}],
    )

    turns = 0
    restarts = 0
    last = None
    while True:
        try:
            runner = client.beta.messages.tool_runner(messages=messages, **runner_kwargs)
        except TypeError:
            # Older SDK without the fallbacks param — drop it and retry.
            runner_kwargs.pop("fallbacks", None)
            runner_kwargs.pop("betas", None)
            runner = client.beta.messages.tool_runner(messages=messages, **runner_kwargs)

        stop_early = False
        for message in runner:
            last = message
            turns += 1
            messages.append({"role": "assistant", "content": message.content})
            _print_and_log(broker, session_id, message)
            tool_response = runner.generate_tool_call_response()
            if tool_response is not None:
                messages.append(tool_response)
            if turns >= cfg.max_assistant_turns:
                print(f"[session {session_id}] reached max turns ({turns}); stopping.",
                      flush=True)
                stop_early = True
                break
        if stop_early or last is None:
            break
        if last.stop_reason == "pause_turn":
            restarts += 1
            if restarts > cfg.max_pause_restarts:
                print(f"[session {session_id}] still paused after {restarts} restarts.",
                      flush=True)
                break
            continue  # messages already end with the paused assistant turn
        break

    summary = ""
    if last is not None:
        if last.stop_reason == "refusal":
            summary = "(Session ended with a safety refusal — no summary produced.)"
        else:
            summary = "\n".join(b.text for b in last.content if b.type == "text")
    broker.log(session_id, "summary", summary or "(no summary)")
    print(f"[session {session_id}] done — {turns} assistant turns.", flush=True)
    return summary


def _print_and_log(broker: Broker, session_id: str, message) -> None:
    for block in message.content:
        if block.type == "text" and block.text.strip():
            print(f"\n{block.text.strip()}\n", flush=True)
            broker.log(session_id, "assistant", block.text)
        elif block.type == "tool_use":
            print(f"  -> tool: {block.name}({json.dumps(block.input)[:200]})", flush=True)
            broker.log(session_id, "tool_use",
                       json.dumps({"tool": block.name, "input": block.input}))
        elif block.type == "server_tool_use":
            print(f"  -> web_search: {json.dumps(block.input)[:160]}", flush=True)
            broker.log(session_id, "web_search", json.dumps(block.input))

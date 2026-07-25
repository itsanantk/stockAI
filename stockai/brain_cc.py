"""Claude Code subscription backend: runs the trading session through your
installed Claude Code CLI (and its login) via the Claude Agent SDK.

No API credits needed — sessions draw on your Claude subscription usage.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import uuid
from zoneinfo import ZoneInfo

from . import core
from .broker import Broker
from .config import Config, PROJECT_ROOT

TZ = ZoneInfo("America/Toronto")

TOOL_NAMES = [
    "get_portfolio", "get_quote", "get_history", "get_market_snapshot",
    "buy", "sell", "save_note",
]


def _build_server():
    from claude_agent_sdk import create_sdk_mcp_server, tool

    def text(result: str) -> dict:
        return {"content": [{"type": "text", "text": result}]}

    @tool("get_portfolio",
          "Get the current portfolio: cash, equity, open positions with live P&L, "
          "pending orders, recent trades, and performance vs the S&P 500 (ZSP.TO) "
          "and TSX Composite benchmarks.", {})
    async def get_portfolio(args):
        return text(core.t_portfolio())

    @tool("get_quote",
          "Get a live quote for a Canadian stock (price, day change, volume, "
          "52-week range, market cap). Ticker e.g. 'SHOP', 'RY.TO', 'TOI.V'; "
          "TSX assumed if no suffix.", {"ticker": str})
    async def get_quote(args):
        return text(core.t_quote(args["ticker"]))

    @tool("get_history",
          "Get recent OHLCV price history and liquidity stats for a stock. "
          "period: 5d|1mo|3mo|6mo|1y, interval: 1d|1h|30m.",
          {"ticker": str, "period": str, "interval": str})
    async def get_history(args):
        return text(core.t_history(args["ticker"], args.get("period", "1mo"),
                                   args.get("interval", "1d")))

    @tool("get_market_snapshot",
          "Get a Canadian market overview: index/commodity levels (TSX, S&P 500, "
          "USDCAD, oil, gold) and today's top gainers, losers, and most-traded "
          "names across ~150 liquid TSX/TSXV stocks.", {})
    async def get_market_snapshot(args):
        return text(core.t_snapshot())

    @tool("buy",
          "Buy a Canadian stock with a market order sized in CAD. Fills at the "
          "real current offer (or queues for the next open if the market is "
          "closed). Hard broker rules: TSX/TSXV only, max 20% of equity per "
          "position, order size capped vs real liquidity, min price $0.50. "
          "reason = your thesis: catalyst, timeline, exit plan.",
          {"ticker": str, "amount_cad": float, "reason": str})
    async def buy(args):
        return text(core.t_buy(args["ticker"], args["amount_cad"], args["reason"]))

    @tool("sell",
          "Sell shares you hold with a market order at the real current bid "
          "(queues for next open if market closed). No shorting. "
          "shares = a number or 'all'.",
          {"ticker": str, "shares": str, "reason": str})
    async def sell(args):
        return text(core.t_sell(args["ticker"], args["shares"], args["reason"]))

    @tool("save_note",
          "Save a note to your persistent memory, shown at the start of your "
          "next session: watchlist with entry levels, open-position theses with "
          "targets and stops, lessons learned. Under ~400 words.",
          {"content": str})
    async def save_note(args):
        return text(core.t_note(args["content"]))

    return create_sdk_mcp_server(
        name="stockai",
        tools=[get_portfolio, get_quote, get_history, get_market_snapshot,
               buy, sell, save_note],
    )


async def _run(broker: Broker, cfg: Config, opening: str, session_id: str) -> str:
    from claude_agent_sdk import (
        AssistantMessage, ClaudeAgentOptions, ResultMessage, query,
    )

    # The CLI would prefer an inherited ANTHROPIC_API_KEY over the subscription
    # login — drop it for this process so the session bills to the subscription.
    os.environ.pop("ANTHROPIC_API_KEY", None)

    options = ClaudeAgentOptions(
        system_prompt=core.SYSTEM_PROMPT,
        mcp_servers={"stockai": _build_server()},
        strict_mcp_config=True,  # only our trading tools — no personal connectors
        allowed_tools=[f"mcp__stockai__{n}" for n in TOOL_NAMES]
        + ["WebSearch", "WebFetch"],
        disallowed_tools=["Bash", "Read", "Write", "Edit", "NotebookEdit",
                          "Glob", "Grep", "Task", "TodoWrite", "KillShell"],
        permission_mode="bypassPermissions",
        setting_sources=[],
        max_turns=cfg.max_assistant_turns,
        model=getattr(cfg, "cc_model", "opus"),
        effort=cfg.effort,
        cwd=str(PROJECT_ROOT),
    )

    summary_parts: list[str] = []
    final_result = None
    async for msg in query(prompt=opening, options=options):
        if isinstance(msg, AssistantMessage):
            summary_parts = []
            for block in msg.content:
                btype = getattr(block, "text", None)
                if btype is not None and block.text.strip():
                    print(f"\n{block.text.strip()}\n", flush=True)
                    broker.log(session_id, "assistant", block.text)
                    summary_parts.append(block.text)
                elif hasattr(block, "name"):  # tool use
                    label = block.name.replace("mcp__stockai__", "")
                    args = json.dumps(getattr(block, "input", {}))[:200]
                    print(f"  -> tool: {label}({args})", flush=True)
                    broker.log(session_id, "tool_use",
                               json.dumps({"tool": label,
                                           "input": getattr(block, "input", {})}))
        elif isinstance(msg, ResultMessage):
            final_result = msg

    if final_result is not None and getattr(final_result, "result", None):
        return final_result.result
    return "\n".join(summary_parts)


def run_session_cc(broker: Broker, cfg: Config, extra_instruction: str | None = None) -> str:
    session_id = dt.datetime.now(TZ).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    core.ctx.update(broker=broker, session_id=session_id, cfg=cfg)

    opening = core.build_opening_message(broker, cfg)
    if extra_instruction:
        opening += f"\n\nOperator instruction for this session: {extra_instruction}"
    broker.log(session_id, "opening", opening)
    print(f"[session {session_id}] backend=claude-code model={getattr(cfg, 'cc_model', 'opus')}",
          flush=True)

    summary = asyncio.run(_run(broker, cfg, opening, session_id))
    broker.log(session_id, "summary", summary or "(no summary)")
    print(f"[session {session_id}] done.", flush=True)
    return summary

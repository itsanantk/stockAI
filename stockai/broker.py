"""Paper-trading broker: SQLite portfolio with realistic fills and hard risk rules.

The AI cannot override anything here — rejections come back as tool results it
has to work around, exactly like a real broker's order-management system.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from zoneinfo import ZoneInfo

from . import market
from .config import Config, DB_PATH

TZ = ZoneInfo("America/Toronto")

SCHEMA = """
CREATE TABLE IF NOT EXISTS account (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    cash REAL NOT NULL,
    starting_cash REAL NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS positions (
    ticker TEXT PRIMARY KEY,
    shares INTEGER NOT NULL,
    avg_cost REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    shares INTEGER NOT NULL,
    price REAL NOT NULL,
    commission REAL NOT NULL,
    notional REAL NOT NULL,
    realized_pnl REAL,
    reason TEXT,
    session_id TEXT
);
CREATE TABLE IF NOT EXISTS pending_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_ts TEXT NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    amount_cad REAL,
    shares INTEGER,
    reason TEXT
);
CREATE TABLE IF NOT EXISTS snapshots (
    ts TEXT PRIMARY KEY,
    equity REAL NOT NULL,
    cash REAL NOT NULL,
    positions_json TEXT NOT NULL,
    bench_sp500_cad REAL,
    bench_tsx REAL
);
CREATE TABLE IF NOT EXISTS benchmarks (
    symbol TEXT PRIMARY KEY,
    inception_price REAL NOT NULL,
    inception_ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    session_id TEXT,
    content TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    session_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    content TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS daily_summaries (
    date TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    content TEXT NOT NULL
);
"""


def _now() -> str:
    return dt.datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


class Broker:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.db = sqlite3.connect(DB_PATH)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    # ---------- lifecycle ----------

    def is_initialized(self) -> bool:
        return self.db.execute("SELECT 1 FROM account WHERE id=1").fetchone() is not None

    def init_account(self):
        if self.is_initialized():
            raise RuntimeError("Account already initialized — delete data/stockai.db to restart.")
        self.db.execute(
            "INSERT INTO account (id, cash, starting_cash, created_at) VALUES (1, ?, ?, ?)",
            (self.cfg.starting_cash, self.cfg.starting_cash, _now()),
        )
        for sym in (self.cfg.benchmark_sp500_cad, self.cfg.benchmark_tsx):
            try:
                px = market.benchmark_price(sym)
                self.db.execute(
                    "INSERT OR REPLACE INTO benchmarks VALUES (?, ?, ?)", (sym, px, _now())
                )
            except Exception as e:
                print(f"[init] warning: could not record benchmark {sym}: {e}")
        self.db.commit()

    # ---------- state ----------

    @property
    def cash(self) -> float:
        return self.db.execute("SELECT cash FROM account WHERE id=1").fetchone()["cash"]

    @property
    def starting_cash(self) -> float:
        return self.db.execute("SELECT starting_cash FROM account WHERE id=1").fetchone()[
            "starting_cash"
        ]

    def _set_cash(self, cash: float):
        self.db.execute("UPDATE account SET cash=? WHERE id=1", (cash,))

    def positions(self) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM positions WHERE shares > 0 ORDER BY ticker"
        )]

    def positions_with_prices(self) -> list[dict]:
        out = []
        for p in self.positions():
            row = dict(p)
            try:
                q = market.get_quote(p["ticker"])
                row["last"] = q["last"]
                row["market_value"] = round(q["last"] * p["shares"], 2)
                row["unrealized_pnl"] = round((q["last"] - p["avg_cost"]) * p["shares"], 2)
                row["unrealized_pct"] = round((q["last"] / p["avg_cost"] - 1) * 100, 2)
                row["day_change_pct"] = q.get("change_pct")
            except Exception as e:
                row["price_error"] = str(e)
            out.append(row)
        return out

    def equity(self) -> float:
        total = self.cash
        for p in self.positions_with_prices():
            total += p.get("market_value", p["shares"] * p["avg_cost"])
        return round(total, 2)

    def recent_trades(self, n: int = 15) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (n,)
        )]

    def pending(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM pending_orders ORDER BY id")]

    def latest_notes(self, n: int = 3) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT ts, content FROM notes ORDER BY id DESC LIMIT ?", (n,)
        )]

    def save_note(self, content: str, session_id: str | None = None):
        self.db.execute(
            "INSERT INTO notes (ts, session_id, content) VALUES (?, ?, ?)",
            (_now(), session_id, content),
        )
        self.db.commit()

    def save_daily_summary(self, date: str, content: str):
        self.db.execute(
            "INSERT OR REPLACE INTO daily_summaries VALUES (?, ?, ?)",
            (date, _now(), content),
        )
        self.db.commit()

    def daily_summaries(self, n: int = 7) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM daily_summaries ORDER BY date DESC LIMIT ?", (n,)
        )]

    def log(self, session_id: str, kind: str, content: str):
        self.db.execute(
            "INSERT INTO journal (ts, session_id, kind, content) VALUES (?, ?, ?, ?)",
            (_now(), session_id, kind, content[:20000]),
        )
        self.db.commit()

    # ---------- fills ----------

    def _commission(self, shares: int, price: float) -> float:
        """IBKR Canada fixed pricing: per-share, floor $1, cap 0.5% of trade value
        (the cap overrides the floor on very small orders, matching IBKR)."""
        c = max(shares * self.cfg.commission_per_share, self.cfg.commission_min)
        cap = self.cfg.commission_max_pct * shares * price
        return round(min(c, cap) if cap > 0 else c, 2)

    def _fill_price(self, side: str, q: dict) -> float:
        """Realistic fill: cross the spread if book data is sane, else last + slippage."""
        last = q["last"]
        slip = self.cfg.slippage_bps / 10000
        if side == "buy":
            ask = q.get("ask")
            if ask and 0 <= (ask - last) / last < 0.05:
                return ask
            return last * (1 + slip)
        bid = q.get("bid")
        if bid and 0 <= (last - bid) / last < 0.05:
            return bid
        return last * (1 - slip)

    def _validate_symbol(self, q: dict) -> str | None:
        sym = q["symbol"]
        if not sym.endswith(self.cfg.allowed_suffixes):
            return f"REJECTED: {sym} is not a TSX/TSXV listing. This account trades Canadian listings only (.TO/.V)."
        if q.get("currency") and q["currency"] != "CAD":
            return f"REJECTED: {sym} trades in {q['currency']}, not CAD. Use the Canadian listing."
        if q["last"] < self.cfg.min_price:
            return f"REJECTED: {sym} at ${q['last']:.2f} is below the ${self.cfg.min_price:.2f} minimum price rule."
        return None

    def buy(self, ticker: str, amount_cad: float, reason: str, session_id: str,
            queued_from: int | None = None, use_open_price: bool = False) -> dict:
        try:
            q = market.get_quote(ticker, include_book=True)
        except ValueError as e:
            return {"status": "rejected", "reason": str(e)}
        sym = q["symbol"]

        err = self._validate_symbol(q)
        if err:
            return {"status": "rejected", "reason": err}

        status = market.market_status()
        if not status["is_open"] and queued_from is None:
            return self._queue(sym, "buy", amount_cad=amount_cad, reason=reason, status=status)

        price = None
        if use_open_price:
            price = market.today_open_price(sym)
        if price is None:
            price = self._fill_price("buy", q)
        price = round(price, 3)

        shares = int(amount_cad // price)
        if shares <= 0:
            return {"status": "rejected", "reason": f"amount_cad {amount_cad} buys 0 shares at ${price}."}
        commission = self._commission(shares, price)
        cost = shares * price + commission
        while cost > self.cash and shares > 0:
            shares -= 1
            commission = self._commission(shares, price)
            cost = shares * price + commission
        if shares <= 0:
            return {"status": "rejected",
                    "reason": f"Insufficient cash: ${self.cash:,.2f} available."}

        # Liquidity rule: order must be small vs the name's real daily dollar volume
        adv = market.avg_dollar_volume(sym)
        notional = shares * price
        if adv > 0 and notional > self.cfg.max_adv_pct * adv:
            max_notional = self.cfg.max_adv_pct * adv
            return {"status": "rejected", "reason": (
                f"LIQUIDITY: order ${notional:,.0f} exceeds {self.cfg.max_adv_pct:.0%} of "
                f"{sym}'s 20-day avg dollar volume (${adv:,.0f}). Max order ≈ ${max_notional:,.0f}."
            )}

        # Concentration rule: position cost basis capped vs current equity
        equity = self.equity()
        pos = self.db.execute("SELECT * FROM positions WHERE ticker=?", (sym,)).fetchone()
        existing_cost = (pos["shares"] * pos["avg_cost"]) if pos else 0.0
        if existing_cost + notional > self.cfg.max_position_pct * equity:
            room = self.cfg.max_position_pct * equity - existing_cost
            return {"status": "rejected", "reason": (
                f"CONCENTRATION: position would exceed {self.cfg.max_position_pct:.0%} of equity "
                f"(${equity:,.0f}). Remaining room in {sym}: ${max(room, 0):,.0f}."
            )}

        # Fill
        if pos:
            new_shares = pos["shares"] + shares
            new_avg = (existing_cost + shares * price) / new_shares
            self.db.execute("UPDATE positions SET shares=?, avg_cost=? WHERE ticker=?",
                            (new_shares, new_avg, sym))
        else:
            self.db.execute("INSERT INTO positions VALUES (?, ?, ?)", (sym, shares, price))
        self._set_cash(self.cash - cost)
        self.db.execute(
            "INSERT INTO trades (ts, ticker, side, shares, price, commission, notional, realized_pnl, reason, session_id)"
            " VALUES (?, ?, 'buy', ?, ?, ?, ?, NULL, ?, ?)",
            (_now(), sym, shares, price, commission, round(notional, 2), reason, session_id),
        )
        if queued_from is not None:
            self.db.execute("DELETE FROM pending_orders WHERE id=?", (queued_from,))
        self.db.commit()
        return {"status": "filled", "symbol": sym, "side": "buy", "shares": shares,
                "price": price, "commission": commission, "total_cost": round(cost, 2),
                "cash_remaining": round(self.cash, 2)}

    def sell(self, ticker: str, shares: int | str, reason: str, session_id: str,
             queued_from: int | None = None, use_open_price: bool = False) -> dict:
        sym = market.normalize_ticker(ticker)
        pos = self.db.execute("SELECT * FROM positions WHERE ticker=?", (sym,)).fetchone()
        if not pos or pos["shares"] <= 0:
            return {"status": "rejected", "reason": f"No position in {sym} (no short selling)."}
        if isinstance(shares, str) and shares.lower() == "all":
            shares = pos["shares"]
        shares = int(shares)
        if shares <= 0 or shares > pos["shares"]:
            return {"status": "rejected",
                    "reason": f"Invalid share count — you hold {pos['shares']} {sym}."}

        try:
            q = market.get_quote(sym, include_book=True)
        except ValueError as e:
            return {"status": "rejected", "reason": str(e)}

        status = market.market_status()
        if not status["is_open"] and queued_from is None:
            return self._queue(sym, "sell", shares=shares, reason=reason, status=status)

        price = None
        if use_open_price:
            price = market.today_open_price(sym)
        if price is None:
            price = self._fill_price("sell", q)
        price = round(price, 3)

        commission = self._commission(shares, price)
        proceeds = shares * price - commission
        realized = round((price - pos["avg_cost"]) * shares - commission, 2)

        remaining = pos["shares"] - shares
        if remaining == 0:
            self.db.execute("DELETE FROM positions WHERE ticker=?", (sym,))
        else:
            self.db.execute("UPDATE positions SET shares=? WHERE ticker=?", (remaining, sym))
        self._set_cash(self.cash + proceeds)
        self.db.execute(
            "INSERT INTO trades (ts, ticker, side, shares, price, commission, notional, realized_pnl, reason, session_id)"
            " VALUES (?, ?, 'sell', ?, ?, ?, ?, ?, ?, ?)",
            (_now(), sym, shares, price, commission, round(shares * price, 2), realized,
             reason, session_id),
        )
        if queued_from is not None:
            self.db.execute("DELETE FROM pending_orders WHERE id=?", (queued_from,))
        self.db.commit()
        return {"status": "filled", "symbol": sym, "side": "sell", "shares": shares,
                "price": price, "commission": commission, "proceeds": round(proceeds, 2),
                "realized_pnl": realized, "cash_now": round(self.cash, 2)}

    def _queue(self, sym: str, side: str, status: dict, amount_cad: float | None = None,
               shares: int | None = None, reason: str = "") -> dict:
        self.db.execute(
            "INSERT INTO pending_orders (created_ts, ticker, side, amount_cad, shares, reason)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (_now(), sym, side, amount_cad, shares, reason),
        )
        self.db.commit()
        return {
            "status": "queued",
            "detail": (
                f"Market is closed ({status['detail']}). Order queued as market-on-open — "
                f"it will fill at the next session's opening price. It can be seen in "
                f"pending_orders and will execute before your next session."
            ),
            "symbol": sym, "side": side, "amount_cad": amount_cad, "shares": shares,
        }

    def fill_pending_orders(self, session_id: str = "pending-fill") -> list[dict]:
        """Fill queued market-on-open orders. Call at the start of each run while open."""
        results = []
        if not market.market_status()["is_open"]:
            return results
        today = dt.datetime.now(TZ).strftime("%Y-%m-%d")
        for order in self.pending():
            placed_today = order["created_ts"][:10] == today
            use_open = not placed_today  # order predates today's open -> opening auction fill
            if order["side"] == "buy":
                r = self.buy(order["ticker"], order["amount_cad"],
                             f"[queued {order['created_ts']}] {order['reason']}",
                             session_id, queued_from=order["id"], use_open_price=use_open)
            else:
                r = self.sell(order["ticker"], order["shares"],
                              f"[queued {order['created_ts']}] {order['reason']}",
                              session_id, queued_from=order["id"], use_open_price=use_open)
            if r["status"] == "rejected":
                # Drop unfillable queued orders so they don't wedge forever
                self.db.execute("DELETE FROM pending_orders WHERE id=?", (order["id"],))
                self.db.commit()
            results.append({"order": dict(order), "result": r})
        return results

    # ---------- snapshots ----------

    def snapshot(self):
        positions = self.positions_with_prices()
        bench = {}
        for sym in (self.cfg.benchmark_sp500_cad, self.cfg.benchmark_tsx):
            try:
                bench[sym] = market.benchmark_price(sym)
            except Exception:
                bench[sym] = None
        self.db.execute(
            "INSERT OR REPLACE INTO snapshots VALUES (?, ?, ?, ?, ?, ?)",
            (_now(), self.equity(), self.cash, json.dumps(positions),
             bench.get(self.cfg.benchmark_sp500_cad), bench.get(self.cfg.benchmark_tsx)),
        )
        self.db.commit()

    def performance(self) -> dict:
        """Portfolio return vs benchmarks since inception."""
        equity = self.equity()
        out = {
            "starting_cash": self.starting_cash,
            "equity": equity,
            "cash": round(self.cash, 2),
            "return_pct": round((equity / self.starting_cash - 1) * 100, 2),
            "benchmarks": {},
        }
        for r in self.db.execute("SELECT * FROM benchmarks"):
            try:
                now_px = market.benchmark_price(r["symbol"])
                out["benchmarks"][r["symbol"]] = {
                    "inception": r["inception_price"],
                    "now": round(now_px, 2),
                    "return_pct": round((now_px / r["inception_price"] - 1) * 100, 2),
                }
            except Exception:
                continue
        sp = out["benchmarks"].get(self.cfg.benchmark_sp500_cad)
        if sp:
            out["alpha_vs_sp500_pct"] = round(out["return_pct"] - sp["return_pct"], 2)
        return out

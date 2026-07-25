"""Market data for Canadian equities via Yahoo Finance (yfinance).

All prices are as offered by the real market (Yahoo data is ~15 min delayed for
TSX, which is the realistic price a retail order would see when it reaches the
book a few moments later).
"""

from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

import yfinance as yf

TZ_TORONTO = ZoneInfo("America/Toronto")

# TSX holidays (yyyy-mm-dd). Extend each December.
TSX_HOLIDAYS = {
    "2026-01-01", "2026-02-16", "2026-04-03", "2026-05-18", "2026-07-01",
    "2026-08-03", "2026-09-07", "2026-10-12", "2026-12-25", "2026-12-28",
    "2027-01-01", "2027-02-15", "2027-03-26", "2027-05-24", "2027-07-01",
    "2027-08-02", "2027-09-06", "2027-10-11", "2027-12-27", "2027-12-28",
}

# Curated liquid Canadian universe (Yahoo symbols). The agent may trade any
# .TO/.V listing — this list just powers the movers scan.
TSX_UNIVERSE = [
    # Financials
    "RY.TO", "TD.TO", "BNS.TO", "BMO.TO", "CM.TO", "NA.TO", "MFC.TO", "SLF.TO",
    "GWO.TO", "IFC.TO", "FFH.TO", "POW.TO", "IGM.TO", "X.TO", "EQB.TO", "GSY.TO",
    "PRL.TO",
    # Energy
    "CNQ.TO", "SU.TO", "CVE.TO", "IMO.TO", "TOU.TO", "ARX.TO", "WCP.TO",
    "BTE.TO", "PEY.TO", "VET.TO", "FRU.TO", "AAV.TO",
    "KEL.TO", "TVE.TO", "ATH.TO", "IPCO.TO",
    # Pipelines & Utilities
    "ENB.TO", "TRP.TO", "PPL.TO", "KEY.TO", "GEI.TO", "FTS.TO", "EMA.TO",
    "H.TO", "CU.TO", "CPX.TO", "NPI.TO", "BLX.TO", "AQN.TO", "TA.TO",
    # Gold & precious metals
    "ABX.TO", "AEM.TO", "K.TO", "WPM.TO", "FNV.TO", "AGI.TO", "BTO.TO",
    "EDV.TO", "IMG.TO", "LUG.TO", "OGC.TO", "PAAS.TO", "DPM.TO",
    "EQX.TO", "KNT.TO", "WDO.TO", "TXG.TO", "OR.TO", "SSRM.TO", "CG.TO",
    "ARIS.TO", "SKE.TO",
    # Base metals, uranium, lithium
    "TECK-B.TO", "FM.TO", "HBM.TO", "ERO.TO", "CS.TO", "LUN.TO", "IVN.TO",
    "CCO.TO", "NXE.TO", "DML.TO", "EFR.TO", "NDM.TO",
    "TKO.TO", "III.TO", "SEA.TO",
    # Tech
    "SHOP.TO", "CSU.TO", "GIB-A.TO", "OTEX.TO", "KXS.TO", "DSG.TO", "LSPD.TO",
    "DCBO.TO", "ENGH.TO", "CLS.TO", "BB.TO", "TOI.V", "LMN.V", "HPS-A.TO",
    "VHI.TO", "DND.TO", "WELL.TO", "ALYA.TO", "TSAT.TO",
    # Industrials & transport
    "CNR.TO", "CP.TO", "WSP.TO", "STN.TO", "TFII.TO", "BBD-B.TO", "AC.TO",
    "CAE.TO", "TRI.TO", "WCN.TO", "GFL.TO", "RBA.TO", "MDA.TO",
    "EIF.TO", "MAL.TO", "DRX.TO", "NFI.TO", "AFN.TO", "BDT.TO",
    # Telecom & media
    "BCE.TO", "T.TO", "RCI-B.TO", "QBR-B.TO", "CJT.TO",
    # Consumer
    "ATD.TO", "L.TO", "MRU.TO", "EMP-A.TO", "DOL.TO", "QSR.TO", "GOOS.TO",
    "ATZ.TO", "GIL.TO", "PBH.TO", "SAP.TO", "WN.TO", "JWEL.TO",
    "BYD.TO", "DOO.TO", "MTY.TO",
    # Real estate
    "REI-UN.TO", "CAR-UN.TO", "GRT-UN.TO", "DIR-UN.TO", "CHP-UN.TO", "FCR-UN.TO",
    # Health & other
    "BHC.TO", "WEED.TO", "TLRY.TO", "HUT.TO", 
    "DMGI.V", 
]

_SUFFIX_RE = re.compile(r"\.(TO|V|NE|CN)$", re.IGNORECASE)


def normalize_ticker(ticker: str) -> str:
    """Normalize user/AI input to a Yahoo TSX/TSXV symbol.

    'ry' -> 'RY.TO'; 'TECK.B' -> 'TECK-B.TO'; 'TOI.V' stays 'TOI.V'.
    """
    t = ticker.strip().upper()
    if _SUFFIX_RE.search(t):
        base, suffix = t.rsplit(".", 1)
    else:
        base, suffix = t, None
    # Class shares: TECK.B / TECK B -> TECK-B
    base = base.replace(" ", "-")
    if re.search(r"\.[A-Z]{1,2}$", base):
        base = base.replace(".", "-")
    if suffix:
        return f"{base}.{suffix}"
    # No exchange suffix given — assume TSX
    return f"{base}.TO"


def get_quote(ticker: str, include_book: bool = False) -> dict:
    """Current quote. include_book=True also fetches bid/ask (slower)."""
    symbol = normalize_ticker(ticker)
    tk = yf.Ticker(symbol)
    fi = tk.fast_info
    quote: dict = {"symbol": symbol}

    def grab(name, key):
        try:
            v = fi[key]
            if v is not None:
                quote[name] = round(float(v), 4) if isinstance(v, (int, float)) else v
        except (KeyError, TypeError, ValueError):
            pass

    grab("last", "lastPrice")
    grab("previous_close", "previousClose")
    grab("open", "open")
    grab("day_high", "dayHigh")
    grab("day_low", "dayLow")
    grab("year_high", "yearHigh")
    grab("year_low", "yearLow")
    grab("volume", "lastVolume")
    grab("avg_volume_10d", "tenDayAverageVolume")
    grab("avg_volume_3m", "threeMonthAverageVolume")
    grab("market_cap", "marketCap")
    try:
        quote["currency"] = fi["currency"]
    except (KeyError, TypeError):
        pass

    if "last" not in quote:
        raise ValueError(f"No price data for {symbol} — is the ticker correct?")

    if quote.get("previous_close"):
        quote["change_pct"] = round(
            (quote["last"] / quote["previous_close"] - 1) * 100, 2
        )

    if include_book:
        try:
            info = tk.info
            bid, ask = info.get("bid"), info.get("ask")
            if bid and bid > 0:
                quote["bid"] = float(bid)
            if ask and ask > 0:
                quote["ask"] = float(ask)
        except Exception:
            pass  # book data is best-effort

    return quote


def get_history(ticker: str, period: str = "1mo", interval: str = "1d") -> dict:
    """Recent OHLCV history plus summary stats."""
    symbol = normalize_ticker(ticker)
    df = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=True)
    if df.empty:
        raise ValueError(f"No history for {symbol}")
    df = df.tail(66)
    rows = [
        {
            "date": idx.strftime("%Y-%m-%d %H:%M") if interval.endswith(("m", "h"))
            else idx.strftime("%Y-%m-%d"),
            "open": round(float(r["Open"]), 3),
            "high": round(float(r["High"]), 3),
            "low": round(float(r["Low"]), 3),
            "close": round(float(r["Close"]), 3),
            "volume": int(r["Volume"]),
        }
        for idx, r in df.iterrows()
    ]
    closes = [r["close"] for r in rows]
    out = {"symbol": symbol, "interval": interval, "bars": rows}
    if len(closes) >= 2:
        out["change_pct_period"] = round((closes[-1] / closes[0] - 1) * 100, 2)
    tail = rows[-20:]
    out["avg_dollar_volume_20d"] = round(
        sum(r["close"] * r["volume"] for r in tail) / len(tail), 0
    )
    return out


def avg_dollar_volume(ticker: str) -> float:
    """20-day average daily dollar volume (CAD) — the liquidity gate."""
    try:
        return float(get_history(ticker, period="2mo", interval="1d")["avg_dollar_volume_20d"])
    except Exception:
        return 0.0


def today_open_price(ticker: str) -> float | None:
    """Today's opening price, if the session has opened."""
    try:
        df = yf.Ticker(normalize_ticker(ticker)).history(period="1d", interval="1d")
        if df.empty:
            return None
        idx = df.index[-1]
        if idx.astimezone(TZ_TORONTO).date() != dt.datetime.now(TZ_TORONTO).date():
            return None
        return float(df["Open"].iloc[-1])
    except Exception:
        return None


def market_status(now: dt.datetime | None = None) -> dict:
    """TSX session status (9:30–16:00 America/Toronto, weekdays, ex-holidays)."""
    now = now or dt.datetime.now(TZ_TORONTO)
    now = now.astimezone(TZ_TORONTO)
    is_weekday = now.weekday() < 5
    is_holiday = now.strftime("%Y-%m-%d") in TSX_HOLIDAYS
    open_t = now.replace(hour=9, minute=30, second=0, microsecond=0)
    close_t = now.replace(hour=16, minute=0, second=0, microsecond=0)
    is_open = is_weekday and not is_holiday and open_t <= now < close_t
    return {
        "now_toronto": now.strftime("%Y-%m-%d %H:%M %Z"),
        "is_open": is_open,
        "session": "open" if is_open else "closed",
        "detail": (
            "regular session" if is_open
            else "holiday" if is_holiday
            else "weekend" if not is_weekday
            else "pre-market" if now < open_t
            else "after-hours"
        ),
    }


def _batch_changes(symbols: list[str]) -> list[dict]:
    """Percent change today for a list of symbols, via one batched download."""
    df = yf.download(
        symbols, period="5d", interval="1d", auto_adjust=True,
        progress=False, group_by="ticker", threads=True,
    )
    out = []
    for sym in symbols:
        try:
            sub = df[sym].dropna()
            if len(sub) < 2:
                continue
            prev, last = float(sub["Close"].iloc[-2]), float(sub["Close"].iloc[-1])
            vol = int(sub["Volume"].iloc[-1])
            out.append({
                "symbol": sym,
                "last": round(last, 2),
                "change_pct": round((last / prev - 1) * 100, 2),
                "dollar_volume": round(last * vol, 0),
            })
        except (KeyError, IndexError, TypeError):
            continue
    return out


def top_movers(n: int = 12) -> dict:
    """Top gainers/losers and volume leaders across the Canadian universe."""
    changes = _batch_changes(TSX_UNIVERSE)
    by_change = sorted(changes, key=lambda r: r["change_pct"], reverse=True)
    by_dollar = sorted(changes, key=lambda r: r["dollar_volume"], reverse=True)
    return {
        "gainers": by_change[:n],
        "losers": by_change[-n:][::-1],
        "most_traded": by_dollar[:n],
        "universe_size": len(changes),
    }


def index_snapshot(cfg) -> dict:
    """Benchmark and macro reference levels."""
    out = {}
    for label, sym in [
        ("sp500_cad_etf", cfg.benchmark_sp500_cad),
        ("tsx_composite", cfg.benchmark_tsx),
        ("sp500_index", "^GSPC"),
        ("usdcad", "CAD=X"),
        ("wti_crude", "CL=F"),
        ("gold", "GC=F"),
    ]:
        try:
            fi = yf.Ticker(sym).fast_info
            last, prev = float(fi["lastPrice"]), float(fi["previousClose"])
            out[label] = {
                "symbol": sym,
                "last": round(last, 2),
                "change_pct": round((last / prev - 1) * 100, 2),
            }
        except Exception:
            continue
    return out


def benchmark_price(symbol: str) -> float:
    return float(yf.Ticker(symbol).fast_info["lastPrice"])

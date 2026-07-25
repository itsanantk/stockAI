"""Configuration for stockAI. Values in config.json (project root) override defaults."""

import json
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "stockai.db"
CONFIG_PATH = PROJECT_ROOT / "config.json"


@dataclass
class Config:
    # --- Simulation ---
    starting_cash: float = 100_000.0          # CAD
    max_position_pct: float = 0.20            # max cost basis per ticker, as % of equity
    max_adv_pct: float = 0.05                 # max order notional vs 20-day avg dollar volume
    min_price: float = 0.50                   # reject ultra-penny stocks
    slippage_bps: float = 15.0                # fallback slippage when no live bid/ask
    # IBKR Canada fixed pricing (the realistic API broker for a future live version)
    commission_per_share: float = 0.01
    commission_min: float = 1.00
    commission_max_pct: float = 0.005         # capped at 0.5% of trade value
    allowed_suffixes: tuple = (".TO", ".V")   # TSX and TSX Venture

    # --- Benchmarks ---
    benchmark_sp500_cad: str = "ZSP.TO"       # BMO S&P 500 ETF (CAD) — the "beat the S&P" yardstick
    benchmark_tsx: str = "^GSPTSE"            # S&P/TSX Composite

    # --- Brain ---
    backend: str = "auto"                     # auto | api | claude-code
    model: str = "claude-opus-5"              # model for the API backend
    cc_model: str = "opus"                    # model for the claude-code backend
    effort: str = "high"                      # low | medium | high | xhigh | max
    checkin_model: str = "sonnet"             # cheaper model for 30-min check-ins
    checkin_max_searches: int = 6
    max_tokens: int = 16000
    max_web_searches: int = 15
    max_assistant_turns: int = 60             # safety cap per session
    max_pause_restarts: int = 5

    extras: dict = field(default_factory=dict)


def load_config() -> Config:
    cfg = Config()
    if CONFIG_PATH.exists():
        try:
            overrides = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            for k, v in overrides.items():
                if hasattr(cfg, k):
                    setattr(cfg, k, v)
                else:
                    cfg.extras[k] = v
        except (json.JSONDecodeError, OSError) as e:
            print(f"[config] warning: could not read config.json ({e}); using defaults")
    DATA_DIR.mkdir(exist_ok=True)
    return cfg

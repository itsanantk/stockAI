# stockAI — AI trading agent for the Canadian stock market

An autonomous AI portfolio manager (Claude Opus 5 + live web search) that trades
TSX/TSX-Venture stocks in a **realistic paper-trading simulation**: real market
prices, real commissions and spreads, real market hours. The goal: beat the
S&P 500 (measured as **ZSP.TO**, the S&P 500 ETF in CAD) with swing trades that
pay off in days to one month.

## How it works

- **Paper broker** (`stockai/broker.py`, SQLite in `data/stockai.db`)
  - Starts with **$100,000 CAD**.
  - Fills at real prices: crosses the live bid/ask when available, otherwise
    last price ± 15 bps slippage. Commissions mimic Interactive Brokers Canada
    fixed pricing ($0.01/share, min $1.00, capped at 0.5% of trade value) —
    the broker a future real-money version would use, so paper results
    translate directly.
  - Enforces market hours (9:30–16:00 ET, TSX holidays). Orders placed while
    closed queue as **market-on-open** and fill at the next session's open.
  - Hard risk rules the AI cannot override: long-only, CAD listings only,
    max 20% of equity per position, order size ≤ 5% of the stock's 20-day
    average dollar volume, min price $0.50.
- **AI brain** (`stockai/brain.py`) — Claude with tools: portfolio, quotes,
  price history, market movers scan, buy, sell, persistent notes (memory
  between sessions), and **live web search** for news/catalyst research.
- **Benchmarking** (`stockai/report.py`) — every run snapshots equity alongside
  ZSP.TO and the TSX Composite; `report` shows your alpha vs the S&P 500.

## Setup

```powershell
pip install -r requirements.txt
python agent.py init
```

### How the AI is powered (backends)

`backend` in `config.json` (default `"auto"`):

| backend | What it uses | Needs |
|---|---|---|
| `api` | Anthropic API (Claude Opus 5 + server-side web search) | `ANTHROPIC_API_KEY` **with credits** |
| `claude-code` | Your installed Claude Code CLI + its login | A Claude subscription (no API credits) |
| `auto` | Tries `api`, falls back to `claude-code` on billing/auth errors | either |

Both backends run the identical system prompt and trading tools. Your current
API key has no credits, so sessions run on your Claude Code subscription.

## Usage

```powershell
python agent.py run                 # one full AI trading session (research + trades)
python agent.py run -m "focus on gold miners today"   # optional steer
python agent.py dashboard           # generate + open the web dashboard
python agent.py report              # performance vs S&P 500 + TSX
python agent.py portfolio           # quick position view
python agent.py trades              # trade log with the AI's written reasons
python agent.py quote SHOP          # live quote
```

The **dashboard** (`data/dashboard.html`, auto-refreshed after every run) is the
"website": equity curve vs the S&P 500 and TSX indexed to inception, stat tiles
with your alpha, open positions, pending orders, the full trade log with the
AI's written reasoning, and its latest memory note. Light/dark mode follows
your system.

A session typically: reviews positions and news on holdings, scans movers,
web-searches for catalysts, places trades with written theses, and saves notes
for its next session.

## Run it in the cloud (fully self-running + hosted dashboard)

The repo ships a GitHub Actions workflow (`.github/workflows/trade.yml`) that
runs sessions automatically twice per trading day on GitHub's servers — using
**your Claude subscription** — commits the portfolio state back to the repo,
generates the daily summary, and publishes the dashboard to **GitHub Pages**
(your live "website", e.g. `https://<you>.github.io/stockAI/`). This is separate
from a personal `<you>.github.io` site — project sites don't conflict with it.

One-time setup (~5 minutes):

1. Create a **public** GitHub repo (Pages on free accounts requires public) and
   push this project to it.
2. In a terminal here, run `claude setup-token` and copy the long-lived token
   it prints (this bills sessions to your Claude subscription).
3. In the repo: Settings → Secrets and variables → Actions → New repository
   secret: name `CLAUDE_CODE_OAUTH_TOKEN`, paste the token.
4. Settings → Pages → Source: **GitHub Actions**.
5. Actions tab → "stockAI trading session" → **Run workflow** to test once.

After that it runs itself: sessions at ~10:35 and ~15:45 ET on weekdays
(`--skip-if-closed` makes holiday firings a no-op), the dashboard URL updates
after every session, and each afternoon run writes the daily summary.

> Why not Vercel? Vercel can serve the static dashboard, but its serverless
> functions can't run 10-minute Python sessions that spawn the Claude Code CLI,
> and there's no persistent disk for the portfolio DB. GitHub Actions provides
> the compute, the repo provides the storage, and Pages provides the hosting.

## Daily summary

`python agent.py daily` (run automatically by the cloud workflow after the
afternoon session) writes an end-of-day report — day P&L, alpha vs S&P 500,
trades with reasons, positions, and the AI's session recap — stored in the DB
and shown in the dashboard's "Daily summaries" section.

## Recommended schedule (local alternative)

Run 1–2 sessions per trading day while the market is open — e.g. **10:00**
(react to the open + fill queued orders) and **15:30** (position for the close).
Windows Task Scheduler:

```powershell
schtasks /Create /TN "stockAI-morning" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 10:00 `
  /TR "cmd /c cd /d C:\Users\itsan\Desktop\Projects\stockAI && python agent.py run >> data\run.log 2>&1"
schtasks /Create /TN "stockAI-afternoon" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 15:30 `
  /TR "cmd /c cd /d C:\Users\itsan\Desktop\Projects\stockAI && python agent.py run >> data\run.log 2>&1"
```

(Requires `ANTHROPIC_API_KEY` to be set as a user/system environment variable.)

## Configuration

Create `config.json` in the project root to override defaults, e.g.:

```json
{
  "starting_cash": 100000,
  "effort": "high",
  "max_web_searches": 15,
  "max_position_pct": 0.20
}
```

`effort` controls how hard the model thinks (`low`…`max`); `xhigh` is stronger
and pricier per session.

## Honest limitations

- Yahoo quotes are ~15 min delayed for TSX — realistic for a retail workflow,
  but the sim can't capture intraday scalping (which the mandate avoids anyway).
- Fills model spread + commissions but not partial fills or deep market impact
  (the 5%-of-ADV rule keeps orders in realistic size).
- Judge the experiment over **months, not days** — a couple of weeks of
  out/underperformance vs ZSP.TO is mostly noise.
- Each session costs real API tokens (Opus 5 + web search); expect roughly
  $1–4 per session depending on effort and search volume.

## Reset

Delete `data/stockai.db` and run `python agent.py init` again.

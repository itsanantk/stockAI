"""Local dashboard: generates a self-contained HTML page from the database.

`python agent.py dashboard` writes data/dashboard.html and opens it.
No external assets — inline CSS/JS/SVG, light + dark mode.
"""

from __future__ import annotations

import datetime as dt
import html
import json
from zoneinfo import ZoneInfo

from . import market
from .broker import Broker
from .config import Config, DATA_DIR

DASHBOARD_PATH = DATA_DIR / "dashboard.html"


def _payload(broker: Broker, cfg: Config) -> dict:
    perf = broker.performance()
    zsp0 = tsx0 = None
    for r in broker.db.execute("SELECT * FROM benchmarks"):
        if r["symbol"] == cfg.benchmark_sp500_cad:
            zsp0 = r["inception_price"]
        elif r["symbol"] == cfg.benchmark_tsx:
            tsx0 = r["inception_price"]

    series = []
    for r in broker.db.execute("SELECT * FROM snapshots ORDER BY ts"):
        series.append({
            "ts": r["ts"],
            "portfolio": round(r["equity"] / broker.starting_cash * 100, 3),
            "sp500": round(r["bench_sp500_cad"] / zsp0 * 100, 3)
            if (r["bench_sp500_cad"] and zsp0) else None,
            "tsx": round(r["bench_tsx"] / tsx0 * 100, 3)
            if (r["bench_tsx"] and tsx0) else None,
        })

    trades = [dict(r) for r in broker.db.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 60")]
    notes = broker.latest_notes(1)
    return {
        "dailies": broker.daily_summaries(7),
        "generated": dt.datetime.now(ZoneInfo("America/Toronto")).strftime("%Y-%m-%d %H:%M ET"),
        "market": market.market_status(),
        "perf": perf,
        "series": series,
        "positions": broker.positions_with_prices(),
        "pending": broker.pending(),
        "trades": trades,
        "latest_note": notes[0] if notes else None,
    }


def generate(broker: Broker, cfg: Config) -> str:
    data = _payload(broker, cfg)
    page = _TEMPLATE.replace("__DATA__", json.dumps(data, default=str)) \
                    .replace("__TITLE__", html.escape("stockAI — Canadian AI portfolio"))
    DASHBOARD_PATH.write_text(page, encoding="utf-8")
    return str(DASHBOARD_PATH)


_TEMPLATE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Autonomous AI portfolio manager trading TSX/TSXV stocks in a realistic paper simulation.">
<title>__TITLE__</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='.9em' font-size='90'%3E%F0%9F%93%88%3C/text%3E%3C/svg%3E">
<script>try{var t=localStorage.getItem("theme");if(t)document.documentElement.dataset.theme=t}catch(e){}</script>
<style>
  :root, :root[data-theme="light"] {
    color-scheme: light;
    --page:      #f6f6f3; --surface-1: #fdfdfc;
    --ink-1:     #0b0b0b; --ink-2:     #52514e; --ink-muted: #8a887f;
    --grid:      #e4e3dc; --baseline:  #c3c2b7;
    --border:    rgba(11,11,11,0.09);
    --shadow:    0 1px 2px rgba(11,11,11,0.04), 0 4px 16px rgba(11,11,11,0.03);
    --series-1:  #2a78d6; --series-2:  #eb6834; --series-3:  #1baf7a;
    --good:      #0a6e0a; --bad:       #cf3b3b; --warn: #a86a00;
    --good-bg:   rgba(10,110,10,0.08); --bad-bg: rgba(207,59,59,0.08);
    --hover:     rgba(11,11,11,0.03);
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --page:      #0c0c0c; --surface-1: #171716;
    --ink-1:     #f4f4f2; --ink-2:     #c3c2b7; --ink-muted: #8a887f;
    --grid:      #292927; --baseline:  #3a3a37;
    --border:    rgba(255,255,255,0.09);
    --shadow:    0 1px 2px rgba(0,0,0,0.3);
    --series-1:  #4d94e8; --series-2:  #e8703f; --series-3:  #23b981;
    --good:      #3fbf3f; --bad:       #e05c5c; --warn: #d99a2b;
    --good-bg:   rgba(63,191,63,0.13); --bad-bg: rgba(224,92,92,0.13);
    --hover:     rgba(255,255,255,0.04);
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      color-scheme: dark;
      --page:      #0c0c0c; --surface-1: #171716;
      --ink-1:     #f4f4f2; --ink-2:     #c3c2b7; --ink-muted: #8a887f;
      --grid:      #292927; --baseline:  #3a3a37;
      --border:    rgba(255,255,255,0.09);
      --shadow:    0 1px 2px rgba(0,0,0,0.3);
      --series-1:  #4d94e8; --series-2:  #e8703f; --series-3:  #23b981;
      --good:      #3fbf3f; --bad:       #e05c5c; --warn: #d99a2b;
      --good-bg:   rgba(63,191,63,0.13); --bad-bg: rgba(224,92,92,0.13);
      --hover:     rgba(255,255,255,0.04);
    }
  }
  * { box-sizing: border-box; margin: 0; }
  body {
    background: var(--page); color: var(--ink-1);
    font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    padding: 28px 24px 12px; max-width: 1080px; margin: 0 auto;
    -webkit-text-size-adjust: 100%;
  }
  header { display: flex; align-items: flex-start; justify-content: space-between;
           gap: 14px; flex-wrap: wrap; }
  .brand { font-size: 23px; font-weight: 750; letter-spacing: -0.02em; }
  .brand .ai { color: var(--series-1); }
  .sub { color: var(--ink-muted); font-size: 12.5px; margin-top: 5px; }
  .hdr-right { display: flex; align-items: center; gap: 8px; }
  .pill { display: inline-flex; align-items: center; gap: 7px;
          background: var(--surface-1); border: 1px solid var(--border);
          border-radius: 999px; padding: 6px 13px; font-size: 12.5px;
          color: var(--ink-2); white-space: nowrap; }
  .pill .dot { width: 8px; height: 8px; border-radius: 50%; }
  #themebtn { background: var(--surface-1); border: 1px solid var(--border);
              border-radius: 999px; padding: 6px 13px; font-size: 12.5px;
              color: var(--ink-2); cursor: pointer; font-family: inherit; }
  #themebtn:hover { color: var(--ink-1); }
  h2 { font-size: 11.5px; font-weight: 650; color: var(--ink-muted);
       text-transform: uppercase; letter-spacing: .07em;
       display: flex; align-items: center; gap: 8px; margin: 0 0 12px; }
  h2::before { content: ""; width: 6px; height: 6px; border-radius: 2px;
               background: var(--series-1); flex: none; }
  .card { background: var(--surface-1); border: 1px solid var(--border);
          border-radius: 14px; padding: 18px 20px; margin-top: 16px;
          box-shadow: var(--shadow); }
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px,1fr));
           gap: 12px; margin-top: 20px; }
  .tile { background: var(--surface-1); border: 1px solid var(--border);
          border-radius: 14px; padding: 15px 17px 13px; box-shadow: var(--shadow); }
  .tile .label { font-size: 11px; font-weight: 600; color: var(--ink-muted);
                 text-transform: uppercase; letter-spacing: .06em; }
  .tile .value { font-size: 27px; font-weight: 700; letter-spacing: -0.01em;
                 margin-top: 6px; font-variant-numeric: tabular-nums; }
  .tile .delta { font-size: 12.5px; margin-top: 3px; color: var(--ink-2); }
  .up   { color: var(--good); }
  .down { color: var(--bad); }
  .chart-head { display: flex; align-items: baseline; justify-content: space-between;
                gap: 10px; flex-wrap: wrap; }
  .legend { display: flex; gap: 16px; font-size: 12.5px; color: var(--ink-2);
            margin-bottom: 10px; flex-wrap: wrap; }
  .legend .swatch { display: inline-block; width: 10px; height: 10px;
                    border-radius: 3px; margin-right: 5px; vertical-align: -1px; }
  #chartwrap { position: relative; overflow-x: auto; }
  #chart { width: 100%; height: auto; min-width: 640px; display: block; }
  #tooltip { position: absolute; pointer-events: none; display: none;
             background: var(--surface-1); border: 1px solid var(--border);
             border-radius: 10px; padding: 8px 11px; font-size: 12px;
             box-shadow: 0 6px 20px rgba(0,0,0,.15); white-space: nowrap; z-index: 5; }
  #tooltip .t { color: var(--ink-muted); margin-bottom: 3px; }
  .tablewrap { overflow-x: auto; margin: 0 -4px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; color: var(--ink-muted); font-weight: 600; font-size: 11px;
       text-transform: uppercase; letter-spacing: .05em;
       border-bottom: 1px solid var(--baseline); padding: 7px 9px; white-space: nowrap; }
  td { padding: 9px; border-bottom: 1px solid var(--grid);
       font-variant-numeric: tabular-nums; vertical-align: top; }
  tbody tr:last-child td { border-bottom: 0; }
  tbody tr:hover td { background: var(--hover); }
  td.tick { font-weight: 650; }
  td.reason { color: var(--ink-2); font-size: 12.5px; min-width: 260px; max-width: 460px; }
  .num { text-align: right; }
  .nw { white-space: nowrap; }
  .side { display: inline-block; font-size: 10.5px; font-weight: 750;
          letter-spacing: .05em; padding: 2.5px 9px; border-radius: 999px; }
  .side.b { color: var(--good); background: var(--good-bg); }
  .side.s { color: var(--bad); background: var(--bad-bg); }
  .reason .md.clamp { display: -webkit-box; -webkit-line-clamp: 3;
                      -webkit-box-orient: vertical; overflow: hidden; }
  .morebtn { background: none; border: none; padding: 2px 0 0; cursor: pointer;
             color: var(--series-1); font-size: 12px; font-family: inherit; }
  .morebtn:hover { text-decoration: underline; }
  details.day { border: 1px solid var(--border); border-radius: 10px;
                padding: 0 14px; margin: 8px 0; }
  details.day summary { cursor: pointer; font-weight: 650; font-size: 13.5px;
                        padding: 11px 0; list-style: none; user-select: none; }
  details.day summary::-webkit-details-marker { display: none; }
  details.day summary::before { content: "\25B8"; display: inline-block; margin-right: 9px;
                                color: var(--ink-muted); transition: transform .15s; }
  details.day[open] summary::before { transform: rotate(90deg); }
  details.day[open] { padding-bottom: 10px; }
  pre.note { white-space: pre-wrap; font-family: inherit; font-size: 13px;
             color: var(--ink-2); line-height: 1.5; }
  .empty { color: var(--ink-muted); font-size: 13px; }
  .md { font-size: 13px; color: var(--ink-2); line-height: 1.55;
        overflow-wrap: break-word; }
  .md p { margin: 2px 0; }
  .md .md-h1 { font-size: 15px; font-weight: 650; color: var(--ink-1); margin: 10px 0 4px; }
  .md .md-h2 { font-size: 13.5px; font-weight: 650; color: var(--ink-1); margin: 10px 0 4px; }
  .md .md-h3, .md .md-h4 { font-size: 13px; font-weight: 600; color: var(--ink-1); margin: 8px 0 3px; }
  .md ul, .md ol { margin: 4px 0 6px 20px; padding: 0; }
  .md li { margin: 3px 0; }
  .md .md-gap { height: 8px; }
  .md a { color: var(--series-1); text-decoration: none; }
  .md a:hover { text-decoration: underline; }
  .md b { color: var(--ink-1); }
  .md i b, .md b i { color: var(--ink-1); }
  .md code { background: var(--grid); border-radius: 4px; padding: 0 4px; }
  .md hr { border: 0; border-top: 1px solid var(--grid); margin: 8px 0; }
  td.reason .md { font-size: 12.5px; }
  footer { text-align: center; color: var(--ink-muted); font-size: 12px;
           margin: 30px 0 14px; }
  footer a { color: var(--ink-2); }
  @media (max-width: 640px) {
    body { padding: 16px 12px 8px; }
    .card { padding: 14px; border-radius: 12px; }
    .tile .value { font-size: 22px; }
    .brand { font-size: 20px; }
  }
</style></head>
<body>
<header>
  <div>
    <div class="brand">stock<span class="ai">AI</span></div>
    <div class="sub" id="subline"></div>
  </div>
  <div class="hdr-right">
    <span class="pill" id="mktpill"></span>
    <button id="themebtn" title="Toggle theme"></button>
  </div>
</header>

<div class="tiles" id="tiles"></div>

<div class="card">
  <div class="chart-head">
    <h2>Performance, indexed to 100 at inception</h2>
    <div class="legend" id="legend"></div>
  </div>
  <div id="chartwrap"><div id="tooltip"></div>
    <svg id="chart" viewBox="0 0 1000 320" height="320"></svg>
  </div>
</div>

<div class="card"><h2>Open positions</h2><div id="positions"></div></div>
<div class="card"><h2>Pending market-on-open orders</h2><div id="pending"></div></div>
<div class="card"><h2>Daily summaries</h2><div id="dailies"></div></div>
<div class="card"><h2>Trade log (AI reasoning included)</h2><div id="trades"></div></div>
<div class="card"><h2>Latest AI note (its memory)</h2><div id="note"></div></div>

<footer>AI paper-trading experiment · not financial advice · quotes ~15 min delayed ·
<a href="https://github.com/itsanantk/stockAI" target="_blank" rel="noopener">GitHub</a></footer>

<script>
const D = __DATA__;
const fmt$ = x => x == null ? "-" : x.toLocaleString("en-CA", {style:"currency", currency:"CAD"});
const pct = x => (x >= 0 ? "+" : "") + x.toFixed(2) + "%";
const esc = s => String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

/* ---- theme toggle: auto -> dark -> light ---- */
(function () {
  const btn = document.getElementById("themebtn");
  const order = ["auto", "dark", "light"];
  const label = {auto: "◑ Auto", dark: "☽ Dark", light: "☀ Light"};
  let cur = document.documentElement.dataset.theme || "auto";
  const apply = () => {
    if (cur === "auto") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = cur;
    btn.textContent = label[cur];
    try { cur === "auto" ? localStorage.removeItem("theme")
                         : localStorage.setItem("theme", cur); } catch (e) {}
  };
  btn.addEventListener("click", () => {
    cur = order[(order.indexOf(cur) + 1) % order.length]; apply();
  });
  apply();
})();

/* Minimal markdown renderer for AI-written notes/summaries (escapes first). */
function mdInline(s) {
  s = esc(s);
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
                '<a href="$2" target="_blank" rel="noopener">$1</a>');
  s = s.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
  s = s.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<i>$2</i>");
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
  return s;
}
function mdBlock(text) {
  const lines = String(text).split(/\r?\n/);
  let out = "", list = null;
  const closeList = () => { if (list) { out += `</${list}>`; list = null; } };
  for (const raw of lines) {
    const line = raw.trimEnd();
    const h = line.match(/^(#{1,4})\s+(.*)/);
    const ul = line.match(/^\s*[-•]\s+(.*)/);
    const ol = line.match(/^\s*\d+[.)]\s+(.*)/);
    if (h) { closeList(); out += `<div class="md-h${h[1].length}">${mdInline(h[2])}</div>`; }
    else if (/^\s*-{3,}\s*$/.test(line)) { closeList(); out += "<hr>"; }
    else if (ul) { if (list !== "ul") { closeList(); out += "<ul>"; list = "ul"; }
                   out += `<li>${mdInline(ul[1])}</li>`; }
    else if (ol) { if (list !== "ol") { closeList(); out += "<ol>"; list = "ol"; }
                   out += `<li>${mdInline(ol[1])}</li>`; }
    else if (line.trim() === "") { closeList(); out += '<div class="md-gap"></div>'; }
    else { closeList(); out += `<p>${mdInline(line)}</p>`; }
  }
  closeList();
  return `<div class="md">${out}</div>`;
}

document.getElementById("subline").textContent =
  `Autonomous AI portfolio manager · TSX/TSXV · updated ${D.generated}`;

/* ---- market status pill ---- */
(function () {
  const m = D.market;
  const col = m.is_open ? "var(--good)"
            : m.detail === "pre-market" ? "var(--warn)" : "var(--ink-muted)";
  document.getElementById("mktpill").innerHTML =
    `<span class="dot" style="background:${col}"></span>Market ${esc(m.session)} · ${esc(m.detail)}`;
})();

/* ---- stat tiles ---- */
const perf = D.perf;
const sp = perf.benchmarks["ZSP.TO"] || null;
const alpha = perf.alpha_vs_sp500_pct;

/* equity change vs the last snapshot of the previous day (~prior close) */
let dayTxt = "", dayCls = "";
if (D.series.length > 1) {
  const last = D.series[D.series.length - 1];
  const prior = [...D.series].reverse().find(p => p.ts.slice(0, 10) !== last.ts.slice(0, 10));
  if (prior && prior.portfolio) {
    const chg = (last.portfolio / prior.portfolio - 1) * 100;
    dayTxt = `${pct(chg)} today`; dayCls = chg >= 0 ? "up" : "down";
  }
}

const tiles = [
  {label: "Equity", value: fmt$(perf.equity),
   delta: pct(perf.return_pct) + " since inception", cls: perf.return_pct >= 0 ? "up" : "down",
   delta2: dayTxt, cls2: dayCls},
  {label: "Cash", value: fmt$(perf.cash),
   delta: (100 * perf.cash / perf.equity).toFixed(0) + "% of equity", cls: ""},
  {label: "S&P 500 (ZSP.TO)", value: sp ? pct(sp.return_pct) : "-",
   delta: "same period", cls: sp && sp.return_pct >= 0 ? "up" : "down"},
  {label: "Alpha vs S&P 500", value: alpha == null ? "-" : pct(alpha),
   delta: alpha == null ? "" : (alpha >= 0 ? "beating the index" : "trailing the index"),
   cls: alpha >= 0 ? "up" : "down"},
];
document.getElementById("tiles").innerHTML = tiles.map(t =>
  `<div class="tile"><div class="label">${t.label}</div><div class="value">${t.value}</div>
   <div class="delta ${t.cls}">${t.delta}</div>` +
  (t.delta2 ? `<div class="delta ${t.cls2}">${t.delta2}</div>` : "") +
  `</div>`).join("");

/* ---- chart ---- */
const SERIES = [
  {key: "portfolio", name: "Portfolio", color: "var(--series-1)"},
  {key: "sp500",     name: "S&P 500 (ZSP.TO)", color: "var(--series-2)"},
  {key: "tsx",       name: "TSX Composite", color: "var(--series-3)"},
];
document.getElementById("legend").innerHTML = SERIES.map(s =>
  `<span><span class="swatch" style="background:${s.color}"></span>${s.name}</span>`).join("");

const svg = document.getElementById("chart");
const W = 1000, H = 320, M = {t: 16, r: 158, b: 28, l: 46};
const pts = D.series.map(r => ({...r, t: new Date(r.ts.replace(" ", "T")).getTime()}));

function drawChart() {
  if (pts.length === 0) { svg.outerHTML = '<div class="empty">No snapshots yet — run a session.</div>'; return; }
  const xs = pts.map(p => p.t);
  let vals = [];
  for (const s of SERIES) for (const p of pts) if (p[s.key] != null) vals.push(p[s.key]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  let lo = Math.min(...vals, 99.5), hi = Math.max(...vals, 100.5);
  const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
  const X = t => x0 === x1 ? (M.l + (W - M.l - M.r) / 2) : M.l + (t - x0) / (x1 - x0) * (W - M.l - M.r);
  const Y = v => M.t + (hi - v) / (hi - lo) * (H - M.t - M.b);
  let g = `<defs><linearGradient id="gradP" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="var(--series-1)" stop-opacity="0.16"/>
    <stop offset="1" stop-color="var(--series-1)" stop-opacity="0"/></linearGradient></defs>`;
  // gridlines + y ticks
  const steps = 4;
  for (let i = 0; i <= steps; i++) {
    const v = lo + (hi - lo) * i / steps, y = Y(v);
    g += `<line x1="${M.l}" y1="${y}" x2="${W - M.r}" y2="${y}" stroke="var(--grid)" stroke-width="1"/>`;
    g += `<text x="${M.l - 8}" y="${y + 4}" text-anchor="end" font-size="11" fill="var(--ink-muted)">${v.toFixed(1)}</text>`;
  }
  // baseline at 100
  if (lo < 100 && hi > 100)
    g += `<line x1="${M.l}" y1="${Y(100)}" x2="${W - M.r}" y2="${Y(100)}" stroke="var(--baseline)" stroke-width="1" stroke-dasharray="4 3"/>`;
  // x ticks: first, middle, last — show times when the span is under 2 days
  const shortSpan = (x1 - x0) < 48 * 3600 * 1000;
  const tickLabel = p => shortSpan ? p.ts.slice(5, 16) : p.ts.slice(0, 10);
  const tickIdx = [...new Set([0, Math.floor((pts.length - 1) / 2), pts.length - 1])];
  let lastTickX = -1e9;
  for (const i of tickIdx) {
    const tx = X(pts[i].t);
    if (tx - lastTickX < 80) continue;
    lastTickX = tx;
    g += `<text x="${tx}" y="${H - 8}" text-anchor="middle" font-size="11" fill="var(--ink-muted)">${tickLabel(pts[i])}</text>`;
  }
  // gradient area under the portfolio line
  const ppts = pts.filter(p => p.portfolio != null);
  if (ppts.length > 1) {
    const area = ppts.map((p, i) => (i === 0 ? "M" : "L") + X(p.t).toFixed(1) + " " + Y(p.portfolio).toFixed(1)).join(" ")
      + ` L ${X(ppts[ppts.length - 1].t).toFixed(1)} ${H - M.b} L ${X(ppts[0].t).toFixed(1)} ${H - M.b} Z`;
    g += `<path d="${area}" fill="url(#gradP)" stroke="none"/>`;
  }
  // lines
  const endLabels = [];
  for (const s of SERIES) {
    const path = pts.filter(p => p[s.key] != null)
      .map((p, i) => (i === 0 ? "M" : "L") + X(p.t).toFixed(1) + " " + Y(p[s.key]).toFixed(1)).join(" ");
    if (!path) continue;
    g += `<path d="${path}" fill="none" stroke="${s.color}" stroke-width="2.25" stroke-linejoin="round" stroke-linecap="round"/>`;
    const lastPt = [...pts].reverse().find(p => p[s.key] != null);
    if (pts.length === 1 || x0 === x1)
      g += `<circle cx="${X(lastPt.t)}" cy="${Y(lastPt[s.key])}" r="4" fill="${s.color}"/>`;
    endLabels.push({y: Y(lastPt[s.key]), color: s.color,
                    text: `${s.name.split(" (")[0]} ${lastPt[s.key].toFixed(1)}`});
  }
  // end labels with collision avoidance: sort by y, enforce 15px spacing
  endLabels.sort((a, b) => a.y - b.y);
  for (let i = 1; i < endLabels.length; i++)
    if (endLabels[i].y - endLabels[i - 1].y < 15) endLabels[i].y = endLabels[i - 1].y + 15;
  for (const l of endLabels) {
    g += `<circle cx="${W - M.r + 10}" cy="${l.y}" r="3.5" fill="${l.color}"/>`;
    g += `<text x="${W - M.r + 18}" y="${l.y + 4}" font-size="12" font-weight="600" fill="var(--ink-1)">${l.text}</text>`;
  }
  // crosshair group (populated on hover)
  g += `<g id="hoverg"></g>`;
  svg.innerHTML = g;

  // hover layer
  const tip = document.getElementById("tooltip");
  svg.addEventListener("mousemove", ev => {
    const rect = svg.getBoundingClientRect();
    const mx = (ev.clientX - rect.left) * (W / rect.width);
    let best = null, bd = 1e18;
    for (const p of pts) { const d = Math.abs(X(p.t) - mx); if (d < bd) { bd = d; best = p; } }
    if (!best) return;
    const hx = X(best.t);
    let hg = `<line x1="${hx}" y1="${M.t}" x2="${hx}" y2="${H - M.b}" stroke="var(--baseline)" stroke-width="1"/>`;
    for (const s of SERIES) if (best[s.key] != null)
      hg += `<circle cx="${hx}" cy="${Y(best[s.key])}" r="4.5" fill="${s.color}" stroke="var(--surface-1)" stroke-width="2"/>`;
    document.getElementById("hoverg").innerHTML = hg;
    tip.style.display = "block";
    tip.innerHTML = `<div class="t">${best.ts}</div>` + SERIES.map(s =>
      best[s.key] == null ? "" :
      `<div><span class="swatch" style="background:${s.color};display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:5px"></span>${s.name}: <b>${best[s.key].toFixed(2)}</b></div>`).join("");
    const wrap = document.getElementById("chartwrap").getBoundingClientRect();
    let tx = ev.clientX - wrap.left + 14;
    if (tx + 180 > wrap.width) tx -= 200;
    tip.style.left = tx + "px";
    tip.style.top = (ev.clientY - wrap.top - 10) + "px";
  });
  svg.addEventListener("mouseleave", () => {
    tip.style.display = "none";
    document.getElementById("hoverg").innerHTML = "";
  });
}
drawChart();

/* ---- tables ---- */
const sidePill = s => `<span class="side ${s.toLowerCase() === "buy" ? "b" : "s"}">${esc(s.toUpperCase())}</span>`;

function table(id, headers, rows, empty) {
  const el = document.getElementById(id);
  if (!rows.length) { el.innerHTML = `<div class="empty">${empty}</div>`; return; }
  el.innerHTML = `<div class="tablewrap"><table><thead><tr>${headers.map(h =>
    `<th class="${h.num ? "num" : ""}">${h.t}</th>`).join("")}</tr></thead><tbody>` +
    rows.map(r => `<tr>${r.map((c, i) =>
      `<td class="${headers[i].num ? "num" : ""} ${headers[i].cls || ""} ${c && c.cls ? c.cls : ""}">${c && c.v !== undefined ? c.v : c}</td>`).join("")}</tr>`).join("") +
    "</tbody></table></div>";
}

table("positions",
  [{t:"Ticker"},{t:"Shares",num:1},{t:"Avg cost",num:1},{t:"Last",num:1},{t:"Value",num:1},{t:"P&L",num:1},{t:"P&L %",num:1},{t:"Today",num:1}],
  D.positions.map(p => [
    {v: esc(p.ticker), cls: "tick"}, p.shares, p.avg_cost.toFixed(2),
    p.last != null ? p.last.toFixed(2) : "-",
    p.market_value != null ? fmt$(p.market_value) : "-",
    p.unrealized_pnl != null ? {v: fmt$(p.unrealized_pnl), cls: p.unrealized_pnl >= 0 ? "up" : "down"} : "-",
    p.unrealized_pct != null ? {v: pct(p.unrealized_pct), cls: p.unrealized_pct >= 0 ? "up" : "down"} : "-",
    p.day_change_pct != null ? {v: pct(p.day_change_pct), cls: p.day_change_pct >= 0 ? "up" : "down"} : "-",
  ]), "No open positions — the account is in cash.");

table("pending",
  [{t:"Placed",cls:"nw"},{t:"Side"},{t:"Ticker"},{t:"Size",num:1},{t:"Reason",cls:"reason"}],
  D.pending.map(o => [esc(o.created_ts), sidePill(o.side), {v: esc(o.ticker), cls: "tick"},
    o.amount_cad ? fmt$(o.amount_cad) : o.shares + " sh",
    `<div class="md">${mdInline(o.reason || "")}</div>`]),
  "None.");

table("trades",
  [{t:"Time",cls:"nw"},{t:"Side"},{t:"Ticker"},{t:"Shares",num:1},{t:"Price",num:1},{t:"Realized",num:1},{t:"Reason",cls:"reason"}],
  D.trades.map(t => [esc(t.ts), sidePill(t.side), {v: esc(t.ticker), cls: "tick"}, t.shares,
    Number(t.price).toFixed(3),
    t.realized_pnl != null ? {v: fmt$(t.realized_pnl), cls: t.realized_pnl >= 0 ? "up" : "down"} : "-",
    `<div class="md">${mdInline(t.reason || "")}</div>`]),
  "No trades yet.");

/* clamp long trade theses to 3 lines with a more/less toggle */
document.querySelectorAll("td.reason .md").forEach(el => {
  el.classList.add("clamp");
  if (el.scrollHeight > el.clientHeight + 4) {
    const b = document.createElement("button");
    b.className = "morebtn"; b.textContent = "more ▾";
    b.addEventListener("click", () => {
      const open = !el.classList.toggle("clamp");
      b.textContent = open ? "less ▴" : "more ▾";
    });
    el.after(b);
  } else {
    el.classList.remove("clamp");
  }
});

document.getElementById("dailies").innerHTML = (D.dailies && D.dailies.length)
  ? D.dailies.map((d, i) =>
      `<details class="day" ${i === 0 ? "open" : ""}><summary>${esc(d.date)}</summary>
       ${mdBlock(d.content)}</details>`).join("")
  : '<div class="empty">No daily summaries yet — generated by <code>python agent.py daily</code> after the close.</div>';

document.getElementById("note").innerHTML = D.latest_note
  ? `<div class="sub">${esc(D.latest_note.ts)}</div>${mdBlock(D.latest_note.content)}`
  : '<div class="empty">No notes yet.</div>';
</script>
</body></html>
"""

"""
packages/engine/statistics.py
──────────────────────────────
Reads GitData vault, generates analytics reports (JSON) and a
self-contained GitHub Pages dashboard (HTML).

Usage
-----
    python -m packages.engine.statistics \\
        --vault  /path/to/vault-clone \\
        --output /path/to/output-dir

Output structure
-----------------
    output/
      reports/
        summary.json     — portfolio-level totals
        top_repos.json   — repos ranked by lifetime clones
        trends.json      — week-over-week deltas per repo
      docs/
        index.html       — fully self-contained dashboard (no build step)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from .schema import MonthLedger, VaultIndex

logger = logging.getLogger(__name__)


# ── Data loading ──────────────────────────────────────────────────────────────

def _load_index(vault: Path) -> VaultIndex:
    p = vault / "index.json"
    if not p.exists():
        raise FileNotFoundError(f"index.json not found in vault at {vault}")
    return VaultIndex.model_validate(json.loads(p.read_text()))


def _load_month_ledger(vault: Path, owner: str, repo: str, month: str) -> MonthLedger | None:
    p = vault / "data" / owner / repo / month[:4] / f"{month}.json"
    if not p.exists():
        return None
    try:
        return MonthLedger.model_validate(json.loads(p.read_text()))
    except Exception as e:
        logger.warning("Could not parse %s: %s", p, e)
        return None


def _load_all_ledgers(vault: Path, full_repo: str) -> list[MonthLedger]:
    owner, repo = full_repo.split("/", 1)
    ledgers: list[MonthLedger] = []
    repo_dir = vault / "data" / owner / repo
    if not repo_dir.exists():
        return ledgers
    for year_dir in sorted(repo_dir.iterdir()):
        for f in sorted(year_dir.glob("*.json")):
            try:
                ledgers.append(MonthLedger.model_validate(json.loads(f.read_text())))
            except Exception as e:
                logger.warning("Could not parse %s: %s", f, e)
    return ledgers


# ── Report generators ─────────────────────────────────────────────────────────

def _generate_summary(index: VaultIndex, owner: str = "") -> dict[str, Any]:
    repos = {
        k: v for k, v in index.repos.items()
        if not owner or k.split("/")[0] == owner
    }
    total_clones  = sum(m.lifetime_clones  for m in repos.values())
    total_uniques = sum(m.lifetime_uniques for m in repos.values())
    most_active   = max(repos, key=lambda r: repos[r].lifetime_clones) if repos else None

    return {
        "generated_at":   datetime.now(tz=UTC).isoformat(),
        "total_repos":    len(repos),
        "lifetime_clones":  total_clones,
        "lifetime_uniques": total_uniques,
        "most_active_repo": most_active,
    }


def _generate_top_repos(index: VaultIndex, owner: str = "") -> list[dict[str, Any]]:
    rows = []
    for full_repo, meta in index.repos.items():
        # Skip repos not owned by the user (stale org entries in vault)
        if owner and full_repo.split("/")[0] != owner:
            continue
        rows.append({
            "repo":             full_repo,
            "description":      meta.description,
            "lifetime_clones":  meta.lifetime_clones,
            "lifetime_uniques": meta.lifetime_uniques,
            "first_date":       meta.first_date,
            "last_date":        meta.last_date,
            "last_harvest":     meta.last_harvest,
            "available_months": len(meta.available_months),
            "stars":            meta.stars,
            "forks":            meta.forks,
            "watchers":         meta.watchers,
            "open_issues":      meta.open_issues,
            "language":         meta.language,
            "topics":           meta.topics,
        })
    return sorted(rows, key=lambda r: r["lifetime_clones"], reverse=True)


def _generate_trends(vault: Path, index: VaultIndex) -> list[dict[str, Any]]:
    """
    For each repo, compute 7-day rolling clone and view totals for the most
    recent month, then compare to the prior 7 days. Returns a list of
    {repo, current_week_clones, prior_week_clones, delta_pct} records.
    """
    today     = date.today()
    week_end  = today
    week_start      = today - timedelta(days=6)
    prior_end   = week_start - timedelta(days=1)
    prior_start = prior_end  - timedelta(days=6)

    trends = []
    for full_repo in index.repos:
        ledgers = _load_all_ledgers(vault, full_repo)
        clone_by_date: dict[str, int] = {}
        view_by_date:  dict[str, int] = {}
        for ledger in ledgers:
            for entry in ledger.clones:
                clone_by_date[entry.date.isoformat()] = entry.count
            for entry in ledger.views:
                view_by_date[entry.date.isoformat()] = entry.count

        def _sum_range(d: dict[str, int], start: date, end: date) -> int:
            total = 0
            cur = start
            while cur <= end:
                total += d.get(cur.isoformat(), 0)
                cur += timedelta(days=1)
            return total

        cur_clones  = _sum_range(clone_by_date, week_start, week_end)
        prev_clones = _sum_range(clone_by_date, prior_start, prior_end)
        cur_views   = _sum_range(view_by_date,  week_start, week_end)
        prev_views  = _sum_range(view_by_date,  prior_start, prior_end)

        def _pct(cur: int, prev: int) -> float | None:
            if prev == 0:
                return None
            return round((cur - prev) / prev * 100, 1)

        trends.append({
            "repo":               full_repo,
            "current_week_clones":  cur_clones,
            "prior_week_clones":    prev_clones,
            "clone_delta_pct":      _pct(cur_clones, prev_clones),
            "current_week_views":   cur_views,
            "prior_week_views":     prev_views,
            "view_delta_pct":       _pct(cur_views, prev_views),
        })

    return sorted(trends, key=lambda r: r["current_week_clones"], reverse=True)


def _collect_chart_data(vault: Path, index: VaultIndex, lookback_months: int = 12) -> list[dict[str, Any]]:
    """
    Aggregate daily clone + view data across all repos for the last N months.
    Returns a dict keyed by date → {clones, views}.
    """
    today    = date.today()
    cutoff   = today - timedelta(days=365)

    clone_by_date: dict[str, int] = {}
    view_by_date:  dict[str, int] = {}

    for full_repo in index.repos:
        for ledger in _load_all_ledgers(vault, full_repo):
            for entry in ledger.clones:
                d = entry.date.isoformat()
                if entry.date >= cutoff:
                    clone_by_date[d] = clone_by_date.get(d, 0) + entry.count
            for entry in ledger.views:
                d = entry.date.isoformat()
                if entry.date >= cutoff:
                    view_by_date[d] = view_by_date.get(d, 0) + entry.count

    all_dates = sorted(set(clone_by_date) | set(view_by_date))
    return [
        {"date": d, "clones": clone_by_date.get(d, 0), "views": view_by_date.get(d, 0)}
        for d in all_dates
    ]


# ── HTML template ─────────────────────────────────────────────────────────────

def _render_html(
    summary: dict[str, Any],
    top_repos: list[dict[str, Any]],
    trends: list[dict[str, Any]],
    chart_data: list[dict[str, Any]],
    owner: str,
) -> str:
    summary_json    = json.dumps(summary,    separators=(",", ":"))
    top_repos_json  = json.dumps(top_repos,  separators=(",", ":"))
    trends_json     = json.dumps(trends,     separators=(",", ":"))
    chart_data_json = json.dumps(chart_data, separators=(",", ":"))
    generated_at    = summary.get("generated_at", "")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{owner} · GitEternal Statistics</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    :root {{
      --bg:        #0d1117;
      --surface:   #161b22;
      --border:    #30363d;
      --text:      #c9d1d9;
      --muted:     #8b949e;
      --blue:      #58a6ff;
      --green:     #3fb950;
      --red:       #f85149;
      --purple:    #bc8cff;
      --orange:    #d29922;
      --radius:    8px;
      --shadow:    0 1px 3px rgba(0,0,0,.4);
    }}

    body {{
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif;
      font-size: 14px;
      line-height: 1.5;
      min-height: 100vh;
    }}

    /* Layout */
    .header {{
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      padding: 1rem 1.5rem;
      display: flex;
      align-items: center;
      gap: 0.75rem;
    }}
    .header-logo {{ font-size: 1.5rem; }}
    .header h1 {{ font-size: 1.125rem; font-weight: 600; color: #f0f6fc; }}
    .header-meta {{ margin-left: auto; color: var(--muted); font-size: 0.8125rem; }}

    .main {{ max-width: 1100px; margin: 0 auto; padding: 1.5rem; }}

    /* Cards */
    .card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
    }}
    .card-header {{
      padding: 1rem 1.25rem 0.75rem;
      border-bottom: 1px solid var(--border);
      font-weight: 600;
      color: #f0f6fc;
      font-size: 0.9375rem;
    }}
    .card-body {{ padding: 1.25rem; }}

    /* Summary strip */
    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 1rem;
      margin-bottom: 1.5rem;
    }}
    .stat-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 1.25rem;
      box-shadow: var(--shadow);
    }}
    .stat-label {{ color: var(--muted); font-size: 0.8125rem; margin-bottom: 0.3rem; }}
    .stat-value {{ font-size: 1.75rem; font-weight: 700; color: #f0f6fc; letter-spacing: -0.5px; }}
    .stat-sub   {{ color: var(--muted); font-size: 0.75rem; margin-top: 0.2rem; }}

    /* Chart */
    .chart-wrap {{ position: relative; height: 200px; margin-bottom: 0.5rem; }}
    canvas {{ width: 100% !important; }}

    /* Table */
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.8125rem; }}
    th {{
      text-align: left; padding: 0.6rem 0.75rem;
      color: var(--muted); font-weight: 500;
      border-bottom: 1px solid var(--border);
      white-space: nowrap;
    }}
    td {{
      padding: 0.65rem 0.75rem;
      border-bottom: 1px solid var(--border);
      color: var(--text);
      white-space: nowrap;
    }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: rgba(255,255,255,.03); }}

    .repo-link {{ color: var(--blue); text-decoration: none; font-weight: 500; }}
    .repo-link:hover {{ text-decoration: underline; }}

    /* Repo cards grid */
    .repos-section {{
      margin-bottom: 1rem;
    }}
    .repos-section .card-header {{
      padding: 1rem 1.25rem 0.75rem;
      border-bottom: 1px solid var(--border);
      font-weight: 600;
      color: #f0f6fc;
      font-size: 0.9375rem;
      background: var(--surface);
      border-radius: var(--radius) var(--radius) 0 0;
      border: 1px solid var(--border);
      border-bottom: none;
    }}
    .repo-cards {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 1rem;
      padding: 1rem 0;
    }}
    .repo-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 1.1rem 1.25rem;
      display: flex;
      flex-direction: column;
      gap: 0.5rem;
      transition: border-color 0.15s;
    }}
    .repo-card:hover {{ border-color: var(--blue); }}
    .repo-card-title {{
      font-weight: 600;
      font-size: 0.9375rem;
    }}
    .repo-card-title a {{ color: var(--blue); text-decoration: none; }}
    .repo-card-title a:hover {{ text-decoration: underline; }}
    .repo-card-desc {{
      color: var(--muted);
      font-size: 0.8rem;
      line-height: 1.45;
      flex: 1;
    }}
    .repo-card-lang {{
      display: flex;
      align-items: center;
      gap: 0.35rem;
      font-size: 0.78rem;
      color: var(--muted);
    }}
    .lang-dot {{
      width: 10px; height: 10px;
      border-radius: 50%;
      background: var(--orange);
      flex-shrink: 0;
    }}
    .repo-card-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.75rem;
      font-size: 0.78rem;
      color: var(--muted);
      margin-top: 0.2rem;
    }}
    .repo-card-meta span {{ display: flex; align-items: center; gap: 0.25rem; }}
    .repo-card-topics {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.35rem;
      margin-top: 0.1rem;
    }}
    .topic-tag {{
      background: rgba(88,166,255,.1);
      color: var(--blue);
      border-radius: 20px;
      padding: 0.1rem 0.5rem;
      font-size: 0.7rem;
    }}

    .badge {{
      display: inline-block;
      padding: 0.15rem 0.5rem;
      border-radius: 20px;
      font-size: 0.75rem;
      font-weight: 500;
    }}
    .badge-up   {{ background: rgba(63,185,80,.15);  color: var(--green);  }}
    .badge-down {{ background: rgba(248,81,73,.15);  color: var(--red);    }}
    .badge-flat {{ background: rgba(139,148,158,.12); color: var(--muted); }}

    /* Two-column layout */
    .grid-2 {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1rem;
      margin-bottom: 1rem;
    }}
    @media (max-width: 700px) {{
      .grid-2 {{ grid-template-columns: 1fr; }}
    }}

    .mb-1 {{ margin-bottom: 1rem; }}
    .footer {{ text-align: center; color: var(--muted); font-size: 0.75rem; padding: 2rem 0 1rem; }}
    .footer a {{ color: var(--blue); text-decoration: none; }}
  </style>
</head>
<body>

<header class="header">
  <span class="header-logo">📊</span>
  <h1>{owner} · GitEternal Statistics</h1>
  <div class="header-meta">
    Updated: <span id="generated-at"></span>
  </div>
</header>

<main class="main">

  <!-- Summary strip -->
  <div class="summary-grid" id="summary-strip"></div>

  <!-- Activity chart -->
  <div class="card mb-1">
    <div class="card-header">Activity — last 365 days</div>
    <div class="card-body">
      <div class="chart-wrap">
        <canvas id="activityChart"></canvas>
      </div>
      <div style="display:flex;gap:1.5rem;font-size:0.75rem;color:var(--muted);margin-top:.5rem;">
        <span><span style="display:inline-block;width:10px;height:10px;background:var(--blue);border-radius:2px;margin-right:4px;"></span>Clones</span>
        <span><span style="display:inline-block;width:10px;height:10px;background:var(--green);border-radius:2px;margin-right:4px;"></span>Views</span>
      </div>
    </div>
  </div>

  <!-- Repo cards -->
  <div class="repos-section">
    <div class="card-header">Repositories</div>
    <div class="repo-cards" id="repo-cards"></div>
  </div>

  <!-- Trends table -->
  <div class="card mb-1">
    <div class="card-header">Week-over-Week Trends</div>
    <div class="card-body" style="padding:0;">
      <div class="table-wrap">
        <table id="trends-table">
          <thead>
            <tr>
              <th>Repository</th>
              <th>This Week</th>
              <th>Last Week</th>
              <th>Change</th>
            </tr>
          </thead>
          <tbody></tbody>
        </table>
      </div>
    </div>
  </div>

</main>

<footer class="footer">
  Powered by <a href="https://github.com/{owner}/GitEternal" target="_blank">GitEternal</a>
  — data stored privately, dashboard auto-generated weekly.
</footer>

<!-- Inline data (no external fetches needed) -->
<script>
const SUMMARY    = {summary_json};
const TOP_REPOS  = {top_repos_json};
const TRENDS     = {trends_json};
const CHART_DATA = {chart_data_json};

// ── Utilities ─────────────────────────────────────────────────────────────────
function fmt(n) {{
  if (n === null || n === undefined) return '—';
  return Number(n).toLocaleString();
}}
function fmtPct(v) {{
  if (v === null || v === undefined) return '<span class="badge badge-flat">—</span>';
  const sign = v >= 0 ? '+' : '';
  const cls  = v > 0 ? 'badge-up' : v < 0 ? 'badge-down' : 'badge-flat';
  return `<span class="badge ${{cls}}">${{sign}}${{v}}%</span>`;
}}

// ── Summary strip ─────────────────────────────────────────────────────────────
function renderSummary() {{
  const el = document.getElementById('summary-strip');
  const stats = [
    {{ label: 'Tracked Repos',   value: fmt(SUMMARY.total_repos),    sub: '' }},
    {{ label: 'Lifetime Clones', value: fmt(SUMMARY.lifetime_clones), sub: 'all time' }},
    {{ label: 'Unique Cloners',  value: fmt(SUMMARY.lifetime_uniques), sub: 'all time' }},
    {{ label: 'Most Active Repo',
       value: SUMMARY.most_active_repo
                ? SUMMARY.most_active_repo.split('/')[1]
                : '—',
       sub: SUMMARY.most_active_repo
              ? SUMMARY.most_active_repo.split('/')[0]
              : '' }},
  ];
  el.innerHTML = stats.map(s => `
    <div class="stat-card">
      <div class="stat-label">${{s.label}}</div>
      <div class="stat-value">${{s.value}}</div>
      ${{s.sub ? `<div class="stat-sub">${{s.sub}}</div>` : ''}}
    </div>
  `).join('');

  const genAt = document.getElementById('generated-at');
  if (SUMMARY.generated_at) {{
    genAt.textContent = new Date(SUMMARY.generated_at).toLocaleString();
  }}
}}

// ── Repo cards ─────────────────────────────────────────────────────────────────
function renderRepoCards() {{
  const container = document.getElementById('repo-cards');
  if (!container || !TOP_REPOS.length) return;

  const langColors = {{
    'Python':'#3572A5','JavaScript':'#f1e05a','TypeScript':'#2b7489','Java':'#b07219',
    'C++':'#f34b7d','C':'#555555','Go':'#00ADD8','Rust':'#dea584','Ruby':'#701516',
    'PHP':'#4F5D95','Shell':'#89e051','Kotlin':'#F18E33','Swift':'#ffac45',
    'HTML':'#e34c26','CSS':'#563d7c','Dart':'#00B4AB','Scala':'#c22d40',
    'Vue':'#2c3e50','C#':'#178600',
  }};

  container.innerHTML = TOP_REPOS.map(r => {{
    const [, repo] = r.repo.split('/');
    const desc  = r.description ? `<div class="repo-card-desc">${{r.description}}</div>` : '';
    const lang  = r.language
      ? `<div class="repo-card-lang">
           <span class="lang-dot" style="background:${{langColors[r.language] || 'var(--muted)'}};"></span>
           ${{r.language}}
         </div>`
      : '';
    const topics = r.topics && r.topics.length
      ? `<div class="repo-card-topics">${{r.topics.slice(0,4).map(t => `<span class="topic-tag">${{t}}</span>`).join('')}}</div>`
      : '';
    return `
      <div class="repo-card">
        <div class="repo-card-title">
          <a href="https://github.com/${{r.repo}}" target="_blank">${{repo}}</a>
        </div>
        ${{desc}}
        ${{lang}}
        <div class="repo-card-meta">
          <span>⭐ ${{fmt(r.stars)}}</span>
          <span>🍴 ${{fmt(r.forks)}}</span>
          <span>👁 ${{fmt(r.watchers)}}</span>
          <span>🔵 ${{fmt(r.lifetime_clones)}} clones</span>
          ${{r.open_issues ? `<span>⚠ ${{r.open_issues}} issues</span>` : ''}}
        </div>
        ${{topics}}
      </div>`;
  }}).join('');
}}

// ── Trends table ──────────────────────────────────────────────────────────────
function renderTrends() {{
  const tbody = document.querySelector('#trends-table tbody');
  tbody.innerHTML = TRENDS.slice(0, 15).map(r => {{
    const [, repo] = r.repo.split('/');
    return `<tr>
      <td><a class="repo-link" href="https://github.com/${{r.repo}}" target="_blank">${{repo}}</a></td>
      <td>${{fmt(r.current_week_clones)}}</td>
      <td>${{fmt(r.prior_week_clones)}}</td>
      <td>${{fmtPct(r.clone_delta_pct)}}</td>
    </tr>`;
  }}).join('');
}}

// ── Activity chart (pure canvas, no library) ──────────────────────────────────
function renderChart() {{
  const canvas = document.getElementById('activityChart');
  if (!canvas || !CHART_DATA.length) return;

  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.parentElement.getBoundingClientRect();
  const W = rect.width;
  const H = 200;
  canvas.width  = W * dpr;
  canvas.height = H * dpr;
  canvas.style.width  = W + 'px';
  canvas.style.height = H + 'px';

  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  const PAD = {{ top: 10, right: 16, bottom: 30, left: 44 }};
  const CW  = W - PAD.left - PAD.right;
  const CH  = H - PAD.top  - PAD.bottom;

  const clones = CHART_DATA.map(d => d.clones);
  const views  = CHART_DATA.map(d => d.views);
  const maxVal = Math.max(...clones, ...views, 1);
  const n      = CHART_DATA.length;
  const step   = CW / Math.max(n - 1, 1);

  function xOf(i) {{ return PAD.left + i * step; }}
  function yOf(v) {{ return PAD.top  + CH - (v / maxVal) * CH; }}

  // Grid lines
  ctx.strokeStyle = '#21262d';
  ctx.lineWidth   = 1;
  for (let t = 0; t <= 4; t++) {{
    const y = PAD.top + (CH / 4) * t;
    ctx.beginPath();
    ctx.moveTo(PAD.left, y);
    ctx.lineTo(PAD.left + CW, y);
    ctx.stroke();
  }}

  // Y-axis labels
  ctx.fillStyle  = '#8b949e';
  ctx.font       = '11px system-ui';
  ctx.textAlign  = 'right';
  for (let t = 0; t <= 4; t++) {{
    const v = Math.round(maxVal * (1 - t / 4));
    const y = PAD.top + (CH / 4) * t + 4;
    ctx.fillText(v >= 1000 ? (v/1000).toFixed(1)+'k' : v, PAD.left - 6, y);
  }}

  // X-axis labels (roughly monthly)
  ctx.textAlign = 'center';
  const labelStep = Math.max(1, Math.round(n / 6));
  for (let i = 0; i < n; i += labelStep) {{
    const d   = CHART_DATA[i].date;
    const lbl = d.slice(5, 7) + '/' + d.slice(2, 4);
    ctx.fillText(lbl, xOf(i), H - 8);
  }}

  // Area fill + line — views
  const gv = ctx.createLinearGradient(0, PAD.top, 0, PAD.top + CH);
  gv.addColorStop(0, 'rgba(63,185,80,.25)');
  gv.addColorStop(1, 'rgba(63,185,80,0)');
  ctx.beginPath();
  ctx.moveTo(xOf(0), yOf(views[0]));
  for (let i = 1; i < n; i++) ctx.lineTo(xOf(i), yOf(views[i]));
  ctx.lineTo(xOf(n-1), PAD.top + CH);
  ctx.lineTo(xOf(0),   PAD.top + CH);
  ctx.closePath();
  ctx.fillStyle = gv;
  ctx.fill();

  ctx.beginPath();
  ctx.moveTo(xOf(0), yOf(views[0]));
  for (let i = 1; i < n; i++) ctx.lineTo(xOf(i), yOf(views[i]));
  ctx.strokeStyle = '#3fb950';
  ctx.lineWidth   = 1.5;
  ctx.stroke();

  // Area fill + line — clones
  const gc = ctx.createLinearGradient(0, PAD.top, 0, PAD.top + CH);
  gc.addColorStop(0, 'rgba(88,166,255,.3)');
  gc.addColorStop(1, 'rgba(88,166,255,0)');
  ctx.beginPath();
  ctx.moveTo(xOf(0), yOf(clones[0]));
  for (let i = 1; i < n; i++) ctx.lineTo(xOf(i), yOf(clones[i]));
  ctx.lineTo(xOf(n-1), PAD.top + CH);
  ctx.lineTo(xOf(0),   PAD.top + CH);
  ctx.closePath();
  ctx.fillStyle = gc;
  ctx.fill();

  ctx.beginPath();
  ctx.moveTo(xOf(0), yOf(clones[0]));
  for (let i = 1; i < n; i++) ctx.lineTo(xOf(i), yOf(clones[i]));
  ctx.strokeStyle = '#58a6ff';
  ctx.lineWidth   = 2;
  ctx.stroke();
}}

// ── Boot ──────────────────────────────────────────────────────────────────────
renderSummary();
renderRepoCards();
renderTrends();
renderChart();
window.addEventListener('resize', renderChart);
</script>
</body>
</html>
"""


# ── Main ──────────────────────────────────────────────────────────────────────

def generate(vault_path: Path, output_path: Path, owner: str | None = None) -> None:
    logger.info("Loading vault from %s", vault_path)
    index = _load_index(vault_path)

    if not owner and index.repos:
        owner = next(iter(index.repos)).split("/")[0]
    owner = owner or "unknown"

    logger.info("Generating reports for %d repos (owner=%s)", len(index.repos), owner)

    summary    = _generate_summary(index, owner)
    top_repos  = _generate_top_repos(index, owner)
    trends     = _generate_trends(vault_path, index)
    chart_data = _collect_chart_data(vault_path, index)

    # Write reports
    reports_dir = output_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "summary.json"  ).write_text(json.dumps(summary,   indent=2, sort_keys=True))
    (reports_dir / "top_repos.json").write_text(json.dumps(top_repos, indent=2))
    (reports_dir / "trends.json"   ).write_text(json.dumps(trends,    indent=2))
    (reports_dir / "chart_data.json").write_text(json.dumps(chart_data, indent=2))
    logger.info("Reports written to %s", reports_dir)

    # Write dashboard HTML
    docs_dir = output_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    html = _render_html(summary, top_repos, trends, chart_data, owner)
    (docs_dir / "index.html").write_text(html)
    logger.info("Dashboard written to %s/docs/index.html", output_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate GitEternal statistics reports")
    parser.add_argument("--vault",  required=True, help="Path to GitData clone")
    parser.add_argument("--output", required=True, help="Path to write output files")
    parser.add_argument("--owner",  default=None,  help="GitHub owner login (auto-detected if omitted)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    generate(Path(args.vault), Path(args.output), args.owner)


if __name__ == "__main__":
    main()

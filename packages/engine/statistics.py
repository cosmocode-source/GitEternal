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
    total_stars   = sum(m.stars  for m in repos.values())
    total_forks   = sum(m.forks  for m in repos.values())
    most_active   = max(repos, key=lambda r: repos[r].lifetime_clones) if repos else None
    most_starred  = max(repos, key=lambda r: repos[r].stars) if repos else None

    # Collect language breakdown
    lang_counts: dict[str, int] = {}
    for m in repos.values():
        if m.language:
            lang_counts[m.language] = lang_counts.get(m.language, 0) + 1
    top_lang = max(lang_counts, key=lang_counts.__getitem__) if lang_counts else ""

    return {
        "generated_at":     datetime.now(tz=UTC).isoformat(),
        "total_repos":      len(repos),
        "lifetime_clones":  total_clones,
        "lifetime_uniques": total_uniques,
        "total_stars":      total_stars,
        "total_forks":      total_forks,
        "most_active_repo": most_active,
        "most_starred_repo": most_starred,
        "top_language":     top_lang,
        "language_breakdown": lang_counts,
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
    owner_stats: dict[str, Any] | None = None,
) -> str:
    os_  = owner_stats or {}
    summary_json    = json.dumps(summary,    separators=(",", ":"))
    top_repos_json  = json.dumps(top_repos,  separators=(",", ":"))
    trends_json     = json.dumps(trends,     separators=(",", ":"))
    chart_data_json = json.dumps(chart_data, separators=(",", ":"))
    owner_stats_json = json.dumps(os_,       separators=(",", ":"))

    avatar   = os_.get("avatar_url", "")
    bio      = os_.get("bio", "")
    location = os_.get("location", "")
    blog     = os_.get("blog", "")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{owner} · GitHub Statistics</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --bg:      #0d1117; --surface: #161b22; --surface2: #21262d;
      --border:  #30363d; --text:    #c9d1d9; --muted:    #8b949e;
      --blue:    #58a6ff; --green:   #3fb950; --red:      #f85149;
      --purple:  #bc8cff; --orange:  #d29922; --yellow:   #e3b341;
      --radius:  8px;     --shadow:  0 1px 3px rgba(0,0,0,.4);
    }}
    body {{ background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; font-size:14px; line-height:1.5; min-height:100vh; }}

    /* ── Header ── */
    .header {{ background:var(--surface); border-bottom:1px solid var(--border); padding:1rem 1.5rem; display:flex; align-items:center; gap:1rem; }}
    .header-avatar {{ width:48px; height:48px; border-radius:50%; border:2px solid var(--border); object-fit:cover; }}
    .header-avatar-placeholder {{ width:48px; height:48px; border-radius:50%; background:var(--surface2); border:2px solid var(--border); display:flex; align-items:center; justify-content:center; font-size:1.4rem; }}
    .header-info h1 {{ font-size:1.1rem; font-weight:600; color:#f0f6fc; }}
    .header-info .sub {{ color:var(--muted); font-size:0.8rem; }}
    .header-meta {{ margin-left:auto; color:var(--muted); font-size:0.75rem; text-align:right; }}

    .main {{ max-width:1200px; margin:0 auto; padding:1.5rem; }}

    /* ── Profile card ── */
    .profile-card {{ background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:1.25rem 1.5rem; margin-bottom:1.5rem; display:flex; align-items:center; gap:1.5rem; flex-wrap:wrap; }}
    .profile-avatar {{ width:72px; height:72px; border-radius:50%; border:3px solid var(--border); object-fit:cover; flex-shrink:0; }}
    .profile-avatar-ph {{ width:72px; height:72px; border-radius:50%; background:var(--surface2); border:3px solid var(--border); display:flex; align-items:center; justify-content:center; font-size:2rem; flex-shrink:0; }}
    .profile-details h2 {{ font-size:1.2rem; font-weight:700; color:#f0f6fc; }}
    .profile-details .bio {{ color:var(--muted); font-size:0.85rem; margin-top:.25rem; max-width:500px; }}
    .profile-meta {{ display:flex; gap:1rem; flex-wrap:wrap; margin-top:.5rem; font-size:0.78rem; color:var(--muted); }}
    .profile-meta span {{ display:flex; align-items:center; gap:.3rem; }}
    .profile-links {{ margin-left:auto; display:flex; gap:.75rem; align-items:center; flex-wrap:wrap; }}
    .profile-links a {{ color:var(--blue); text-decoration:none; font-size:0.82rem; }}
    .profile-links a:hover {{ text-decoration:underline; }}

    /* ── Stat strip ── */
    .stat-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:.875rem; margin-bottom:1.5rem; }}
    .stat-card {{ background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:1rem 1.25rem; box-shadow:var(--shadow); position:relative; overflow:hidden; }}
    .stat-card::before {{ content:''; position:absolute; top:0; left:0; right:0; height:3px; background:var(--accent-color,var(--blue)); }}
    .stat-label {{ color:var(--muted); font-size:0.75rem; text-transform:uppercase; letter-spacing:.05em; margin-bottom:.3rem; }}
    .stat-value {{ font-size:1.6rem; font-weight:700; color:#f0f6fc; letter-spacing:-0.5px; }}
    .stat-sub {{ color:var(--muted); font-size:0.72rem; margin-top:.15rem; }}
    .stat-icon {{ position:absolute; right:1rem; top:50%; transform:translateY(-50%); font-size:1.6rem; opacity:.18; }}

    /* ── Cards ── */
    .card {{ background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); box-shadow:var(--shadow); }}
    .card-header {{ padding:.875rem 1.25rem; border-bottom:1px solid var(--border); font-weight:600; color:#f0f6fc; font-size:.9rem; display:flex; align-items:center; gap:.5rem; }}
    .card-body {{ padding:1.25rem; }}
    .mb {{ margin-bottom:1rem; }}

    /* ── Chart ── */
    .chart-wrap {{ position:relative; height:180px; }}
    canvas {{ width:100%!important; }}
    .chart-legend {{ display:flex; gap:1.5rem; font-size:.72rem; color:var(--muted); margin-top:.5rem; }}
    .chart-legend span {{ display:flex; align-items:center; gap:.3rem; }}
    .legend-dot {{ width:10px; height:10px; border-radius:2px; display:inline-block; }}

    /* ── Language bar ── */
    .lang-bar-wrap {{ margin-bottom:.75rem; }}
    .lang-bar {{ display:flex; height:8px; border-radius:4px; overflow:hidden; gap:2px; }}
    .lang-bar-seg {{ height:100%; border-radius:2px; transition:flex .3s; }}
    .lang-legend {{ display:flex; flex-wrap:wrap; gap:.5rem 1rem; margin-top:.6rem; font-size:.75rem; color:var(--muted); }}
    .lang-legend-item {{ display:flex; align-items:center; gap:.3rem; }}
    .lang-dot {{ width:10px; height:10px; border-radius:50%; flex-shrink:0; }}

    /* ── Two-col ── */
    .grid-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:1rem; margin-bottom:1rem; }}
    @media(max-width:750px) {{ .grid-2 {{ grid-template-columns:1fr; }} }}

    /* ── Table ── */
    .table-wrap {{ overflow-x:auto; }}
    table {{ width:100%; border-collapse:collapse; font-size:.8rem; }}
    th {{ text-align:left; padding:.55rem .75rem; color:var(--muted); font-weight:500; border-bottom:1px solid var(--border); white-space:nowrap; }}
    td {{ padding:.6rem .75rem; border-bottom:1px solid var(--border); color:var(--text); }}
    tr:last-child td {{ border-bottom:none; }}
    tr:hover td {{ background:rgba(255,255,255,.025); }}
    .repo-link {{ color:var(--blue); text-decoration:none; font-weight:500; }}
    .repo-link:hover {{ text-decoration:underline; }}

    /* ── Badges ── */
    .badge {{ display:inline-block; padding:.15rem .45rem; border-radius:20px; font-size:.72rem; font-weight:500; }}
    .badge-up   {{ background:rgba(63,185,80,.15);   color:var(--green); }}
    .badge-down {{ background:rgba(248,81,73,.15);   color:var(--red); }}
    .badge-flat {{ background:rgba(139,148,158,.12); color:var(--muted); }}

    /* ── Repo cards ── */
    .repos-header {{ font-weight:600; color:#f0f6fc; font-size:.9rem; margin-bottom:.875rem; display:flex; align-items:center; gap:.5rem; }}
    .repo-cards {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(270px,1fr)); gap:.875rem; margin-bottom:1.5rem; }}
    .repo-card {{ background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:1rem 1.1rem; display:flex; flex-direction:column; gap:.45rem; transition:border-color .15s,box-shadow .15s; }}
    .repo-card:hover {{ border-color:var(--blue); box-shadow:0 0 0 1px rgba(88,166,255,.2); }}
    .repo-card-title {{ font-weight:600; font-size:.875rem; }}
    .repo-card-title a {{ color:var(--blue); text-decoration:none; }}
    .repo-card-title a:hover {{ text-decoration:underline; }}
    .repo-card-desc {{ color:var(--muted); font-size:.775rem; line-height:1.45; flex:1; }}
    .repo-card-lang {{ display:flex; align-items:center; gap:.3rem; font-size:.75rem; color:var(--muted); }}
    .lang-circle {{ width:10px; height:10px; border-radius:50%; flex-shrink:0; background:var(--orange); }}
    .repo-card-stats {{ display:flex; flex-wrap:wrap; gap:.6rem; font-size:.75rem; color:var(--muted); }}
    .repo-card-stats span {{ display:flex; align-items:center; gap:.2rem; }}
    .repo-card-topics {{ display:flex; flex-wrap:wrap; gap:.3rem; }}
    .topic {{ background:rgba(88,166,255,.1); color:var(--blue); border-radius:20px; padding:.1rem .45rem; font-size:.68rem; }}

    /* ── Footer ── */
    .footer {{ text-align:center; color:var(--muted); font-size:.72rem; padding:2rem 0 1rem; }}
    .footer a {{ color:var(--blue); text-decoration:none; }}
  </style>
</head>
<body>

<header class="header">
  {'<img class="header-avatar" src="' + avatar + '" alt="' + owner + '">' if avatar else '<div class="header-avatar-placeholder">👤</div>'}
  <div class="header-info">
    <h1>{owner} · GitHub Statistics</h1>
    <div class="sub">{'📍 ' + location if location else ''}</div>
  </div>
  <div class="header-meta">
    Updated: <span id="generated-at"></span>
  </div>
</header>

<main class="main">

  <!-- Profile card -->
  <div class="profile-card">
    {'<img class="profile-avatar" src="' + avatar + '" alt="' + owner + '">' if avatar else '<div class="profile-avatar-ph">👤</div>'}
    <div class="profile-details">
      <h2>{owner}</h2>
      {'<div class="bio">' + bio + '</div>' if bio else ''}
      <div class="profile-meta">
        {'<span>📍 ' + location + '</span>' if location else ''}
        <span id="prof-followers"></span>
        <span id="prof-following"></span>
        <span id="prof-repos"></span>
      </div>
    </div>
    {'<div class="profile-links"><a href="' + blog + '" target="_blank">🔗 ' + blog + '</a></div>' if blog else ''}
  </div>

  <!-- Stat strip -->
  <div class="stat-grid" id="stat-strip"></div>

  <!-- Activity chart + Language breakdown -->
  <div class="grid-2 mb">
    <div class="card">
      <div class="card-header">📈 Activity — last 365 days</div>
      <div class="card-body">
        <div class="chart-wrap"><canvas id="activityChart"></canvas></div>
        <div class="chart-legend">
          <span><span class="legend-dot" style="background:var(--blue)"></span>Clones</span>
          <span><span class="legend-dot" style="background:var(--green)"></span>Views</span>
        </div>
      </div>
    </div>
    <div class="card">
      <div class="card-header">🌐 Language Breakdown</div>
      <div class="card-body">
        <div class="lang-bar-wrap">
          <div class="lang-bar" id="lang-bar"></div>
          <div class="lang-legend" id="lang-legend"></div>
        </div>
      </div>
    </div>
  </div>

  <!-- Repo cards -->
  <div class="repos-header">📦 Repositories</div>
  <div class="repo-cards" id="repo-cards"></div>

  <!-- Trends + Top by clones -->
  <div class="grid-2">
    <div class="card">
      <div class="card-header">🔥 Week-over-Week Trends</div>
      <div class="card-body" style="padding:0">
        <div class="table-wrap">
          <table id="trends-table">
            <thead><tr><th>Repository</th><th>This Week</th><th>Last Week</th><th>Δ</th></tr></thead>
            <tbody></tbody>
          </table>
        </div>
      </div>
    </div>
    <div class="card">
      <div class="card-header">⭐ Top by Stars</div>
      <div class="card-body" style="padding:0">
        <div class="table-wrap">
          <table id="stars-table">
            <thead><tr><th>#</th><th>Repository</th><th>Stars</th><th>Forks</th></tr></thead>
            <tbody></tbody>
          </table>
        </div>
      </div>
    </div>
  </div>

</main>

<footer class="footer">
  Powered by <a href="https://github.com/{owner}/GitEternal" target="_blank">GitEternal</a>
  · Data stored privately · Dashboard auto-generated weekly
</footer>

<script>
const SUMMARY     = {summary_json};
const TOP_REPOS   = {top_repos_json};
const TRENDS      = {trends_json};
const CHART_DATA  = {chart_data_json};
const OWNER_STATS = {owner_stats_json};

const LANG_COLORS = {{
  'Python':'#3572A5','JavaScript':'#f1e05a','TypeScript':'#2b7489','Java':'#b07219',
  'C++':'#f34b7d','C':'#555555','Go':'#00ADD8','Rust':'#dea584','Ruby':'#701516',
  'PHP':'#4F5D95','Shell':'#89e051','Kotlin':'#F18E33','Swift':'#ffac45',
  'HTML':'#e34c26','CSS':'#563d7c','Dart':'#00B4AB','Scala':'#c22d40',
  'Vue':'#41b883','C#':'#178600','R':'#198CE7','Jupyter Notebook':'#DA5B0B',
}};

function fmt(n) {{ return n == null ? '—' : Number(n).toLocaleString(); }}
function fmtPct(v) {{
  if (v == null) return '<span class="badge badge-flat">—</span>';
  const s = v >= 0 ? '+' : ''; const c = v > 0 ? 'badge-up' : v < 0 ? 'badge-down' : 'badge-flat';
  return `<span class="badge ${{c}}">${{s}}${{v}}%</span>`;
}}

// ── Stat strip ──────────────────────────────────────────────────────────────
function renderStats() {{
  const stats = [
    {{ label:'Public Repos',    value:fmt(SUMMARY.total_repos),         sub:'tracked',     icon:'📦', color:'var(--blue)'   }},
    {{ label:'Total Stars',     value:fmt(SUMMARY.total_stars),         sub:'across repos', icon:'⭐', color:'var(--yellow)' }},
    {{ label:'Total Forks',     value:fmt(SUMMARY.total_forks),         sub:'across repos', icon:'🍴', color:'var(--green)'  }},
    {{ label:'Lifetime Clones', value:fmt(SUMMARY.lifetime_clones),     sub:'all time',    icon:'📥', color:'var(--purple)' }},
    {{ label:'Unique Cloners',  value:fmt(SUMMARY.lifetime_uniques),    sub:'all time',    icon:'👤', color:'var(--orange)' }},
    {{ label:'Total Commits',   value:fmt(OWNER_STATS.total_commits),   sub:'all time',    icon:'💻', color:'var(--green)'  }},
    {{ label:'Total PRs',       value:fmt(OWNER_STATS.total_prs),       sub:'all time',    icon:'🔀', color:'var(--blue)'   }},
    {{ label:'Followers',       value:fmt(OWNER_STATS.followers),       sub:'on GitHub',   icon:'👥', color:'var(--purple)' }},
  ];
  document.getElementById('stat-strip').innerHTML = stats.map(s => `
    <div class="stat-card" style="--accent-color:${{s.color}}">
      <div class="stat-label">${{s.label}}</div>
      <div class="stat-value">${{s.value}}</div>
      <div class="stat-sub">${{s.sub}}</div>
      <div class="stat-icon">${{s.icon}}</div>
    </div>`).join('');

  // Profile meta
  if (OWNER_STATS.followers) document.getElementById('prof-followers').textContent = `👥 ${{fmt(OWNER_STATS.followers)}} followers`;
  if (OWNER_STATS.following) document.getElementById('prof-following').textContent = `· ${{fmt(OWNER_STATS.following)}} following`;
  if (OWNER_STATS.public_repos) document.getElementById('prof-repos').textContent = `· ${{fmt(OWNER_STATS.public_repos)}} public repos`;

  const genAt = document.getElementById('generated-at');
  if (SUMMARY.generated_at) genAt.textContent = new Date(SUMMARY.generated_at).toLocaleString();
}}

// ── Language bar ────────────────────────────────────────────────────────────
function renderLangBar() {{
  const langs = SUMMARY.language_breakdown || {{}};
  const total = Object.values(langs).reduce((a,b) => a+b, 0);
  if (!total) return;
  const sorted = Object.entries(langs).sort((a,b) => b[1]-a[1]);
  const bar = document.getElementById('lang-bar');
  const legend = document.getElementById('lang-legend');
  bar.innerHTML = sorted.map(([lang, count]) => {{
    const pct = (count / total * 100).toFixed(1);
    const color = LANG_COLORS[lang] || 'var(--muted)';
    return `<div class="lang-bar-seg" style="flex:${{pct}};background:${{color}}" title="${{lang}} ${{pct}}%"></div>`;
  }}).join('');
  legend.innerHTML = sorted.slice(0, 10).map(([lang, count]) => {{
    const pct = (count / total * 100).toFixed(1);
    const color = LANG_COLORS[lang] || 'var(--muted)';
    return `<div class="lang-legend-item"><span class="lang-dot" style="background:${{color}}"></span>${{lang}} ${{pct}}%</div>`;
  }}).join('');
}}

// ── Repo cards ───────────────────────────────────────────────────────────────
function renderRepoCards() {{
  const container = document.getElementById('repo-cards');
  if (!container || !TOP_REPOS.length) return;
  container.innerHTML = TOP_REPOS.map(r => {{
    const [, repo] = r.repo.split('/');
    const desc   = r.description ? `<div class="repo-card-desc">${{r.description}}</div>` : '';
    const lang   = r.language ? `<div class="repo-card-lang"><span class="lang-circle" style="background:${{LANG_COLORS[r.language]||'var(--muted)'}}"></span>${{r.language}}</div>` : '';
    const topics = r.topics?.length ? `<div class="repo-card-topics">${{r.topics.slice(0,3).map(t=>`<span class="topic">${{t}}</span>`).join('')}}</div>` : '';
    return `<div class="repo-card">
      <div class="repo-card-title"><a href="https://github.com/${{r.repo}}" target="_blank">${{repo}}</a></div>
      ${{desc}}${{lang}}
      <div class="repo-card-stats">
        <span>⭐ ${{fmt(r.stars)}}</span>
        <span>🍴 ${{fmt(r.forks)}}</span>
        <span>👁 ${{fmt(r.watchers)}}</span>
        <span>📥 ${{fmt(r.lifetime_clones)}}</span>
        ${{r.open_issues ? `<span>⚠ ${{r.open_issues}}</span>` : ''}}
      </div>
      ${{topics}}
    </div>`;
  }}).join('');
}}

// ── Trends table ─────────────────────────────────────────────────────────────
function renderTrends() {{
  document.querySelector('#trends-table tbody').innerHTML =
    TRENDS.slice(0,15).map(r => {{
      const [,repo] = r.repo.split('/');
      return `<tr>
        <td><a class="repo-link" href="https://github.com/${{r.repo}}" target="_blank">${{repo}}</a></td>
        <td>${{fmt(r.current_week_clones)}}</td>
        <td>${{fmt(r.prior_week_clones)}}</td>
        <td>${{fmtPct(r.clone_delta_pct)}}</td>
      </tr>`;
    }}).join('');
}}

// ── Top by stars table ───────────────────────────────────────────────────────
function renderStarsTable() {{
  const sorted = [...TOP_REPOS].sort((a,b) => (b.stars||0)-(a.stars||0));
  document.querySelector('#stars-table tbody').innerHTML =
    sorted.slice(0,15).map((r,i) => {{
      const [,repo] = r.repo.split('/');
      return `<tr>
        <td style="color:var(--muted)">${{i+1}}</td>
        <td><a class="repo-link" href="https://github.com/${{r.repo}}" target="_blank">${{repo}}</a></td>
        <td>⭐ ${{fmt(r.stars)}}</td>
        <td>🍴 ${{fmt(r.forks)}}</td>
      </tr>`;
    }}).join('');
}}

// ── Activity chart ───────────────────────────────────────────────────────────
function renderChart() {{
  const canvas = document.getElementById('activityChart');
  if (!canvas || !CHART_DATA.length) return;
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.parentElement.getBoundingClientRect().width;
  const H = 180;
  canvas.width = W * dpr; canvas.height = H * dpr;
  canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  const PAD = {{ top:10, right:16, bottom:30, left:44 }};
  const gW = W - PAD.left - PAD.right;
  const gH = H - PAD.top  - PAD.bottom;
  const maxC = Math.max(...CHART_DATA.map(d=>d.clones), 1);
  const maxV = Math.max(...CHART_DATA.map(d=>d.views),  1);
  const maxY = Math.max(maxC, maxV);
  const xStep = gW / Math.max(CHART_DATA.length - 1, 1);
  function px(i, val) {{ return [PAD.left + i * xStep, PAD.top + gH - (val / maxY) * gH]; }}
  // Grid
  ctx.strokeStyle = 'rgba(48,54,61,.8)'; ctx.lineWidth = 1;
  for (let t = 0; t <= 4; t++) {{
    const y = PAD.top + (gH / 4) * t;
    ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(PAD.left + gW, y); ctx.stroke();
  }}
  function drawLine(color, key) {{
    ctx.beginPath(); ctx.strokeStyle = color; ctx.lineWidth = 1.5;
    CHART_DATA.forEach((d,i) => {{ const [x,y] = px(i,d[key]); i===0?ctx.moveTo(x,y):ctx.lineTo(x,y); }});
    ctx.stroke();
  }}
  drawLine('#58a6ff','clones'); drawLine('#3fb950','views');
  // X labels (monthly)
  ctx.fillStyle = '#8b949e'; ctx.font = '10px sans-serif'; ctx.textAlign = 'center';
  const step = Math.max(1, Math.floor(CHART_DATA.length / 6));
  CHART_DATA.forEach((d,i) => {{
    if (i % step === 0) {{
      const [x] = px(i,0);
      ctx.fillText(d.date.slice(0,7), x, H - 8);
    }}
  }});
  // Y label
  ctx.textAlign = 'right'; ctx.fillText(fmt(maxY), PAD.left - 4, PAD.top + 4);
}}

renderStats();
renderLangBar();
renderRepoCards();
renderTrends();
renderStarsTable();
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

    # Load owner stats if available
    owner_stats_path = vault_path / "owner_stats.json"
    owner_stats = json.loads(owner_stats_path.read_text()) if owner_stats_path.exists() else {}

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
    html = _render_html(summary, top_repos, trends, chart_data, owner, owner_stats)
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

"""
packages/engine/statistics.py
──────────────────────────────
Reads GitData vault, generates analytics reports (JSON) and a
self-contained GitHub Pages dashboard (HTML).

Usage
-----
    python -m packages.engine.statistics \
        --vault  /path/to/vault-clone \
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
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Mono:wght@300;400;500&family=Inter:wght@300;400;500&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    :root {{
      --bg:        #080c10;
      --surface:   #0e1318;
      --surface2:  #141b22;
      --surface3:  #1a2430;
      --border:    rgba(99,179,237,0.12);
      --border2:   rgba(99,179,237,0.22);
      --text:      #c8d8e8;
      --muted:     #5d7a94;
      --accent:    #4fc3f7;
      --accent2:   #26a69a;
      --accent3:   #81c784;
      --gold:      #ffd54f;
      --coral:     #ef9a9a;
      --radius:    12px;
      --radius-lg: 20px;
      --font-display: 'Syne', sans-serif;
      --font-mono:    'DM Mono', monospace;
      --font-body:    'Inter', sans-serif;
    }}

    html {{ scroll-behavior: smooth; }}

    body {{
      background: var(--bg);
      color: var(--text);
      font-family: var(--font-body);
      font-size: 14px;
      line-height: 1.6;
      overflow-x: hidden;
    }}

    /* ═══════════════════════════════════════════
       SCROLL FADE SYSTEM
    ═══════════════════════════════════════════ */
    .reveal {{
      opacity: 0;
      transform: translateY(32px);
      transition: opacity 0.7s cubic-bezier(.16,1,.3,1), transform 0.7s cubic-bezier(.16,1,.3,1);
    }}
    .reveal.visible {{
      opacity: 1;
      transform: translateY(0);
    }}
    .reveal-delay-1 {{ transition-delay: 0.1s; }}
    .reveal-delay-2 {{ transition-delay: 0.2s; }}
    .reveal-delay-3 {{ transition-delay: 0.3s; }}
    .reveal-delay-4 {{ transition-delay: 0.4s; }}
    .reveal-delay-5 {{ transition-delay: 0.5s; }}
    .reveal-delay-6 {{ transition-delay: 0.6s; }}

    /* ═══════════════════════════════════════════
       HERO SECTION
    ═══════════════════════════════════════════ */
    #hero {{
      position: relative;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      text-align: center;
      overflow: hidden;
      padding: 2rem;
    }}

    /* Animated gradient background */
    #hero::before {{
      content: '';
      position: absolute;
      inset: 0;
      background:
        radial-gradient(ellipse 80% 60% at 50% 40%, rgba(79,195,247,0.07) 0%, transparent 70%),
        radial-gradient(ellipse 60% 50% at 20% 80%, rgba(38,166,154,0.05) 0%, transparent 60%),
        radial-gradient(ellipse 50% 40% at 80% 20%, rgba(129,199,132,0.04) 0%, transparent 60%),
        linear-gradient(180deg, #080c10 0%, #0a1018 40%, #080c10 100%);
      animation: bgPulse 8s ease-in-out infinite alternate;
    }}

    @keyframes bgPulse {{
      0%   {{ opacity: 0.8; }}
      100% {{ opacity: 1; }}
    }}

    /* Grid overlay */
    #hero::after {{
      content: '';
      position: absolute;
      inset: 0;
      background-image:
        linear-gradient(rgba(79,195,247,0.03) 1px, transparent 1px),
        linear-gradient(90deg, rgba(79,195,247,0.03) 1px, transparent 1px);
      background-size: 60px 60px;
      mask-image: radial-gradient(ellipse 70% 70% at 50% 50%, black 20%, transparent 80%);
      pointer-events: none;
    }}

    .hero-inner {{
      position: relative;
      z-index: 2;
      animation: heroFadeIn 1.2s cubic-bezier(.16,1,.3,1) forwards;
      opacity: 0;
    }}

    @keyframes heroFadeIn {{
      0%   {{ opacity: 0; transform: translateY(20px); }}
      100% {{ opacity: 1; transform: translateY(0); }}
    }}

    .hero-eyebrow {{
      font-family: var(--font-mono);
      font-size: 0.7rem;
      letter-spacing: 0.22em;
      text-transform: uppercase;
      color: var(--accent);
      margin-bottom: 1.5rem;
      opacity: 0.8;
    }}

    .hero-avatar-wrap {{
      position: relative;
      display: inline-block;
      margin-bottom: 1.75rem;
    }}

    .hero-avatar {{
      width: 96px;
      height: 96px;
      border-radius: 50%;
      border: 2px solid rgba(79,195,247,0.3);
      object-fit: cover;
      display: block;
      box-shadow: 0 0 40px rgba(79,195,247,0.15), 0 0 80px rgba(79,195,247,0.05);
    }}

    .hero-avatar-ph {{
      width: 96px;
      height: 96px;
      border-radius: 50%;
      background: var(--surface2);
      border: 2px solid var(--border2);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 2.4rem;
      box-shadow: 0 0 40px rgba(79,195,247,0.1);
    }}

    .hero-avatar-ring {{
      position: absolute;
      inset: -8px;
      border-radius: 50%;
      border: 1px solid rgba(79,195,247,0.2);
      animation: ringPulse 3s ease-in-out infinite;
    }}

    .hero-avatar-ring2 {{
      position: absolute;
      inset: -16px;
      border-radius: 50%;
      border: 1px solid rgba(79,195,247,0.08);
      animation: ringPulse 3s ease-in-out infinite 0.5s;
    }}

    @keyframes ringPulse {{
      0%, 100% {{ transform: scale(1); opacity: 1; }}
      50%       {{ transform: scale(1.05); opacity: 0.5; }}
    }}

    .hero-name {{
      font-family: var(--font-display);
      font-size: clamp(2.8rem, 8vw, 5.5rem);
      font-weight: 800;
      color: #f0f8ff;
      letter-spacing: -0.03em;
      line-height: 1;
      margin-bottom: 1rem;
      background: linear-gradient(135deg, #e8f4fd 0%, #4fc3f7 50%, #26a69a 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
    }}

    .hero-bio {{
      font-family: var(--font-body);
      font-size: 1rem;
      font-weight: 300;
      color: var(--muted);
      max-width: 460px;
      margin: 0 auto 0.75rem;
      line-height: 1.7;
    }}

    .hero-location {{
      font-family: var(--font-mono);
      font-size: 0.72rem;
      color: var(--muted);
      letter-spacing: 0.05em;
      margin-bottom: 2rem;
    }}

    .hero-cta {{
      display: inline-flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.65rem 1.5rem;
      border: 1px solid var(--border2);
      border-radius: 50px;
      color: var(--accent);
      font-family: var(--font-mono);
      font-size: 0.72rem;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      text-decoration: none;
      background: rgba(79,195,247,0.05);
      transition: all 0.3s ease;
      cursor: pointer;
    }}

    .hero-cta:hover {{
      background: rgba(79,195,247,0.12);
      border-color: rgba(79,195,247,0.4);
      box-shadow: 0 0 20px rgba(79,195,247,0.1);
    }}

    .hero-scroll-hint {{
      position: absolute;
      bottom: 2rem;
      left: 50%;
      transform: translateX(-50%);
      z-index: 2;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 0.5rem;
      opacity: 0.4;
      animation: scrollHint 2s ease-in-out infinite;
    }}

    @keyframes scrollHint {{
      0%, 100% {{ transform: translateX(-50%) translateY(0); opacity: 0.4; }}
      50%       {{ transform: translateX(-50%) translateY(6px); opacity: 0.2; }}
    }}

    .hero-scroll-hint span {{
      font-family: var(--font-mono);
      font-size: 0.6rem;
      letter-spacing: 0.15em;
      text-transform: uppercase;
      color: var(--muted);
    }}

    .scroll-arrow {{
      width: 1px;
      height: 32px;
      background: linear-gradient(to bottom, var(--accent), transparent);
    }}

    /* ═══════════════════════════════════════════
       INTRO SECTION
    ═══════════════════════════════════════════ */
    #intro {{
      padding: 6rem 2rem;
      max-width: 900px;
      margin: 0 auto;
      text-align: center;
    }}

    .section-label {{
      font-family: var(--font-mono);
      font-size: 0.65rem;
      letter-spacing: 0.25em;
      text-transform: uppercase;
      color: var(--accent);
      margin-bottom: 1.25rem;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 0.75rem;
    }}

    .section-label::before,
    .section-label::after {{
      content: '';
      display: block;
      width: 40px;
      height: 1px;
      background: var(--accent);
      opacity: 0.4;
    }}

    .intro-heading {{
      font-family: var(--font-display);
      font-size: clamp(1.8rem, 5vw, 3rem);
      font-weight: 700;
      color: #e8f4fd;
      line-height: 1.2;
      margin-bottom: 1.5rem;
      letter-spacing: -0.02em;
    }}

    .intro-heading em {{
      font-style: normal;
      color: var(--accent);
    }}

    .intro-body {{
      font-size: 1rem;
      color: var(--muted);
      line-height: 1.8;
      max-width: 640px;
      margin: 0 auto 2rem;
      font-weight: 300;
    }}

    .intro-tags {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      justify-content: center;
    }}

    .intro-tag {{
      padding: 0.35rem 0.85rem;
      border: 1px solid var(--border);
      border-radius: 50px;
      font-family: var(--font-mono);
      font-size: 0.68rem;
      color: var(--muted);
      letter-spacing: 0.05em;
      background: var(--surface);
    }}

    /* ═══════════════════════════════════════════
       DIVIDER
    ═══════════════════════════════════════════ */
    .section-divider {{
      width: 100%;
      height: 1px;
      background: linear-gradient(90deg, transparent, var(--border2), transparent);
      margin: 0;
    }}

    /* ═══════════════════════════════════════════
       STATS SECTION
    ═══════════════════════════════════════════ */
    #stats {{
      padding: 6rem 2rem;
      max-width: 1200px;
      margin: 0 auto;
    }}

    .stats-header {{
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      margin-bottom: 3rem;
      flex-wrap: wrap;
      gap: 1rem;
    }}

    .stats-title {{
      font-family: var(--font-display);
      font-size: clamp(1.5rem, 4vw, 2.2rem);
      font-weight: 700;
      color: #e8f4fd;
      letter-spacing: -0.02em;
    }}

    .stats-subtitle {{
      font-family: var(--font-mono);
      font-size: 0.68rem;
      color: var(--muted);
      letter-spacing: 0.05em;
    }}

    /* Stat grid */
    .stat-grid {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 1px;
      background: var(--border);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      overflow: hidden;
      margin-bottom: 2rem;
    }}

    @media (max-width: 900px) {{ .stat-grid {{ grid-template-columns: repeat(2, 1fr); }} }}
    @media (max-width: 500px) {{ .stat-grid {{ grid-template-columns: 1fr; }} }}

    .stat-card {{
      background: var(--surface);
      padding: 2rem 1.75rem;
      position: relative;
      overflow: hidden;
      transition: background 0.3s ease;
    }}

    .stat-card:hover {{
      background: var(--surface2);
    }}

    .stat-card::before {{
      content: '';
      position: absolute;
      top: 0; left: 0; right: 0;
      height: 2px;
      background: var(--accent-color, var(--accent));
      opacity: 0;
      transition: opacity 0.3s ease;
    }}

    .stat-card:hover::before {{
      opacity: 1;
    }}

    .stat-icon {{
      font-size: 1.3rem;
      margin-bottom: 1rem;
      display: block;
      opacity: 0.7;
    }}

    .stat-value {{
      font-family: var(--font-display);
      font-size: 2.2rem;
      font-weight: 800;
      color: #f0f8ff;
      letter-spacing: -0.04em;
      line-height: 1;
      margin-bottom: 0.4rem;
    }}

    .stat-label {{
      font-family: var(--font-mono);
      font-size: 0.65rem;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--muted);
    }}

    /* Secondary stats row */
    .stat-row {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 1rem;
      margin-bottom: 3rem;
    }}

    .stat-pill {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 1rem 1.25rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      transition: border-color 0.2s ease;
    }}

    .stat-pill:hover {{
      border-color: var(--border2);
    }}

    .stat-pill-label {{
      font-family: var(--font-mono);
      font-size: 0.65rem;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: var(--muted);
    }}

    .stat-pill-value {{
      font-family: var(--font-display);
      font-size: 1.1rem;
      font-weight: 700;
      color: #e8f4fd;
    }}

    /* ═══════════════════════════════════════════
       CHARTS SECTION
    ═══════════════════════════════════════════ */
    .charts-grid {{
      display: grid;
      grid-template-columns: 2fr 1fr;
      gap: 1rem;
      margin-bottom: 3rem;
    }}

    @media (max-width: 800px) {{ .charts-grid {{ grid-template-columns: 1fr; }} }}

    .chart-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      overflow: hidden;
    }}

    .chart-card-header {{
      padding: 1.25rem 1.5rem;
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: space-between;
    }}

    .chart-card-title {{
      font-family: var(--font-display);
      font-size: 0.85rem;
      font-weight: 600;
      color: #e8f4fd;
    }}

    .chart-card-sub {{
      font-family: var(--font-mono);
      font-size: 0.62rem;
      color: var(--muted);
      letter-spacing: 0.06em;
    }}

    .chart-card-body {{
      padding: 1.5rem;
    }}

    .chart-wrap {{
      position: relative;
      height: 180px;
    }}

    canvas {{ width: 100% !important; }}

    .chart-legend {{
      display: flex;
      gap: 1.5rem;
      font-family: var(--font-mono);
      font-size: 0.65rem;
      color: var(--muted);
      margin-top: 1rem;
      letter-spacing: 0.05em;
    }}

    .legend-dot {{
      width: 8px;
      height: 8px;
      border-radius: 2px;
      display: inline-block;
    }}

    /* Language bar */
    .lang-bar {{
      display: flex;
      height: 6px;
      border-radius: 3px;
      overflow: hidden;
      gap: 2px;
      margin-bottom: 1.25rem;
    }}

    .lang-bar-seg {{
      height: 100%;
      border-radius: 2px;
      transition: flex 0.4s ease;
    }}

    .lang-legend {{
      display: flex;
      flex-direction: column;
      gap: 0.6rem;
    }}

    .lang-legend-item {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-family: var(--font-mono);
      font-size: 0.68rem;
      color: var(--muted);
    }}

    .lang-legend-left {{
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }}

    .lang-dot {{
      width: 8px;
      height: 8px;
      border-radius: 50%;
      flex-shrink: 0;
    }}

    /* ═══════════════════════════════════════════
       REPOS SECTION
    ═══════════════════════════════════════════ */
    #repos {{
      padding: 6rem 2rem;
      max-width: 1200px;
      margin: 0 auto;
    }}

    .repos-header-row {{
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      margin-bottom: 3rem;
      flex-wrap: wrap;
      gap: 1rem;
    }}

    .repos-title {{
      font-family: var(--font-display);
      font-size: clamp(1.5rem, 4vw, 2.2rem);
      font-weight: 700;
      color: #e8f4fd;
      letter-spacing: -0.02em;
    }}

    /* Masonry-inspired repo grid */
    .repo-cards {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
      gap: 1rem;
    }}

    .repo-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      padding: 1.5rem;
      display: flex;
      flex-direction: column;
      gap: 0.75rem;
      position: relative;
      overflow: hidden;
      transition: border-color 0.25s ease, transform 0.25s ease, box-shadow 0.25s ease;
      cursor: pointer;
    }}

    .repo-card::before {{
      content: '';
      position: absolute;
      top: 0; left: 0;
      width: 100%; height: 100%;
      background: radial-gradient(ellipse 60% 40% at 50% 0%, rgba(79,195,247,0.04) 0%, transparent 70%);
      opacity: 0;
      transition: opacity 0.3s ease;
      pointer-events: none;
    }}

    .repo-card:hover {{
      border-color: rgba(79,195,247,0.3);
      transform: translateY(-3px);
      box-shadow: 0 8px 32px rgba(0,0,0,0.3), 0 0 0 1px rgba(79,195,247,0.08);
    }}

    .repo-card:hover::before {{
      opacity: 1;
    }}

    /* Featured card — first one is slightly larger feel */
    .repo-card.featured {{
      border-color: rgba(79,195,247,0.2);
      background: linear-gradient(135deg, var(--surface) 0%, rgba(79,195,247,0.03) 100%);
    }}

    .repo-card-top {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 0.5rem;
    }}

    .repo-card-name {{
      font-family: var(--font-display);
      font-size: 1rem;
      font-weight: 700;
      color: #e8f4fd;
      text-decoration: none;
      transition: color 0.2s ease;
    }}

    .repo-card-name:hover {{
      color: var(--accent);
    }}

    .repo-card-arrow {{
      color: var(--muted);
      font-size: 0.8rem;
      transition: color 0.2s ease, transform 0.2s ease;
      flex-shrink: 0;
      margin-top: 2px;
    }}

    .repo-card:hover .repo-card-arrow {{
      color: var(--accent);
      transform: translate(2px, -2px);
    }}

    .repo-card-desc {{
      font-size: 0.8rem;
      color: var(--muted);
      line-height: 1.55;
      flex: 1;
    }}

    .repo-card-footer {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 0.5rem;
      padding-top: 0.75rem;
      border-top: 1px solid var(--border);
    }}

    .repo-card-lang {{
      display: flex;
      align-items: center;
      gap: 0.4rem;
      font-family: var(--font-mono);
      font-size: 0.65rem;
      color: var(--muted);
      letter-spacing: 0.05em;
    }}

    .lang-circle {{
      width: 8px;
      height: 8px;
      border-radius: 50%;
      flex-shrink: 0;
    }}

    .repo-card-metrics {{
      display: flex;
      gap: 0.75rem;
      font-family: var(--font-mono);
      font-size: 0.65rem;
      color: var(--muted);
      letter-spacing: 0.03em;
    }}

    .repo-card-topics {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.3rem;
    }}

    .topic {{
      background: rgba(79,195,247,0.08);
      color: rgba(79,195,247,0.7);
      border: 1px solid rgba(79,195,247,0.15);
      border-radius: 50px;
      padding: 0.15rem 0.5rem;
      font-family: var(--font-mono);
      font-size: 0.6rem;
      letter-spacing: 0.05em;
    }}

    /* ═══════════════════════════════════════════
       TRENDS TABLE SECTION
    ═══════════════════════════════════════════ */
    #analytics {{
      padding: 4rem 2rem 6rem;
      max-width: 1200px;
      margin: 0 auto;
    }}

    .analytics-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1rem;
    }}

    @media (max-width: 750px) {{ .analytics-grid {{ grid-template-columns: 1fr; }} }}

    .analytics-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      overflow: hidden;
    }}

    .analytics-card-header {{
      padding: 1.25rem 1.5rem;
      border-bottom: 1px solid var(--border);
    }}

    .analytics-card-title {{
      font-family: var(--font-display);
      font-size: 0.9rem;
      font-weight: 600;
      color: #e8f4fd;
    }}

    .table-wrap {{ overflow-x: auto; }}

    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.78rem;
    }}

    th {{
      text-align: left;
      padding: 0.65rem 1rem;
      color: var(--muted);
      font-family: var(--font-mono);
      font-size: 0.62rem;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      font-weight: 400;
      border-bottom: 1px solid var(--border);
      white-space: nowrap;
    }}

    td {{
      padding: 0.75rem 1rem;
      border-bottom: 1px solid var(--border);
      color: var(--text);
    }}

    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: rgba(79,195,247,0.02); }}

    .repo-link {{
      color: var(--accent);
      text-decoration: none;
      font-family: var(--font-mono);
      font-size: 0.72rem;
    }}

    .repo-link:hover {{ text-decoration: underline; }}

    .badge {{
      display: inline-block;
      padding: 0.12rem 0.5rem;
      border-radius: 20px;
      font-family: var(--font-mono);
      font-size: 0.62rem;
      letter-spacing: 0.05em;
      font-weight: 500;
    }}

    .badge-up   {{ background: rgba(129,199,132,0.12); color: var(--accent3); border: 1px solid rgba(129,199,132,0.2); }}
    .badge-down {{ background: rgba(239,154,154,0.12); color: var(--coral);   border: 1px solid rgba(239,154,154,0.2); }}
    .badge-flat {{ background: rgba(93,122,148,0.12);  color: var(--muted);   border: 1px solid rgba(93,122,148,0.2); }}

    /* ═══════════════════════════════════════════
       FOOTER
    ═══════════════════════════════════════════ */
    #footer {{
      padding: 5rem 2rem 3rem;
      text-align: center;
      position: relative;
      overflow: hidden;
    }}

    #footer::before {{
      content: '';
      position: absolute;
      top: 0; left: 50%;
      transform: translateX(-50%);
      width: 600px;
      height: 1px;
      background: linear-gradient(90deg, transparent, var(--border2), transparent);
    }}

    .footer-inner {{
      max-width: 600px;
      margin: 0 auto;
    }}

    .footer-logo {{
      font-family: var(--font-display);
      font-size: 1.5rem;
      font-weight: 800;
      color: #e8f4fd;
      letter-spacing: -0.02em;
      margin-bottom: 0.75rem;
    }}

    .footer-logo span {{
      color: var(--accent);
    }}

    .footer-tagline {{
      font-family: var(--font-mono);
      font-size: 0.68rem;
      color: var(--muted);
      letter-spacing: 0.1em;
      text-transform: uppercase;
      margin-bottom: 2rem;
    }}

    .footer-stack {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      justify-content: center;
      margin-bottom: 2.5rem;
    }}

    .stack-pill {{
      padding: 0.3rem 0.75rem;
      border: 1px solid var(--border);
      border-radius: 50px;
      font-family: var(--font-mono);
      font-size: 0.65rem;
      color: var(--muted);
      letter-spacing: 0.06em;
      background: var(--surface);
    }}

    .footer-meta {{
      font-family: var(--font-mono);
      font-size: 0.65rem;
      color: var(--muted);
      letter-spacing: 0.05em;
      opacity: 0.6;
    }}

    .footer-meta a {{
      color: var(--accent);
      text-decoration: none;
      opacity: 0.8;
    }}

    .footer-meta a:hover {{ opacity: 1; }}

    /* ═══════════════════════════════════════════
       UTILITIES
    ═══════════════════════════════════════════ */
    .section-sep {{
      width: 100%;
      padding: 0 2rem;
    }}

    .section-sep-line {{
      height: 1px;
      background: linear-gradient(90deg, transparent, var(--border), transparent);
    }}

    @media (max-width: 600px) {{
      .stats-header, .repos-header-row {{ flex-direction: column; align-items: flex-start; }}
      .hero-name {{ font-size: 2.8rem; }}
    }}
  </style>
</head>
<body>

<!-- ════════════════════════════════════════════
     HERO
════════════════════════════════════════════ -->
<section id="hero">
  <div class="hero-inner">
    <div class="hero-eyebrow">GitHub Portfolio</div>

    <div class="hero-avatar-wrap">
      {'<img class="hero-avatar" src="' + avatar + '" alt="' + owner + '"><div class="hero-avatar-ring"></div><div class="hero-avatar-ring2"></div>' if avatar else '<div class="hero-avatar-ph">◈</div><div class="hero-avatar-ring"></div><div class="hero-avatar-ring2"></div>'}
    </div>

    <h1 class="hero-name">{owner}</h1>

    {'<p class="hero-bio">' + bio + '</p>' if bio else ''}
    {'<p class="hero-location">📍 ' + location + '</p>' if location else ''}

    <button class="hero-cta" onclick="document.getElementById('intro').scrollIntoView({{behavior:'smooth'}})">
      Explore Stats ↓
    </button>
  </div>

  <div class="hero-scroll-hint">
    <div class="scroll-arrow"></div>
    <span>scroll</span>
  </div>
</section>

<!-- ════════════════════════════════════════════
     INTRO
════════════════════════════════════════════ -->
<section id="intro">
  <div class="section-label reveal">About this Dashboard</div>

  <h2 class="intro-heading reveal reveal-delay-1">
    A living archive of<br><em>every commit, clone &amp; star</em>
  </h2>

  <p class="intro-body reveal reveal-delay-2">
    GitEternal tracks GitHub traffic data beyond the standard 14-day window,
    preserving long-term repository metrics — clones, views, stars, forks —
    into a permanent, queryable vault. This dashboard surfaces those insights
    in real time.
  </p>

  <div class="intro-tags reveal reveal-delay-3">
    <span class="intro-tag">Traffic Harvesting</span>
    <span class="intro-tag">Long-term Archival</span>
    <span class="intro-tag">GitHub Actions</span>
    <span class="intro-tag">Python</span>
    <span class="intro-tag">Auto-generated</span>
    <span class="intro-tag">Self-contained</span>
  </div>
</section>

<div class="section-sep"><div class="section-sep-line"></div></div>

<!-- ════════════════════════════════════════════
     STATS
════════════════════════════════════════════ -->
<section id="stats">
  <div class="stats-header">
    <div>
      <div class="section-label reveal" style="justify-content:flex-start;">
        <span style="width:40px;height:1px;background:var(--accent);opacity:0.4;display:block;"></span>
        Metrics
      </div>
      <h2 class="stats-title reveal reveal-delay-1">Portfolio at a glance</h2>
    </div>
    <div class="stats-subtitle reveal reveal-delay-2" id="stats-generated"></div>
  </div>

  <!-- Primary stat grid -->
  <div class="stat-grid" id="stat-strip"></div>

  <!-- Secondary pills -->
  <div class="stat-row" id="stat-pills" style="margin-top:1rem;"></div>

  <!-- Charts -->
  <div class="charts-grid" style="margin-top:2rem;">
    <div class="chart-card reveal">
      <div class="chart-card-header">
        <div class="chart-card-title">Activity — last 365 days</div>
        <div class="chart-card-sub">Clones &amp; Views</div>
      </div>
      <div class="chart-card-body">
        <div class="chart-wrap"><canvas id="activityChart"></canvas></div>
        <div class="chart-legend">
          <span><span class="legend-dot" style="background:var(--accent)"></span>Clones</span>
          <span><span class="legend-dot" style="background:var(--accent2)"></span>Views</span>
        </div>
      </div>
    </div>

    <div class="chart-card reveal reveal-delay-2">
      <div class="chart-card-header">
        <div class="chart-card-title">Language Breakdown</div>
        <div class="chart-card-sub">By repo count</div>
      </div>
      <div class="chart-card-body">
        <div class="lang-bar" id="lang-bar"></div>
        <div class="lang-legend" id="lang-legend"></div>
      </div>
    </div>
  </div>
</section>

<div class="section-sep"><div class="section-sep-line"></div></div>

<!-- ════════════════════════════════════════════
     REPOS
════════════════════════════════════════════ -->
<section id="repos">
  <div class="repos-header-row">
    <div>
      <div class="section-label reveal" style="justify-content:flex-start;">
        <span style="width:40px;height:1px;background:var(--accent);opacity:0.4;display:block;"></span>
        Repositories
      </div>
      <h2 class="repos-title reveal reveal-delay-1">All tracked repos</h2>
    </div>
    <div class="stats-subtitle reveal reveal-delay-2" id="repos-count"></div>
  </div>

  <div class="repo-cards" id="repo-cards"></div>
</section>

<div class="section-sep"><div class="section-sep-line"></div></div>

<!-- ════════════════════════════════════════════
     ANALYTICS TABLES
════════════════════════════════════════════ -->
<section id="analytics">
  <div class="section-label reveal" style="justify-content:flex-start;margin-bottom:1.5rem;">
    <span style="width:40px;height:1px;background:var(--accent);opacity:0.4;display:block;"></span>
    Analytics
  </div>

  <div class="analytics-grid">
    <div class="analytics-card reveal">
      <div class="analytics-card-header">
        <div class="analytics-card-title">Week-over-Week Trends</div>
      </div>
      <div class="table-wrap">
        <table id="trends-table">
          <thead>
            <tr>
              <th>Repository</th>
              <th>This Week</th>
              <th>Last Week</th>
              <th>Δ</th>
            </tr>
          </thead>
          <tbody></tbody>
        </table>
      </div>
    </div>

    <div class="analytics-card reveal reveal-delay-2">
      <div class="analytics-card-header">
        <div class="analytics-card-title">Top by Stars</div>
      </div>
      <div class="table-wrap">
        <table id="stars-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Repository</th>
              <th>Stars</th>
              <th>Forks</th>
            </tr>
          </thead>
          <tbody></tbody>
        </table>
      </div>
    </div>
  </div>
</section>

<!-- ════════════════════════════════════════════
     FOOTER
════════════════════════════════════════════ -->
<footer id="footer">
  <div class="footer-inner reveal">
    <div class="footer-logo">Git<span>Eternal</span></div>
    <div class="footer-tagline">Preserving GitHub history, forever</div>

    <div class="footer-stack">
      <span class="stack-pill">Python 3.12</span>
      <span class="stack-pill">GitHub Actions</span>
      <span class="stack-pill">Pydantic</span>
      <span class="stack-pill">httpx</span>
      <span class="stack-pill">GitHub Pages</span>
    </div>

    <div class="footer-meta">
      Powered by <a href="https://github.com/{owner}/GitEternal" target="_blank">GitEternal</a>
      &nbsp;·&nbsp; Data stored privately
      &nbsp;·&nbsp; Dashboard auto-generated weekly
    </div>
  </div>
</footer>

<!-- ════════════════════════════════════════════
     DATA + SCRIPTS
════════════════════════════════════════════ -->
<script>
const SUMMARY      = {summary_json};
const TOP_REPOS    = {top_repos_json};
const TRENDS       = {trends_json};
const CHART_DATA   = {chart_data_json};
const OWNER_STATS  = {owner_stats_json};

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
  const s = v >= 0 ? '+' : '';
  const c = v > 0 ? 'badge-up' : v < 0 ? 'badge-down' : 'badge-flat';
  return `<span class="badge ${{c}}">${{s}}${{v}}%</span>`;
}}

// ── Stat strip ────────────────────────────────────────────────────────────────
function renderStats() {{
  const primary = [
    {{ label:'Repos',          value:fmt(SUMMARY.total_repos),       icon:'◫', color:'var(--accent)'  }},
    {{ label:'Stars',          value:fmt(SUMMARY.total_stars),       icon:'✦', color:'var(--gold)'    }},
    {{ label:'Forks',          value:fmt(SUMMARY.total_forks),       icon:'⑂', color:'var(--accent2)' }},
    {{ label:'Lifetime Clones',value:fmt(SUMMARY.lifetime_clones),   icon:'↓', color:'var(--accent3)' }},
    {{ label:'Unique Cloners', value:fmt(SUMMARY.lifetime_uniques),  icon:'◎', color:'var(--accent)'  }},
    {{ label:'Commits',        value:fmt(OWNER_STATS.total_commits), icon:'●', color:'var(--accent2)' }},
    {{ label:'Pull Requests',  value:fmt(OWNER_STATS.total_prs),     icon:'⇌', color:'var(--accent)'  }},
    {{ label:'Followers',      value:fmt(OWNER_STATS.followers),     icon:'◈', color:'var(--gold)'    }},
  ];

  const strip = document.getElementById('stat-strip');
  strip.innerHTML = primary.map((s, i) => `
    <div class="stat-card reveal reveal-delay-${{Math.min(i+1,6)}}" style="--accent-color:${{s.color}}">
      <span class="stat-icon" style="color:${{s.color}}">${{s.icon}}</span>
      <div class="stat-value">${{s.value}}</div>
      <div class="stat-label">${{s.label}}</div>
    </div>`).join('');

  const pills = [
    {{ label:'Total Issues', value:fmt(OWNER_STATS.total_issues) }},
    {{ label:'Following',    value:fmt(OWNER_STATS.following) }},
    {{ label:'Public Repos', value:fmt(OWNER_STATS.public_repos) }},
    {{ label:'Top Language', value:SUMMARY.top_language || '—' }},
  ];

  document.getElementById('stat-pills').innerHTML = pills.map(p => `
    <div class="stat-pill reveal">
      <div class="stat-pill-label">${{p.label}}</div>
      <div class="stat-pill-value">${{p.value}}</div>
    </div>`).join('');

  if (SUMMARY.generated_at) {{
    document.getElementById('stats-generated').textContent =
      'Updated ' + new Date(SUMMARY.generated_at).toLocaleDateString('en-US', {{month:'short',day:'numeric',year:'numeric'}});
  }}

  // Re-observe new elements
  observeAll();
}}

// ── Language bar ──────────────────────────────────────────────────────────────
function renderLangBar() {{
  const langs = SUMMARY.language_breakdown || {{}};
  const total = Object.values(langs).reduce((a,b)=>a+b,0);
  if (!total) return;
  const sorted = Object.entries(langs).sort((a,b)=>b[1]-a[1]);
  const bar = document.getElementById('lang-bar');
  const legend = document.getElementById('lang-legend');
  bar.innerHTML = sorted.map(([lang, count]) => {{
    const pct = (count/total*100).toFixed(1);
    const color = LANG_COLORS[lang] || '#5d7a94';
    return `<div class="lang-bar-seg" style="flex:${{pct}};background:${{color}}" title="${{lang}} ${{pct}}%"></div>`;
  }}).join('');
  legend.innerHTML = sorted.slice(0,8).map(([lang, count]) => {{
    const pct = (count/total*100).toFixed(1);
    const color = LANG_COLORS[lang] || '#5d7a94';
    return `<div class="lang-legend-item">
      <div class="lang-legend-left">
        <span class="lang-dot" style="background:${{color}}"></span>
        ${{lang}}
      </div>
      <span>${{pct}}%</span>
    </div>`;
  }}).join('');
}}

// ── Repo cards ────────────────────────────────────────────────────────────────
function renderRepoCards() {{
  const container = document.getElementById('repo-cards');
  if (!container || !TOP_REPOS.length) return;

  document.getElementById('repos-count').textContent = TOP_REPOS.length + ' repositories';

  container.innerHTML = TOP_REPOS.map((r, idx) => {{
    const [, repo] = r.repo.split('/');
    const isFeatured = idx === 0 ? 'featured' : '';
    const desc   = r.description
      ? `<div class="repo-card-desc">${{r.description}}</div>` : '';
    const lang   = r.language
      ? `<div class="repo-card-lang"><span class="lang-circle" style="background:${{LANG_COLORS[r.language]||'#5d7a94'}}"></span>${{r.language}}</div>` : '';
    const topics = r.topics?.length
      ? `<div class="repo-card-topics">${{r.topics.slice(0,3).map(t=>`<span class="topic">${{t}}</span>`).join('')}}</div>` : '';
    const delay  = `reveal-delay-${{Math.min((idx % 6)+1, 6)}}`;
    return `
    <div class="repo-card ${{isFeatured}} reveal ${{delay}}">
      <div class="repo-card-top">
        <a class="repo-card-name" href="https://github.com/${{r.repo}}" target="_blank">${{repo}}</a>
        <span class="repo-card-arrow">↗</span>
      </div>
      ${{desc}}
      ${{topics}}
      <div class="repo-card-footer">
        ${{lang}}
        <div class="repo-card-metrics">
          <span>✦ ${{fmt(r.stars)}}</span>
          <span>⑂ ${{fmt(r.forks)}}</span>
          <span>↓ ${{fmt(r.lifetime_clones)}}</span>
        </div>
      </div>
    </div>`;
  }}).join('');

  observeAll();
}}

// ── Trends table ──────────────────────────────────────────────────────────────
function renderTrends() {{
  document.querySelector('#trends-table tbody').innerHTML =
    TRENDS.slice(0,12).map(r => {{
      const [,repo] = r.repo.split('/');
      return `<tr>
        <td><a class="repo-link" href="https://github.com/${{r.repo}}" target="_blank">${{repo}}</a></td>
        <td style="font-family:var(--font-mono);font-size:.72rem">${{fmt(r.current_week_clones)}}</td>
        <td style="font-family:var(--font-mono);font-size:.72rem;color:var(--muted)">${{fmt(r.prior_week_clones)}}</td>
        <td>${{fmtPct(r.clone_delta_pct)}}</td>
      </tr>`;
    }}).join('');
}}

// ── Stars table ───────────────────────────────────────────────────────────────
function renderStarsTable() {{
  const sorted = [...TOP_REPOS].sort((a,b)=>(b.stars||0)-(a.stars||0));
  document.querySelector('#stars-table tbody').innerHTML =
    sorted.slice(0,12).map((r,i) => {{
      const [,repo] = r.repo.split('/');
      return `<tr>
        <td style="color:var(--muted);font-family:var(--font-mono);font-size:.7rem">${{i+1}}</td>
        <td><a class="repo-link" href="https://github.com/${{r.repo}}" target="_blank">${{repo}}</a></td>
        <td style="font-family:var(--font-mono);font-size:.72rem">✦ ${{fmt(r.stars)}}</td>
        <td style="font-family:var(--font-mono);font-size:.72rem;color:var(--muted)">⑂ ${{fmt(r.forks)}}</td>
      </tr>`;
    }}).join('');
}}

// ── Activity chart ────────────────────────────────────────────────────────────
function renderChart() {{
  const canvas = document.getElementById('activityChart');
  if (!canvas || !CHART_DATA.length) return;
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.parentElement.getBoundingClientRect().width || 600;
  const H = 180;
  canvas.width  = W * dpr; canvas.height = H * dpr;
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

  function px(i, val) {{
    return [PAD.left + i * xStep, PAD.top + gH - (val / maxY) * gH];
  }}

  // Grid lines
  ctx.strokeStyle = 'rgba(79,195,247,0.06)'; ctx.lineWidth = 1;
  for (let t = 0; t <= 4; t++) {{
    const y = PAD.top + (gH / 4) * t;
    ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(PAD.left + gW, y); ctx.stroke();
  }}

  // Draw filled area under line
  function drawArea(color, key) {{
    const grad = ctx.createLinearGradient(0, PAD.top, 0, PAD.top + gH);
    grad.addColorStop(0, color + '22');
    grad.addColorStop(1, color + '00');
    ctx.beginPath();
    CHART_DATA.forEach((d,i) => {{
      const [x,y] = px(i, d[key]);
      i === 0 ? ctx.moveTo(x,y) : ctx.lineTo(x,y);
    }});
    ctx.lineTo(PAD.left + gW, PAD.top + gH);
    ctx.lineTo(PAD.left, PAD.top + gH);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();
  }}

  function drawLine(color, key) {{
    ctx.beginPath(); ctx.strokeStyle = color; ctx.lineWidth = 1.5;
    CHART_DATA.forEach((d,i) => {{
      const [x,y] = px(i, d[key]);
      i === 0 ? ctx.moveTo(x,y) : ctx.lineTo(x,y);
    }});
    ctx.stroke();
  }}

  drawArea('#4fc3f7', 'clones');
  drawArea('#26a69a', 'views');
  drawLine('#4fc3f7', 'clones');
  drawLine('#26a69a', 'views');

  // X labels
  ctx.fillStyle = '#5d7a94'; ctx.font = '10px DM Mono, monospace'; ctx.textAlign = 'center';
  const step = Math.max(1, Math.floor(CHART_DATA.length / 6));
  CHART_DATA.forEach((d,i) => {{
    if (i % step === 0) {{
      const [x] = px(i, 0);
      ctx.fillText(d.date.slice(0,7), x, H - 8);
    }}
  }});

  // Y label
  ctx.textAlign = 'right';
  ctx.fillText(fmt(maxY), PAD.left - 4, PAD.top + 4);
}}

// ── Scroll reveal ─────────────────────────────────────────────────────────────
const io = new IntersectionObserver((entries) => {{
  entries.forEach(e => {{
    if (e.isIntersecting) {{ e.target.classList.add('visible'); io.unobserve(e.target); }}
  }});
}}, {{ threshold: 0.08 }});

function observeAll() {{
  document.querySelectorAll('.reveal:not(.visible)').forEach(el => io.observe(el));
}}

// ── Init ──────────────────────────────────────────────────────────────────────
renderStats();
renderLangBar();
renderRepoCards();
renderTrends();
renderStarsTable();
renderChart();
observeAll();
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

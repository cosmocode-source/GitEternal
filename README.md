<div align="center">

<img src="https://img.shields.io/badge/GitHub-Native-181717?style=for-the-badge&logo=github&logoColor=white" />
<img src="https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white" />
<img src="https://img.shields.io/badge/Pydantic-v2-E92063?style=for-the-badge&logo=pydantic&logoColor=white" />
<img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" />

<br /><br />

```
       ██████╗ ██╗████████╗███████╗████████╗███████╗██████╗ ███╗   ██╗ █████╗ ██╗
      ██╔════╝ ██║╚══██╔══╝██╔════╝╚══██╔══╝██╔════╝██╔══██╗████╗  ██║██╔══██╗██║
      ██║  ███╗██║   ██║   █████╗     ██║   █████╗  ██████╔╝██╔██╗ ██║███████║██║
      ██║   ██║██║   ██║   ██╔══╝     ██║   ██╔══╝  ██╔══██╗██║╚██╗██║██╔══██║██║
           ╚██████╔╝██║   ██║   ███████╗   ██║   ███████╗██║  ██║██║ ╚████║██║  ██║███████╗
            ╚═════╝ ╚═╝   ╚═╝   ╚══════╝   ╚═╝   ╚══════╝╚═╝  ╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝╚══════╝
```

### **Git as the database. GitHub as the infrastructure. Your data, forever.**

*Harvest GitHub traffic data before it expires. Store it privately. Visualize it publicly.*

<br />

[![Harvest](https://img.shields.io/github/actions/workflow/status/cosmocode-source/GitEternal_v2/01-harvester.yml?label=Harvest&logo=github-actions&logoColor=white&style=flat-square)](https://github.com/cosmocode-source/GitEternal_v2/actions/workflows/01-harvester.yml)
[![Statistics](https://img.shields.io/github/actions/workflow/status/cosmocode-source/GitEternal_v2/02-statistics.yml?label=Statistics&logo=github-actions&logoColor=white&style=flat-square)](https://github.com/cosmocode-source/GitEternal_v2/actions/workflows/02-statistics.yml)
[![Dashboard](https://img.shields.io/badge/Dashboard-Live-brightgreen?style=flat-square&logo=github)](https://cosmocode-source.github.io/My-Git-Statistics)

</div>

---

## The Problem

GitHub's traffic API is powerful but brutally short-sighted — it only retains **14 days** of clone and view data. Miss a week and that history is gone permanently. No export, no backup, no long-term storage. For anyone who cares about their project's growth over months and years, this is a silent data loss problem happening every single day.

## The Solution

GitEternal_v2 runs a weekly automated harvest *before* your data expires, commits it into a private Git repository that acts as a flat-file database, and builds a public GitHub Pages dashboard from aggregated reports — all without touching any infrastructure outside GitHub itself.

No servers. No cloud databases. No subscription. No external credentials. Just Git.

---

## How It Works

```
┌──────────────────────────────────────────────────────────────────────┐
│                        YOUR GITHUB ACCOUNT                           │
│                                                                      │
│  ┌─────────────────────┐      ┌────────────────────────┐            │
│  │     GitEternal_v2      │      │   GitData     │ ← PRIVATE  │
│  │     (this repo)     │─────▶│                        │            │
│  │                     │      │  index.json            │            │
│  │  packages/engine/   │      │  harvest_log.json      │            │
│  │  .github/workflows/ │      │  config.json           │            │
│  └─────────────────────┘      │  data/…/**/*.json      │            │
│             │                 └────────────┬───────────┘            │
│             │                              │                         │
│             └──────────────────────────────┘                         │
│                           reads vault                                │
│                                │                                     │
│                                ▼                                     │
│                  ┌─────────────────────────────┐                    │
│                  │    02-statistics workflow    │                    │
│                  │  generates reports + HTML    │                    │
│                  └──────────────┬──────────────┘                    │
│                                 │ pushes                             │
│                                 ▼                                    │
│                    ┌────────────────────────┐                       │
│                    │    My-Git-Statistics      │ ← PUBLIC              │
│                    │                        │                       │
│                    │  reports/*.json        │                       │
│                    │  docs/index.html       │                       │
│                    └───────────┬────────────┘                       │
│                                │ GitHub Pages                        │
└────────────────────────────────┼────────────────────────────────────┘
                                 ▼
             https://YOUR_USERNAME.github.io/My-Git-Statistics
```

**Three repos. Three responsibilities. One automated pipeline.**

| Repository | Visibility | Role |
|---|---|---|
| `GitEternal_v2` | Private | Engine code, workflow definitions, Python harvester |
| `GitData` | **Private** | Raw traffic vault — daily clones, views, referrers per repo |
| `My-Git-Statistics` | Public | Aggregated dashboard served via GitHub Pages |

---

## Features

- **Permanent history** — collects traffic data weekly, building a record that stretches back as far as you run it
- **Zero infrastructure** — runs entirely on GitHub Actions and GitHub Pages, no servers or external services required
- **Privacy-first** — raw daily data lives in a private repo only you can access; the public dashboard shows only aggregated summaries
- **Fully automated** — set up once, runs every Sunday without any manual intervention
- **Self-contained dashboard** — the GitHub Pages site is a single HTML file with zero build step and no npm; inline data, pure canvas charts
- **Conflict-safe merging** — the harvester merges incoming data with existing ledgers by date deduplication, so re-runs never corrupt history
- **Distributed lock** — a `harvest.lock` file in the vault prevents concurrent runs from racing
- **Failure alerting** — opens a GitHub issue automatically if a harvest run fails
- **Validated schema** — every data file is written and re-read through strict Pydantic v2 models before commit
- **Gap-aware** — detects missing days in the ledger and attempts to backfill from the current API response

---

## Tech Stack

### Engine (`packages/engine/`)

| Component | Technology | Purpose |
|---|---|---|
| Runtime | Python 3.12 | Async harvester and statistics processor |
| HTTP client | [httpx](https://www.python-httpx.org/) | Async GitHub API calls with timeout handling |
| Data validation | [Pydantic v2](https://docs.pydantic.dev/latest/) | Strict schema validation on every read and write |
| Linting | [Ruff](https://docs.astral.sh/ruff/) | Fast Python linter and formatter |
| Testing | pytest + pytest-asyncio | Unit tests for merge logic, schema, and gap detection |

### Infrastructure

| Component | Technology | Purpose |
|---|---|---|
| Automation | GitHub Actions | Scheduled workflows, zero external CI needed |
| Data storage | Git + GitHub | Flat-file JSON committed to a private repo |
| Dashboard hosting | GitHub Pages | Static HTML served from `docs/` folder |
| Charts | Pure Canvas API | Hand-drawn canvas, zero frontend dependencies |
| Serialization | JSON | Human-readable, diff-friendly, Git-native |

### Key design choices

**Why Git as a database?** Git gives you history, checksums, conflict detection, atomic commits, and free hosting — all the properties you want from a time-series store, without the operational cost. Each commit is a timestamped snapshot. Rollback is `git revert`. Backup is `git clone`.

**Why no npm / no build step for the dashboard?** The statistics workflow runs in a vanilla Python environment. Introducing Node.js, npm, or a bundler would add install time, dependency drift risk, and complexity for something that is fundamentally a data display problem. A self-contained HTML file with inline data loads instantly, works offline, and can be inspected by anyone.

**Why Pydantic for JSON files?** The harvester writes data that must be read back correctly months or years later. Pydantic v2 enforces field types, validates sort order, catches duplicates, and checksums each month's data — turning silent data corruption into loud exceptions at write time.

---

## Repository Structure

```
GitEternal_v2/
│
├── .github/
│   └── workflows/
│       ├── 00-setup.yml          # One-time bootstrap — creates both repos, enables Pages, self-deletes
│       ├── 01-harvester.yml      # Weekly: collect traffic from GitHub API → commit to vault
│       └── 02-statistics.yml     # Weekly: read vault → generate reports → deploy dashboard
│
├── packages/
│   └── engine/
│       ├── __init__.py
│       ├── harvester.py          # Main entry point — discovers repos, runs harvest loop, manages lock
│       ├── statistics.py         # Reads vault, generates JSON reports + self-contained HTML dashboard
│       ├── api.py                # GitHub API wrappers: clones, views, referrers, rate limit
│       ├── merge.py              # Time-series merge (dedup by date, sort ascending, gap detection)
│       ├── schema.py             # Pydantic models: MonthLedger, VaultIndex, HarvestRun, etc.
│       ├── lock.py               # Distributed mutex via harvest.lock file in vault
│       ├── requirements.txt      # httpx, pydantic>=2, pytest, pytest-asyncio, ruff
│       └── tests/
│           ├── test_schema.py
│           ├── test_merge.py
│           └── test_gaps.py
│
├── docs/
│   ├── PHASE1_ANALYSIS.md        # Architecture analysis of the original codebase
│   └── PHASE2_DESIGN.md          # System design document for the new approach
│
└── README.md
```

### Vault structure (`GitData`, branch `GitData`)

```
GitData/
│
├── index.json            # VaultIndex: lifetime totals + available months per repo
├── harvest_log.json      # HarvestLog: last 50 run records with status + errors
├── config.json           # { "tracked_repos": ["owner/repo", ...] }
├── harvest.lock          # Distributed mutex — auto-cleared after 2 hours if stale
│
└── data/
    └── {owner}/
        └── {repo}/
            └── {year}/
                └── {YYYY-MM}.json    # MonthLedger: daily clones, views, referrers + checksum
```

### Statistics structure (`My-Git-Statistics`, branch `main`)

```
My-Git-Statistics/
│
├── reports/
│   ├── summary.json        # Portfolio totals: lifetime clones, uniques, most active repo
│   ├── top_repos.json      # Repos ranked by lifetime clones
│   ├── trends.json         # Week-over-week clone + view deltas per repo
│   └── chart_data.json     # Daily aggregated activity for the last 365 days
│
└── docs/
    └── index.html          # Self-contained dashboard — inline data, zero external deps
```

---

## Data Schema

### `MonthLedger` — one file per repo per month

```json
{
  "month": "2025-04",
  "repo": "alice/my-project",
  "clones": [
    { "date": "2025-04-01", "count": 12, "uniques": 7 },
    { "date": "2025-04-02", "count": 9,  "uniques": 5 }
  ],
  "views": [
    { "date": "2025-04-01", "count": 34, "uniques": 18 }
  ],
  "referrers": [
    { "captured_on": "2025-04-07", "source": "google.com", "count": 5, "uniques": 3 }
  ],
  "checksum": "sha256:a3f9..."
}
```

Pydantic enforces: dates sorted ascending, no duplicate dates, non-negative counts, valid checksum format.

### `VaultIndex` — top-level summary

```json
{
  "version": 2,
  "repos": {
    "alice/my-project": {
      "first_date": "2024-01-15",
      "last_date": "2025-04-07",
      "total_clone_days": 180,
      "lifetime_clones": 2847,
      "lifetime_uniques": 931,
      "available_months": ["2024-01", "2024-02"],
      "last_harvest": "2025-04-07T06:12:33+00:00"
    }
  }
}
```

---

## Workflows In Depth

### `00-setup.yml` — Initial Setup

Runs **once**, manually. Uses the built-in `gh` CLI to:

1. Create `GitData` (private) with an orphan commit on branch `GitData`
2. Create `My-Git-Statistics` (public) with placeholder `docs/index.html` on `main`
3. Enable GitHub Pages on `My-Git-Statistics` pointing at `docs/`
4. Store `GIT_ETERNAL_DATA_REPO` and `GIT_STATISTICS_REPO` as secrets in this repo
5. Print instructions for the 3 PAT secrets you need to add manually
6. **Delete itself** from the repository so it never appears in the Actions tab again

### `01-harvester.yml` — Weekly Harvest

Runs every **Sunday at 06:00 UTC** (or on demand).

```
checkout repo
  → install Python deps
    → verify HARVEST_TOKEN identity + scopes
      → clone GitData
        → acquire harvest.lock
          → discover accessible repos via traffic API probe
            → for each repo:
                fetch clones (14d)  ──┐
                fetch views  (14d)  ──┼──▶ merge into MonthLedger ──▶ write JSON
                fetch referrers     ──┘
            → update index.json
            → append to harvest_log.json
            → release lock
            → commit + push to GitData
              → on failure: open GitHub issue
```

Rate limit aware — aborts early if fewer than 50 API calls remain. Batches traffic probes 8 at a time concurrently.

### `02-statistics.yml` — Statistics & Pages

Triggered automatically by `workflow_run` after a successful harvest, or on demand.

```
clone GitData (read-only, depth 1)
  → run statistics.py
      → load VaultIndex + all MonthLedgers
      → generate summary.json, top_repos.json, trends.json, chart_data.json
      → render self-contained index.html (data inlined as JS constants)
  → clone My-Git-Statistics
    → copy reports/ + docs/
      → commit + push
        → GitHub Pages auto-deploys
```

---

## Setup Guide

### Prerequisites

- A GitHub account with repositories you want to track
- This repository cloned or forked under your account (set to **private**)

---

### Step 1 — Create `SETUP_TOKEN`

Go to **GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)**

Create a token with these scopes:
- `repo` — full repository access
- `workflow` — manage GitHub Actions workflows

---

### Step 2 — Add `SETUP_TOKEN` secret

In **this repo**: Settings → Secrets and variables → Actions → New repository secret

| Name | Value |
|------|-------|
| `SETUP_TOKEN` | The classic PAT you just created |

---

### Step 3 — Run the setup workflow

**Actions → "00 · Initial Setup" → Run workflow**

Wait ~2 minutes. The workflow creates both repos, enables Pages, prints what to do next, then deletes itself.

---

### Step 4 — Create fine-grained PATs

Go to **GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens**

**Token A — for `GitData`**
- Repository access: Only `GitData`
- Permissions → Contents: **Read and write**

**Token B — for `My-Git-Statistics`**
- Repository access: Only `My-Git-Statistics`
- Permissions → Contents: **Read and write**

---

### Step 5 — Add the remaining 3 secrets

In **this repo**: Settings → Secrets and variables → Actions

| Secret | Value |
|--------|-------|
| `HARVEST_TOKEN` | Classic PAT with `repo` scope |
| `GIT_ETERNAL_DATA_TOKEN` | Fine-grained PAT for `GitData` |
| `GIT_STATISTICS_TOKEN` | Fine-grained PAT for `My-Git-Statistics` |

> `GIT_ETERNAL_DATA_REPO` and `GIT_STATISTICS_REPO` were already set by the setup workflow.

---

### Step 6 — First harvest

**Actions → "01 · Harvest Traffic Data" → Run workflow**

The statistics workflow triggers automatically after. Dashboard goes live at:

```
https://YOUR_USERNAME.github.io/My-Git-Statistics
```

> GitHub Pages can take up to 10 minutes on the very first deploy.

---

## Automation Schedule

| Workflow | Schedule | Trigger |
|----------|----------|---------|
| Harvest | Every Sunday 06:00 UTC | `schedule` cron |
| Statistics | After each successful harvest | `workflow_run` event |

Both can also be triggered manually at any time from the Actions tab.

---

## Token Reference

| Secret | Type | Scopes / Permissions | Used For |
|--------|------|---------------------|----------|
| `SETUP_TOKEN` | Classic PAT | `repo`, `workflow` | One-time setup only |
| `HARVEST_TOKEN` | Classic PAT | `repo` | Reading traffic API for all your repos |
| `GIT_ETERNAL_DATA_TOKEN` | Fine-grained PAT | Contents: read/write on `GitData` | Writing harvested data to vault |
| `GIT_STATISTICS_TOKEN` | Fine-grained PAT | Contents: read/write on `My-Git-Statistics` | Writing reports and dashboard HTML |

**Why a classic PAT for `HARVEST_TOKEN`?**
GitHub's traffic API requires either a classic PAT with `repo` scope, or a fine-grained PAT with "Repository traffic: Read" on *each individual repo*. For tracking many repos across multiple organizations, the classic PAT is significantly simpler.

---

## Privacy Model

```
Private (GitData)              Public (My-Git-Statistics)
──────────────────────────────────────  ─────────────────────────────────────
Exact daily clone counts                Lifetime clone totals per repo
Exact daily view counts                 Lifetime unique cloner totals
Referrer sources and counts             Week-over-week trend percentages
Which repos you own                     Aggregated daily activity (last 365d)
Harvest run history and errors          Most active repo name
```

The public dashboard never exposes per-day breakdowns, referrer details, or harvest metadata. It shows the same kind of summary visible on any public GitHub repo's Insights tab.

---

## Troubleshooting

**Harvest returns 403 on some repos**

The traffic API requires admin/push access *and* the right token scope. Common causes:
- Classic PAT missing the `repo` scope — regenerate with full `repo` scope
- For org repos: you must be an **org owner**, not just a member
- Fine-grained PATs need **"Repository traffic: Read"** set explicitly per repo

**Statistics workflow doesn't trigger after harvest**

The `workflow_run` event only fires if the trigger workflow is on the default branch. Verify `01-harvester.yml` is committed to `main`. You can always trigger `02-statistics` manually from the Actions tab.

**GitHub Pages shows 404 or the placeholder**

- Pages can take up to 10 minutes on first deploy
- Verify: `My-Git-Statistics` → Settings → Pages → Source is `main` branch, `/docs` folder
- Check the Pages deployment tab in `My-Git-Statistics` for build errors

**Harvest lock is stuck**

The `harvest.lock` file auto-expires after 2 hours. If a run was interrupted, the next run detects the stale lock and overwrites it. You can also delete `harvest.lock` directly in `GitData` if needed.

---

## Contributing

```bash
# Clone and set up
git clone https://github.com/YOUR_USERNAME/GitEternal_v2.git
cd GitEternal_v2
pip install -r packages/engine/requirements.txt

# Run tests
python -m pytest packages/engine/tests/ -v

# Lint
ruff check packages/engine/
ruff format packages/engine/
```

All PRs should include tests for any changes to `merge.py`, `schema.py`, or `statistics.py`. The existing 14-test suite covers merge correctness, schema validation, and gap detection.

---

## Roadmap

- [ ] Per-repo sparkline charts on the dashboard
- [ ] Email/webhook notification when a repo crosses a clone milestone
- [ ] CSV export of raw ledger data from the statistics workflow
- [ ] Support for tracking repos you collaborate on but don't own
- [ ] Multi-owner mode — track an entire GitHub org's traffic in one vault

---

## License

MIT — see [LICENSE](LICENSE) for details.

---

<div align="center">

Built with no external services, no subscriptions, and no lock-in.
<br />
Just Python, Git, and GitHub Actions.

<br /><br />

**⭐ Star this repo if GitEternal_v2 is useful to you.**

</div>

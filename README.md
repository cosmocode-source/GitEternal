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

[![Harvest](https://img.shields.io/github/actions/workflow/status/YOUR_USERNAME/GitEternal/01-harvester.yml?label=Harvest&logo=github-actions&logoColor=white&style=flat-square)](https://github.com/YOUR_USERNAME/GitEternal/actions/workflows/01-harvester.yml)
[![Statistics](https://img.shields.io/github/actions/workflow/status/YOUR_USERNAME/GitEternal/02-statistics.yml?label=Statistics&logo=github-actions&logoColor=white&style=flat-square)](https://github.com/YOUR_USERNAME/GitEternal/actions/workflows/02-statistics.yml)
[![Dashboard](https://img.shields.io/badge/Dashboard-Live-brightgreen?style=flat-square&logo=github)](https://YOUR_USERNAME.github.io/My-Git-Statistics)

</div>

---

## The Problem

GitHub's traffic API is powerful but brutally short-sighted — it only retains **14 days** of clone and view data. Miss a week and that history is gone permanently. No export, no backup, no long-term storage. For anyone who cares about their project's growth over months and years, this is a silent data loss problem happening every single day.

## The Solution

GitEternal runs a weekly automated harvest *before* your data expires, commits it into a private Git repository that acts as a flat-file database, and builds a public GitHub Pages dashboard from aggregated reports — all without touching any infrastructure outside GitHub itself.

No servers. No cloud databases. No subscription. No external credentials. Just Git.

---

## How It Works

**One repo. Three branches. Fully isolated histories.**

```
┌─────────────────────────────────────────────────────────────────────┐
│                      GitEternal  (single repo)                      │
│                                                                      │
│  ┌──────────────────┐   push data    ┌──────────────────────────┐   │
│  │   main branch    │ ─────────────▶ │   gitdata branch         │   │
│  │                  │                │   (orphan — no shared    │   │
│  │  packages/       │ ◀──────────── │    history with main)    │   │
│  │  .github/        │   clone vault  │                          │   │
│  │  workflows/      │                │  index.json              │   │
│  │  README.md       │                │  harvest_log.json        │   │
│  └──────────────────┘                │  config.json             │   │
│          │                           │  owner_stats.json        │   │
│          │                           │  data/{owner}/{repo}/    │   │
│          │                           │    {year}/{YYYY-MM}.json │   │
│          │                           └──────────────────────────┘   │
│          │                                                           │
│          │ generate + push site                                      │
│          ▼                                                           │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │   site branch  (orphan — no shared history with main)        │   │
│  │                                                              │   │
│  │   index.html      ← full dashboard                          │   │
│  │   reports/*.json  ← aggregated summaries                    │   │
│  │   README.md                                                  │   │
│  └──────────────────────────────────┬───────────────────────────┘  │
│                                     │ GitHub Pages                   │
└─────────────────────────────────────┼─────────────────────────────-─┘
                                      ▼
              https://YOUR_USERNAME.github.io/GitEternal
```

**One repo. Three responsibilities. Isolated histories.**

| Branch | Orphan | Visibility | Role |
|--------|--------|------------|------|
| `main` | No | Private | Engine code, workflows, Python harvester |
| `gitdata` | **Yes** | Private (branch) | Raw traffic vault — daily JSON ledgers |
| `site` | **Yes** | Public via Pages | Static dashboard HTML + JSON reports |

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
GitEternal/  (single repo)
│
├── [main branch] ──────────────────────────────────────────────────
│   ├── .github/
│   │   └── workflows/
│   │       ├── 00-setup.yml        ← creates gitdata + site branches
│   │       ├── 01-harvester.yml    ← harvests traffic → gitdata
│   │       └── 02-statistics.yml   ← gitdata → generates HTML → site
│   ├── packages/
│   │   └── engine/
│   │       ├── api.py              ← GitHub API calls
│   │       ├── harvester.py        ← main harvest orchestrator
│   │       ├── merge.py            ← deduplicating ledger merge logic
│   │       ├── schema.py           ← Pydantic v2 data models
│   │       ├── statistics.py       ← report + HTML dashboard generator
│   │       ├── lock.py             ← distributed harvest lock
│   │       ├── requirements.txt
│   │       └── tests/
│   └── README.md
│
├── [gitdata branch — orphan] ──────────────────────────────────────
│   ├── index.json                  ← lifetime stats per repo
│   ├── harvest_log.json            ← last 50 harvest run records
│   ├── config.json                 ← tracked repos config
│   ├── owner_stats.json            ← GitHub profile + commit stats
│   └── data/
│       └── {owner}/
│           └── {repo}/
│               └── {year}/
│                   └── {YYYY-MM}.json
│
└── [site branch — orphan] ─────────────────────────────────────────
    ├── index.html                  ← full dashboard (GitHub Pages root)
    ├── reports/
    │   ├── summary.json
    │   ├── top_repos.json
    │   └── trends.json
    └── README.md
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

Create a token with scopes: `repo` + `workflow`

---

### Step 2 — Add `SETUP_TOKEN` secret

**This repo** → Settings → Secrets and variables → Actions → New repository secret

| Name | Value |
|------|-------|
| `SETUP_TOKEN` | The classic PAT from Step 1 |

---

### Step 3 — Run the setup workflow

**Actions → "00 · Setup Branches" → Run workflow**

This creates the `gitdata` and `site` orphan branches inside this repo, enables GitHub Pages from the `site` branch, and prints what to do next.

> During testing, open `00-setup.yml` and uncomment `if: false` on the last step to prevent self-deletion.

---

### Step 4 — Add the 2 operational secrets

After setup completes, add these at **Settings → Secrets and variables → Actions**:

| Secret | Type | Scopes | Purpose |
|--------|------|--------|---------|
| `HARVEST_TOKEN` | Classic PAT | `repo` | Calls GitHub traffic API + fetches your profile/commit stats |
| `ACTIONS_TOKEN` | Classic PAT | `repo`, `workflow` | Writes to `gitdata` and `site` branches |

> `SETUP_TOKEN` can be the same PAT reused as `ACTIONS_TOKEN` if it has `repo` + `workflow` scopes.

---

### Step 5 — First harvest

**Actions → "01 · Harvest Traffic Data" → Run workflow**

The `02 · Statistics` workflow triggers automatically after. Dashboard goes live at:

```
https://YOUR_USERNAME.github.io/GitEternal
```

> GitHub Pages can take up to 10 minutes on first deploy.

---

## Automation Schedule

| Workflow | Schedule | Trigger |
|----------|----------|---------|
| 00 · Setup | Manual only | `workflow_dispatch` |
| 01 · Harvest | Every Sunday 06:00 UTC | `schedule` cron + `workflow_dispatch` |
| 02 · Statistics | After each successful harvest | `workflow_run` + `workflow_dispatch` |

Both 01 and 02 can be triggered manually at any time from the Actions tab.


---

## Token Reference

| Secret | Type | Required Scopes | Used For |
|--------|------|-----------------|----------|
| `SETUP_TOKEN` | Classic PAT | `repo`, `workflow` | One-time branch creation + Pages setup |
| `HARVEST_TOKEN` | Classic PAT | `repo` | GitHub traffic API, search API (commits/PRs/issues), user profile |
| `ACTIONS_TOKEN` | Classic PAT | `repo`, `workflow` | Writing JSON to `gitdata` branch; writing HTML to `site` branch |

**Can I reuse one token for everything?**
Yes — a single classic PAT with `repo` + `workflow` scopes works for all three secrets. Using separate tokens is better for security (principle of least privilege) but not required.

**Why classic PATs and not fine-grained?**
GitHub's traffic API requires either a classic PAT with `repo` scope, or a fine-grained PAT with "Repository traffic: Read" set per-repo. For tracking many repos, classic is simpler. Fine-grained tokens work fine for `ACTIONS_TOKEN` if you prefer.

**What does `owner_stats.json` contain?**
Total commit count, PR count, issue count, followers, and profile info fetched once per harvest via `/users/{owner}` and GitHub's search API. Stored privately in `gitdata`, used only for dashboard stat cards.


---

## Privacy Model

```
gitdata branch (private history)        site branch (public via Pages)
────────────────────────────────────    ─────────────────────────────────────
Exact daily clone counts                Lifetime clone totals per repo
Exact daily view counts                 Lifetime unique cloner totals
Referrer sources + counts               Week-over-week trend percentages
Raw owner_stats.json                    Aggregated daily activity (last 12mo)
Harvest run history + errors            Star/fork/watcher counts per repo
Which repos you own                     Language breakdown + repo descriptions
```

The `site` branch (and therefore the public dashboard) never exposes per-day breakdowns, referrer details, harvest metadata, or raw commit/PR/issue data. It shows the same kind of summary visible on any public GitHub profile.

**Branch isolation:** `gitdata` and `site` are orphan branches — they share no git history with `main` or each other. You can delete either branch and recreate it without affecting the engine code on `main`.


---

## Limitations & Edge Cases

**GitHub Pages visibility**
GitHub Pages on a private repo requires a paid plan (GitHub Pro/Teams). If your `GitEternal` repo is private, you have two options: (a) make the repo public, or (b) use a separate public repo for the site branch — the old multi-repo approach. The `site` branch content itself has no private data so making the repo public is safe.

**Profile README auto-update**
GitHub does not provide an API to update your profile README (`{username}/{username}`) from an external workflow without your PAT. GitEternal does not auto-update your profile README because that requires write access to a separate repo. Workaround: manually add this badge to your profile README once:
```markdown
[![Dashboard](https://img.shields.io/badge/Stats-Dashboard-blue?logo=github)](https://YOUR_USERNAME.github.io/GitEternal)
```

**Branch protection**
If you have branch protection rules on `main`, the setup workflow's self-delete step may fail (it tries to delete a file directly on `main`). Solution: temporarily disable protection, or skip the self-delete step entirely by keeping `if: false` on that step.

**Concurrent runs**
The harvester uses a `harvest.lock` file in the `gitdata` branch to prevent concurrent runs. If a run is interrupted, the lock auto-expires after 2 hours. You can also delete `harvest.lock` directly from the `gitdata` branch via the GitHub UI.

**First harvest timing**
The `site` branch is initialized with a placeholder page. The real dashboard only appears after the first successful harvest + statistics run. This takes ~3–8 minutes depending on how many repos you have.

**Re-running setup**
The setup workflow checks if `gitdata` and `site` branches already exist before creating them — so re-running it is safe. It will skip existing branches and only create missing ones.

## Troubleshooting

**Harvest returns 403 on some repos**
The traffic API requires admin/push access and `repo` scope on `HARVEST_TOKEN`. Check that the token hasn't expired and has the full `repo` scope, not just `public_repo`.

**`gitdata` or `site` branch doesn't exist**
Re-run the `00 · Setup Branches` workflow. It is idempotent — it skips branches that already exist and only creates missing ones.

**Statistics workflow doesn't trigger after harvest**
The `workflow_run` event only fires if `01-harvester.yml` is on the default branch (`main`). Verify the file is committed to `main`, not a feature branch. You can always trigger `02 · Statistics` manually.

**GitHub Pages shows the placeholder or 404**
- Pages can take up to 10 minutes on first deploy
- Verify: **Settings → Pages → Source** is set to the `site` branch, root folder (`/`)
- Check the Pages deployment tab for build errors
- The `02 · Statistics` workflow must have run at least once successfully

**Harvest lock is stuck**
The `harvest.lock` file auto-expires after 2 hours. If a run was interrupted, the next run detects the stale lock and overwrites it. You can also delete `harvest.lock` from the `gitdata` branch in the GitHub UI.

**Push to gitdata/site fails with 403**
`ACTIONS_TOKEN` needs `repo` + `workflow` scopes. Regenerate it if it has expired. Verify the token is stored under the exact name `ACTIONS_TOKEN` in Settings → Secrets.

## Contributing

```bash
# Clone and set up
git clone https://github.com/YOUR_USERNAME/GitEternal.git
cd GitEternal
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

**⭐ Star this repo if GitEternal is useful to you.**

</div>

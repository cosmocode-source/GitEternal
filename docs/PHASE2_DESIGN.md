# Phase 2 — System Design

## Problem Recap

Users won't provide account credentials (PAT), so the original model of "give me your HARVEST_TOKEN and I'll collect your data" is not viable for a public deployment. The new model shifts to **self-sovereign, GitHub-native analytics** — users fork/use GitEternal in their own GitHub account and data never leaves GitHub.

---

## Component Map

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  USER'S GITHUB ACCOUNT                                                      │
│                                                                             │
│  ┌─────────────────────────┐     ┌─────────────────────────┐               │
│  │  GitEternal (main)      │     │  git-eternal-data       │               │
│  │  (forked/cloned)        │     │  (auto-created)         │               │
│  │                         │     │                         │               │
│  │  packages/engine/  ─────┼─────►  index.json            │               │
│  │  .github/workflows/     │     │  harvest_log.json       │               │
│  │    00-setup.yml         │     │  config.json            │               │
│  │    01-harvester.yml     │     │  data/owner/repo/...    │               │
│  │    02-statistics.yml ───┼──┐  │                         │               │
│  │                         │  │  └─────────────────────────┘               │
│  └─────────────────────────┘  │                                             │
│                                │  ┌─────────────────────────┐               │
│                                └──►  git-statistics          │               │
│                                   │  (auto-created)          │               │
│                                   │                          │               │
│                                   │  reports/                │               │
│                                   │  docs/ (GitHub Pages)    │               │
│                                   │    index.html            │               │
│                                   │    assets/               │               │
│                                   │                          │               │
│                                   └──────────┬───────────────┘               │
│                                              │ GitHub Pages                  │
│                                              ▼                               │
│                               https://user.github.io/git-statistics          │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Repos

### `git-eternal-data` (data warehouse)
- **Orphan repo** — no source code, only data
- Flat JSON file tree: `data/{owner}/{repo}/{year}/{YYYY-MM}.json`
- `index.json`: aggregated lifetime stats per repo
- `harvest_log.json`: last 50 harvest run records
- `config.json`: `tracked_repos` list
- `harvest.lock`: mutex to prevent concurrent runs
- Written exclusively by the harvester workflow
- **Private repo recommended** (traffic data is sensitive)

### `git-statistics` (presentation layer)
- **Orphan repo** — no source code
- `reports/`: JSON reports generated from `git-eternal-data`
  - `summary.json`: portfolio-level totals
  - `top_repos.json`: ranked by clones/views
  - `trends.json`: week-over-week deltas
- `docs/`: GitHub Pages site (HTML/CSS/JS, single-file, no build step)
  - `index.html`: dashboard UI
  - Data loaded from `../reports/*.json` via relative paths
- **Public repo** (GitHub Pages requires it for free accounts)
- Updated weekly by the statistics workflow

---

## Workflows

### `00-setup.yml` — Initial Setup (one-time)
**Trigger**: manual dispatch only (`workflow_dispatch`)

**Steps**:
1. Use GitHub CLI (`gh`) with `GITHUB_TOKEN` to create `git-eternal-data` repo (private)
2. Push an initial orphan commit (README + empty index.json)
3. Create `git-statistics` repo (public)
4. Push initial orphan commit with README + placeholder `docs/index.html`
5. Enable GitHub Pages on `git-statistics` from `docs/` folder
6. Create `GIT_ETERNAL_DATA_TOKEN` secret in the main repo (using a fine-grained PAT scoped to both new repos — documented in README, user pastes it in)
7. **Delete itself** (`gh workflow delete 00-setup.yml`)

**Required secrets before first run**:
- `GITHUB_TOKEN` (built-in — needs `repo` + `workflow` scopes via classic PAT or `contents: write` fine-grained)

**Outputs**:
- Both repos exist and are initialized
- GitHub Pages is live
- Setup workflow is gone

---

### `01-harvester.yml` — Recurring Data Collection
**Trigger**: `schedule: cron '0 6 * * 0'` (every Sunday) + `workflow_dispatch`

**Steps**:
1. Checkout main repo
2. Run `packages/engine/harvester.py` (unchanged logic)
3. Commits to `git-eternal-data`

**Required secrets**:
- `HARVEST_TOKEN`: classic PAT with `repo` scope (user's own account — reads their own traffic)
- `GIT_ETERNAL_DATA_TOKEN`: fine-grained PAT with write access to `git-eternal-data`
- `GIT_ETERNAL_DATA_REPO`: `{owner}/git-eternal-data`

**Key**: The harvester token is the **user's own PAT** reading **their own repos** — no cross-account access needed.

---

### `02-statistics.yml` — Statistics Processing
**Trigger**: `workflow_run` on `01-harvester.yml` completion + `workflow_dispatch`

**Steps**:
1. Checkout `git-eternal-data` (shallow, read-only)
2. Run `packages/engine/statistics.py` — reads vault JSON, generates report JSON
3. Checkout `git-statistics`
4. Write `reports/*.json` and regenerate `docs/index.html` from template
5. Commit + push to `git-statistics`

**Required secrets**:
- `GIT_ETERNAL_DATA_TOKEN`: read access to `git-eternal-data`
- `GIT_STATISTICS_TOKEN`: write access to `git-statistics`
- `GIT_ETERNAL_DATA_REPO`: `{owner}/git-eternal-data`
- `GIT_STATISTICS_REPO`: `{owner}/git-statistics`

---

## Data Flow (New)

```
GitHub Traffic API
        │
        │ (HARVEST_TOKEN — user's own PAT)
        ▼
  01-harvester.yml
        │
        │ writes JSON
        ▼
  git-eternal-data ──────────────────────────────┐
                                                  │ reads
                                                  ▼
                                         02-statistics.yml
                                                  │
                                                  │ writes reports + HTML
                                                  ▼
                                         git-statistics/docs/
                                                  │
                                                  │ GitHub Pages
                                                  ▼
                                    user.github.io/git-statistics
```

---

## Key Tradeoffs

| Concern | Decision | Tradeoff |
|---|---|---|
| Privacy | `git-eternal-data` is private | GitHub Pages requires public repo for free tier; stats repo is public but contains only aggregated reports, not raw daily data |
| No external infra | Everything in GitHub Actions + Pages | Slower updates (weekly), no real-time data |
| Commit bloat | Statistics writes to a separate repo | Main GitEternal repo stays clean; `git-eternal-data` grows ~1 commit/week |
| Token scope | User provides their own PAT | Minimal: `repo` scope for traffic API + fine-grained write tokens for the two data repos |
| Setup friction | One manual workflow dispatch | ~5 min setup; no CLI, no external tools required |
| Orphan repos | `git-eternal-data` and `git-statistics` have no common history with main | Clean separation; neither pollutes the main repo's history |
| Pages build | Zero-build static HTML | Avoids Node/npm in statistics workflow; instant deploy |

---

## File/Workflow Structure

```
GitEternal/
├── .github/
│   └── workflows/
│       ├── 00-setup.yml          ← one-time setup (deletes itself)
│       ├── 01-harvester.yml      ← weekly data collection
│       └── 02-statistics.yml     ← weekly stats + pages update
├── packages/
│   └── engine/
│       ├── harvester.py          ← unchanged
│       ├── statistics.py         ← NEW: reads vault, generates reports + HTML
│       ├── api.py                ← unchanged
│       ├── merge.py              ← unchanged
│       ├── schema.py             ← unchanged
│       ├── lock.py               ← unchanged
│       └── requirements.txt      ← unchanged
└── templates/
    └── statistics.html           ← NEW: Jinja2 template for GitHub Pages dashboard
```

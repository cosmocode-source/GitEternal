# GitEternal

> **GitHub-native analytics using Git as the database.**
> Collect, store, and visualize your repository traffic — privately, automatically, forever.

[![Harvest](https://github.com/YOUR_USERNAME/GitEternal/actions/workflows/01-harvester.yml/badge.svg)](https://github.com/YOUR_USERNAME/GitEternal/actions/workflows/01-harvester.yml)
[![Statistics](https://github.com/YOUR_USERNAME/GitEternal/actions/workflows/02-statistics.yml/badge.svg)](https://github.com/YOUR_USERNAME/GitEternal/actions/workflows/02-statistics.yml)

---

## How it works

GitHub's traffic API only keeps **14 days** of data. GitEternal runs weekly, collects your traffic before it expires, and builds a permanent record — all inside GitHub.

```
Your repos ──► GitHub Traffic API ──► git-eternal-data (private vault)
                                              │
                                              ▼
                                      git-statistics ──► GitHub Pages Dashboard
```

Three repos, three responsibilities:

| Repo | Visibility | Purpose |
|------|-----------|---------|
| **GitEternal** (this repo) | Private | Harvester code + workflow definitions |
| **git-eternal-data** | **Private** | Raw traffic JSON — your data, only you can see it |
| **git-statistics** | Public | Aggregated dashboard published via GitHub Pages |

---

## Quick Start

### Step 1 — Fork or clone this repo

```bash
gh repo create YOUR_USERNAME/GitEternal --private --clone
# copy this repo's files in
```

### Step 2 — Create a SETUP_TOKEN

1. Go to **GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)**
2. Create a token with scopes: `repo`, `workflow`
3. Copy it

### Step 3 — Add the secret

Go to this repo's **Settings → Secrets and variables → Actions** and add:

| Secret name | Value |
|-------------|-------|
| `SETUP_TOKEN` | The classic PAT you just created |

### Step 4 — Run the setup workflow

Go to **Actions → "00 · Initial Setup" → Run workflow**.

This will:
- Create `git-eternal-data` (private) and `git-statistics` (public)
- Initialize both repos
- Enable GitHub Pages on `git-statistics`
- Delete itself

### Step 5 — Add the remaining secrets

After setup completes, the workflow output will tell you to add 3 more secrets:

| Secret name | Description |
|-------------|-------------|
| `HARVEST_TOKEN` | Classic PAT with `repo` scope — reads YOUR traffic data |
| `GIT_ETERNAL_DATA_TOKEN` | Fine-grained PAT — write access to `git-eternal-data` |
| `GIT_STATISTICS_TOKEN` | Fine-grained PAT — write access to `git-statistics` |

> **Creating fine-grained PATs**:
> Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token
> Set repository access to the specific repo, permission: **Contents → Read and write**

### Step 6 — Run the first harvest

Go to **Actions → "01 · Harvest Traffic Data" → Run workflow**.

The statistics workflow will trigger automatically after harvest completes.

### Step 7 — View your dashboard

`https://YOUR_USERNAME.github.io/git-statistics`

---

## Automation schedule

| Workflow | Schedule | Purpose |
|----------|----------|---------|
| `01-harvester` | Every Sunday 06:00 UTC | Collect traffic data |
| `02-statistics` | After each harvest | Rebuild dashboard |

You can also trigger either workflow manually from the Actions tab.

---

## Architecture

```
packages/
  engine/
    harvester.py   — async Python: discovers repos, fetches traffic, merges + commits to vault
    statistics.py  — reads vault, generates JSON reports + self-contained HTML dashboard
    api.py         — GitHub API wrappers (clones, views, referrers, rate limit)
    merge.py       — time-series merge logic (dedup by date, sort ascending)
    schema.py      — Pydantic models for MonthLedger, VaultIndex, HarvestRun, etc.
    lock.py        — distributed lock in vault (harvest.lock file)
    requirements.txt

.github/
  workflows/
    00-setup.yml      — one-time bootstrap (self-deletes after run)
    01-harvester.yml  — weekly data collection
    02-statistics.yml — weekly stats processing + Pages deploy
```

### Vault structure (`git-eternal-data`, branch `git-eternal-data`)

```
index.json          — lifetime totals per repo + available months
harvest_log.json    — last 50 harvest run records
config.json         — { "tracked_repos": ["owner/repo", ...] }
harvest.lock        — mutex (auto-cleared after 2h)
data/
  {owner}/
    {repo}/
      {year}/
        {YYYY-MM}.json   — MonthLedger: daily clones, views, referrers
```

### Statistics structure (`git-statistics`, branch `main`)

```
reports/
  summary.json      — portfolio totals
  top_repos.json    — repos ranked by lifetime clones
  trends.json       — week-over-week deltas
  chart_data.json   — daily aggregate for activity chart
docs/
  index.html        — self-contained dashboard (inline data, no build step)
```

---

## Privacy

- Raw traffic data lives in **`git-eternal-data`** which is **private** — only you can access it
- The **`git-statistics`** repo is public (required for free GitHub Pages), but only contains **aggregated summaries** — no raw daily breakdowns
- No external services, no telemetry, no databases outside GitHub

---

## Token requirements

| Token | Type | Required scopes / permissions |
|-------|------|-------------------------------|
| `HARVEST_TOKEN` | Classic PAT | `repo` scope — reads YOUR repos' traffic |
| `GIT_ETERNAL_DATA_TOKEN` | Fine-grained PAT | Contents: Read & write on `git-eternal-data` |
| `GIT_STATISTICS_TOKEN` | Fine-grained PAT | Contents: Read & write on `git-statistics` |

> **Why a classic PAT for HARVEST_TOKEN?**
> GitHub's traffic API (`/traffic/clones`, `/traffic/views`) requires the `repo` scope on a classic PAT, OR a fine-grained PAT with "Repository traffic" → Read permission on each repo you want to track. The classic PAT approach is simpler for tracking many repos across orgs you own.

---

## Troubleshooting

**Harvest gets 403 on some repos**
- Your PAT needs the `repo` scope
- For org repos, you need to be an **owner** of the org (not just a member)
- Fine-grained PATs need "Repository traffic: Read" permission explicitly

**GitHub Pages not loading**
- Pages can take up to 10 minutes to build on first deploy
- Check `git-statistics` repo → Settings → Pages to confirm it's configured to `docs/` on `main`

**Statistics workflow doesn't trigger**
- It's linked to `01-harvester` completion via `workflow_run`
- Trigger it manually: Actions → "02 · Generate Statistics" → Run workflow

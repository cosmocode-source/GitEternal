# Phase 1 — Code Understanding

## Architecture Overview

GitEternal_v2 is a **GitHub traffic analytics system** with three layers:

```
┌─────────────────────────────────────────────────────────────┐
│  GitEternal_v2 (main repo)                                      │
│   └── packages/engine/  ← Python harvester                  │
│   └── apps/web/         ← Next.js dashboard (Vercel-hosted) │
│   └── .github/workflows/harvest.yml ← scheduled runner      │
└─────────────────────────────────────────────────────────────┘
          │ writes to                    │ reads from
          ▼                             ▼
┌────────────────────┐       ┌──────────────────────────────┐
│  GitData  │       │  apps/web (Vercel)           │
│  (orphan branch)   │       │   /api/fetch-ledger          │
│  index.json        │◄──────│   → reads vault via GitHub   │
│  harvest_log.json  │       │      Contents API            │
│  config.json       │       │   Caches in Upstash Redis    │
│  harvest.lock      │       └──────────────────────────────┘
│  data/owner/repo/  │
│    YYYY/YYYY-MM.json│
└────────────────────┘
```

## Data Flow

1. **Harvest trigger**: GitHub Actions cron (`0 6 */5 * *` = every 5 days) or manual dispatch
2. **Token auth**: `HARVEST_TOKEN` (classic PAT with `repo` scope) reads GitHub traffic API; `VAULT_TOKEN` writes to `GitData`
3. **Repo discovery**: `harvester.py` calls `/user/repos`, filters by push/admin permissions, probes `/traffic/clones` to confirm access
4. **Collection**: `api.py` fetches clones, views, referrers for each accessible repo (last 14 days from GitHub API)
5. **Merge**: `merge.py` merges incoming data with existing `MonthLedger` (dedup by date, sort ascending)
6. **Storage**: JSON files written to `GitData` branch under `data/{owner}/{repo}/{year}/{YYYY-MM}.json`
7. **Index**: `index.json` updated with per-repo `RepoMeta` (lifetime totals, available months)
8. **Lock**: `harvest.lock` in vault prevents concurrent runs; stale after 2h

## Existing GitHub Actions

- **`harvest.yml`**: runs every 5 days, Python 3.12, reads `HARVEST_TOKEN` + `VAULT_TOKEN` + `VAULT_REPO` secrets, opens a failure issue if it errors

## Purpose of `harvest` and `GitData`

- **`harvest`** (`packages/engine/`): Python async engine that collects GitHub traffic data via the API, merges it into monthly JSON ledgers, and commits to a storage repo
- **`GitData`**: A separate GitHub repo (or orphan branch) that acts as a flat-file database — contains `index.json` (summary), `harvest_log.json` (run history), `config.json` (tracked repos), and `data/` tree (raw monthly ledgers)

## Key Observations

- The web app (Next.js + NextAuth) requires user login (GitHub OAuth) and reads vault data via GitHub Contents API with Upstash KV caching
- The system was originally designed for a **self-hosted model** where the user provides their own PAT and vault repo
- GitHub's traffic API only returns the **last 14 days** — the entire point of GitEternal_v2 is to harvest before data expires, building a longer history
- Schema is strictly validated via Pydantic (`schema.py`) on both write and read paths

# gitdata branch

**Orphan branch — do not merge into main.**

This branch is the raw traffic vault for GitEternal.
All files here are written automatically by the `01 · Harvest` workflow.
Do not edit manually.

## Structure
```
index.json          — lifetime stats index per repo
harvest_log.json    — last 50 harvest run records
config.json         — harvester runtime config
owner_stats.json    — GitHub profile + commit/PR/issue counts
data/
  {owner}/
    {repo}/
      {year}/
        {YYYY-MM}.json
```

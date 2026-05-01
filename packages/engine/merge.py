from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from .schema import MonthLedger, RepoMeta, VaultIndex


def compute_checksum(clones: list[dict], views: list[dict]) -> str:
    payload = json.dumps(
        {"clones": clones, "views": views}, sort_keys=True, separators=(",", ":")
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def detect_gaps(ledger_clones: list[dict], lookback_days: int = 14) -> list[str]:
    known = {entry["date"] for entry in ledger_clones if "date" in entry}
    today = date.today()
    expected = {
        (today - timedelta(days=offset)).isoformat() for offset in range(lookback_days)
    }
    return sorted(expected - known)


def backfill(gaps: list[str], incoming: list[dict]) -> tuple[list[dict], list[str]]:
    incoming_by_date = {entry.get("date"): entry for entry in incoming}
    recovered: list[dict] = []
    missing: list[str] = []
    for gap in gaps:
        if gap in incoming_by_date:
            recovered.append(incoming_by_date[gap])
        else:
            missing.append(gap)
    recovered.sort(key=lambda item: item["date"])
    return recovered, missing


def _merge_timeseries(existing: list[dict], incoming: list[dict]) -> list[dict]:
    by_date: dict[str, dict] = {entry["date"]: dict(entry) for entry in existing}
    for entry in incoming:
        by_date[entry["date"]] = dict(entry)
    return [by_date[d] for d in sorted(by_date)]


def merge_month(
    existing: MonthLedger | None,
    incoming_clones: list[dict],
    incoming_views: list[dict],
    incoming_referrers: list[dict],
    month: str,
    repo: str,
) -> MonthLedger:
    base_clones = [entry.model_dump(mode="json") for entry in existing.clones] if existing else []
    base_views = [entry.model_dump(mode="json") for entry in existing.views] if existing else []

    merged_clones = _merge_timeseries(base_clones, incoming_clones)
    merged_views = _merge_timeseries(base_views, incoming_views)
    checksum = compute_checksum(merged_clones, merged_views)

    candidate = {
        "month": month,
        "repo": repo,
        "clones": merged_clones,
        "views": merged_views,
        "referrers": incoming_referrers,
        "checksum": checksum,
    }

    try:
        return MonthLedger.model_validate(candidate)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc


def _load_all_ledgers_for_repo(vault_path: Path, owner: str, repo: str) -> list[MonthLedger]:
    """Load all stored monthly ledger files for a repo from the vault."""
    ledgers: list[MonthLedger] = []
    repo_dir = vault_path / "data" / owner / repo
    if not repo_dir.exists():
        return ledgers
    for year_dir in sorted(repo_dir.iterdir()):
        for f in sorted(year_dir.glob("*.json")):
            try:
                ledgers.append(MonthLedger.model_validate(json.loads(f.read_text())))
            except Exception:
                pass
    return ledgers


def update_index(
    index: VaultIndex,
    repo: str,
    month_ledger: MonthLedger,
    vault_path: Path | None = None,
    description: str = "",
    stars: int = 0,
    forks: int = 0,
    watchers: int = 0,
    open_issues: int = 0,
    language: str = "",
    topics: list | None = None,
) -> VaultIndex:
    existing = index.repos.get(repo)

    # Recompute lifetime totals by reading ALL stored ledger files for this repo.
    # This avoids double-counting: each daily entry is stored exactly once per
    # date in the ledger files (merge_month deduplicates by date), so summing
    # across all months gives the true lifetime total.
    if vault_path is not None:
        owner, repo_name = repo.split("/", 1)
        all_ledgers = _load_all_ledgers_for_repo(vault_path, owner, repo_name)
        # Replace the current month's ledger with the freshly merged one
        all_ledgers = [l for l in all_ledgers if l.month != month_ledger.month]
        all_ledgers.append(month_ledger)

        all_clone_entries: dict[str, int] = {}
        all_unique_entries: dict[str, int] = {}
        all_dates: list[str] = []
        for ledger in all_ledgers:
            for entry in ledger.clones:
                d = entry.date.isoformat()
                all_clone_entries[d] = entry.count
                all_unique_entries[d] = entry.uniques
                all_dates.append(d)

        lifetime_clones  = sum(all_clone_entries.values())
        lifetime_uniques = sum(all_unique_entries.values())
        total_clone_days = len(all_clone_entries)
        available_months = sorted({l.month for l in all_ledgers})
        agg_first = min(all_dates) if all_dates else ""
        agg_last  = max(all_dates) if all_dates else ""
    else:
        # Fallback (no vault path): use only the current month ledger
        clones = [entry.model_dump(mode="json") for entry in month_ledger.clones]
        clone_dates = sorted(item["date"] for item in clones)
        lifetime_clones  = sum(item["count"]   for item in clones)
        lifetime_uniques = sum(item["uniques"]  for item in clones)
        total_clone_days = len(clones)
        available_months = [month_ledger.month]
        agg_first = clone_dates[0]  if clone_dates else ""
        agg_last  = clone_dates[-1] if clone_dates else ""
        if existing:
            available_months = sorted(set(existing.available_months + [month_ledger.month]))
            if existing.first_date:
                agg_first = min(agg_first, existing.first_date) if agg_first else existing.first_date
            if existing.last_date:
                agg_last  = max(agg_last,  existing.last_date)  if agg_last  else existing.last_date

    updated_meta = RepoMeta(
        first_date=agg_first,
        last_date=agg_last,
        total_clone_days=total_clone_days,
        lifetime_clones=lifetime_clones,
        lifetime_uniques=lifetime_uniques,
        available_months=available_months,
        last_harvest=datetime.now(tz=UTC).isoformat(),
        description=description if description else (existing.description if existing else ""),
        stars=stars if stars else (existing.stars if existing else 0),
        forks=forks if forks else (existing.forks if existing else 0),
        watchers=watchers if watchers else (existing.watchers if existing else 0),
        open_issues=open_issues,
        language=language if language else (existing.language if existing else ""),
        topics=topics if topics is not None else (existing.topics if existing else []),
    )

    repos = dict(index.repos)
    repos[repo] = updated_meta
    return VaultIndex(version=2, repos=repos)

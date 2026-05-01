from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta

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


def update_index(index: VaultIndex, repo: str, month_ledger: MonthLedger, description: str = "") -> VaultIndex:
    clones = [entry.model_dump(mode="json") for entry in month_ledger.clones]
    clone_days = len(clones)
    clone_total = sum(item["count"] for item in clones)
    unique_total = sum(item["uniques"] for item in clones)

    month_dates = sorted(item["date"] for item in clones)
    first_date = month_dates[0] if month_dates else ""
    last_date = month_dates[-1] if month_dates else ""

    existing = index.repos.get(repo)
    if existing is None:
        available_months = [month_ledger.month]
        total_clone_days = clone_days
        lifetime_clones = clone_total
        lifetime_uniques = unique_total
        agg_first = first_date
        agg_last = last_date
    else:
        available_months = sorted(set(existing.available_months + [month_ledger.month]))
        month_is_new = month_ledger.month not in existing.available_months
        if month_is_new:
            # New month: accumulate on top of existing totals
            total_clone_days = existing.total_clone_days + clone_days
            lifetime_clones  = existing.lifetime_clones  + clone_total
            lifetime_uniques = existing.lifetime_uniques + unique_total
        else:
            # Existing month re-harvested: the merged ledger is authoritative.
            # We cannot subtract the old contribution from cumulative totals, so
            # we take max() to keep totals monotonically non-decreasing without
            # double-counting.
            total_clone_days = max(existing.total_clone_days, clone_days)
            lifetime_clones  = max(existing.lifetime_clones,  clone_total)
            lifetime_uniques = max(existing.lifetime_uniques, unique_total)
        candidates_first = [d for d in [existing.first_date, first_date] if d]
        candidates_last = [d for d in [existing.last_date, last_date] if d]
        agg_first = min(candidates_first) if candidates_first else ""
        agg_last = max(candidates_last) if candidates_last else ""

    updated_meta = RepoMeta(
        first_date=agg_first,
        last_date=agg_last,
        total_clone_days=total_clone_days,
        lifetime_clones=lifetime_clones,
        lifetime_uniques=lifetime_uniques,
        available_months=available_months,
        last_harvest=datetime.now(tz=UTC).isoformat(),
        description=description if description else (existing.description if existing else ""),
    )

    repos = dict(index.repos)
    repos[repo] = updated_meta
    return VaultIndex(version=2, repos=repos)

"""
packages/engine/harvester.py
─────────────────────────────
Reads GitHub traffic data and stores it in the git-eternal-data vault.

Environment variables
─────────────────────
  HARVEST_TOKEN           — classic PAT with 'repo' scope (YOUR GitHub account)
  VAULT_TOKEN             — write-access token for git-eternal-data repo
                            (falls back to HARVEST_TOKEN if not set)
                            In the new workflow this is GIT_ETERNAL_DATA_TOKEN,
                            but the env var is mapped as VAULT_TOKEN in the step.
  VAULT_REPO              — full name of the data repo  e.g. alice/git-eternal-data
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx

from .api import check_rate_limit, fetch_clones, fetch_referrers, fetch_views
from .lock import acquire_lock, release_lock
from .merge import merge_month, update_index
from .schema import HarvestLog, HarvestRun, MonthLedger, VaultIndex

logger = logging.getLogger(__name__)

VAULT_BRANCH = "git-eternal-data"
BOT_NAME     = "github-actions[bot]"
BOT_EMAIL    = "github-actions[bot]@users.noreply.github.com"

GITHUB_API   = "https://api.github.com"


# ── git helpers ───────────────────────────────────────────────────────────────

def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git error: {' '.join(cmd)}\n{r.stderr.strip()}")
    return r


def _clone_vault(vault_repo: str, token: str, dest: Path) -> None:
    url = f"https://x-access-token:{token}@github.com/{vault_repo}.git"
    _run(["git", "clone", "--branch", VAULT_BRANCH, "--depth=1", url, str(dest)])
    _run(["git", "config", "user.name",  BOT_NAME],  cwd=dest)
    _run(["git", "config", "user.email", BOT_EMAIL], cwd=dest)


def _commit_and_push(vault_path: Path, token: str, vault_repo: str, message: str) -> None:
    if not _run(["git", "status", "--porcelain"], cwd=vault_path).stdout.strip():
        logger.info("Nothing to commit")
        return
    _run(["git", "add", "-A"],              cwd=vault_path)
    _run(["git", "commit", "-m", message],  cwd=vault_path)
    url = f"https://x-access-token:{token}@github.com/{vault_repo}.git"
    _run(["git", "push", url, f"HEAD:{VAULT_BRANCH}"], cwd=vault_path)
    logger.info("Pushed: %s", message)


# ── file helpers ──────────────────────────────────────────────────────────────

def _repo_file(owner: str, repo: str, month: str) -> str:
    return f"data/{owner}/{repo}/{month[:4]}/{month}.json"


def _read_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text()) if path.exists() else default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def _append_log(vault_path: Path, run: HarvestRun) -> None:
    log_path = vault_path / "harvest_log.json"
    existing = _read_json(log_path, {"runs": []})
    log  = HarvestLog.model_validate(existing)
    runs = (log.runs + [run])[-50:]
    _write_json(log_path, HarvestLog(runs=runs).model_dump(mode="json"))


def _gh_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "User-Agent": "GitEternal/1.0",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


# ── token diagnostics ─────────────────────────────────────────────────────────

async def _log_token_identity(token: str, client: httpx.AsyncClient) -> str:
    """Log who the token authenticates as and return their login."""
    r = await client.get(f"{GITHUB_API}/user", headers=_gh_headers(token))
    if r.status_code != 200:
        logger.warning("Could not resolve token identity: HTTP %s", r.status_code)
        return ""
    data = r.json()
    login = data.get("login", "unknown")
    utype = data.get("type", "unknown")
    logger.info("HARVEST_TOKEN authenticates as: %s (type=%s)", login, utype)

    scopes = r.headers.get("x-oauth-scopes", "")
    if scopes:
        logger.info("Token OAuth scopes: %s", scopes)
    else:
        logger.info("No x-oauth-scopes header — token may be a fine-grained PAT or GitHub App")

    return login


# ── repo discovery ────────────────────────────────────────────────────────────

async def _get_all_repos(token: str, client: httpx.AsyncClient) -> list[dict]:
    """Page through /user/repos and return raw repo objects."""
    repos: list[dict] = []
    page = 1
    while True:
        r = await client.get(
            f"{GITHUB_API}/user/repos",
            headers=_gh_headers(token),
            params={
                "per_page": 100,
                "page": page,
                "affiliation": "owner,collaborator,organization_member",
            },
        )
        if r.status_code != 200:
            logger.warning("Could not fetch repo list (page %d): HTTP %s", page, r.status_code)
            break
        data = r.json()
        if not data:
            break
        repos.extend(data)
        page += 1
    return repos


async def _can_access_traffic(
    owner: str, repo: str, token: str, client: httpx.AsyncClient
) -> bool:
    r = await client.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/traffic/clones",
        headers=_gh_headers(token),
        params={"per": "day"},
    )
    return r.status_code == 200


async def _discover_repos(token: str, client: httpx.AsyncClient) -> tuple[list[str], list[str]]:
    all_repos = await _get_all_repos(token, client)
    logger.info("Found %d repos visible to token", len(all_repos))

    candidates = [
        r["full_name"] for r in all_repos
        if r.get("permissions", {}).get("admin") or r.get("permissions", {}).get("push")
    ]
    logger.info(
        "%d repos have push/admin — probing traffic API …",
        len(candidates),
    )

    accessible: list[str] = []
    blocked: list[str] = []
    batch_size = 8

    for i in range(0, len(candidates), batch_size):
        batch = candidates[i : i + batch_size]
        results = await asyncio.gather(
            *[
                _can_access_traffic(full.split("/")[0], full.split("/")[1], token, client)
                for full in batch
            ]
        )
        for full_name, ok in zip(batch, results):
            if ok:
                accessible.append(full_name)
            else:
                blocked.append(full_name)

    return sorted(accessible), sorted(blocked)


# ── main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    harvest_token = os.environ.get("HARVEST_TOKEN")
    vault_token   = os.environ.get("VAULT_TOKEN") or harvest_token
    vault_repo    = os.environ.get("VAULT_REPO")

    if not harvest_token:
        raise RuntimeError("HARVEST_TOKEN is required")
    if not vault_repo:
        raise RuntimeError("VAULT_REPO is required")

    with tempfile.TemporaryDirectory() as tmp:
        vault_path = Path(tmp) / "vault"
        _clone_vault(vault_repo, vault_token, vault_path)

        if not acquire_lock(vault_path):
            logger.warning("Harvest skipped — lock held by another run")
            return

        _commit_and_push(vault_path, vault_token, vault_repo,
                         "chore: acquire harvest lock [skip ci]")

        config_path = vault_path / "config.json"
        index_path  = vault_path / "index.json"

        config = _read_json(config_path, {})
        index  = VaultIndex.model_validate(_read_json(index_path, {"version": 2, "repos": {}}))

        harvested:   list[str] = []
        skipped_403: list[str] = []
        repo_errors: list[str] = []

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:

                await _log_token_identity(harvest_token, client)

                rate = await check_rate_limit(harvest_token, client=client)
                logger.info("Rate limit remaining: %d", rate["remaining"])
                if rate["remaining"] < 50:
                    release_lock(vault_path)
                    raise RuntimeError(f"Rate limit too low: {rate['remaining']} remaining")

                pinned: list[str] = config.get("tracked_repos", [])
                logger.info("Discovering repos with confirmed traffic API access …")

                accessible, blocked = await _discover_repos(harvest_token, client)

                if blocked:
                    logger.warning(
                        "=== %d repo(s) BLOCKED by traffic API (403) ===", len(blocked)
                    )
                    for b in blocked:
                        logger.warning(
                            "  BLOCKED: %s  — PAT needs 'repo' scope AND org owner role.",
                            b,
                        )

                tracked = sorted(set(accessible) | set(pinned))

                if sorted(pinned) != tracked:
                    logger.info(
                        "Updating config.json tracked_repos: %d → %d repos",
                        len(pinned), len(tracked),
                    )
                    config["tracked_repos"] = tracked
                    _write_json(config_path, config)

                logger.info("Will harvest %d repo(s): %s", len(tracked), tracked)

                today = date.today()
                month = today.strftime("%Y-%m")

                for full_repo in tracked:
                    try:
                        owner, repo = full_repo.split("/", 1)
                        logger.info("Processing %s …", full_repo)

                        try:
                            clones = await fetch_clones(owner, repo, harvest_token, client=client)
                        except httpx.HTTPStatusError as e:
                            if e.response.status_code == 403:
                                logger.warning("SKIPPING %s — 403 on traffic/clones.", full_repo)
                                skipped_403.append(full_repo)
                                continue
                            raise

                        views = await fetch_views(owner, repo, harvest_token, client=client)

                        try:
                            referrers = await fetch_referrers(owner, repo, harvest_token, client=client)
                        except Exception as exc:
                            logger.warning("Referrers failed for %s: %s", full_repo, exc)
                            referrers = []

                        month_path     = vault_path / _repo_file(owner, repo, month)
                        existing_month = (
                            MonthLedger.model_validate(_read_json(month_path, None))
                            if month_path.exists() else None
                        )

                        merged = merge_month(existing_month, clones, views, referrers, month, full_repo)

                        tmp_path = month_path.with_suffix(".json.tmp")
                        _write_json(tmp_path, merged.model_dump(mode="json"))
                        MonthLedger.model_validate(_read_json(tmp_path, {}))
                        tmp_path.replace(month_path)

                        index = update_index(index, full_repo, merged)
                        harvested.append(full_repo)
                        logger.info("Done: %s", full_repo)

                    except Exception as exc:
                        logger.exception("Failed: %s", full_repo)
                        repo_errors.append(f"{full_repo}: {exc}")

            _write_json(index_path, index.model_dump(mode="json"))

            status = "success"
            if repo_errors and harvested:   status = "partial_failure"
            elif repo_errors:               status = "failed"

            error_parts: list[str] = []
            if repo_errors:
                error_parts.extend(repo_errors)
            if skipped_403:
                error_parts.append(
                    f"skipped {len(skipped_403)} repo(s) — traffic API 403: {skipped_403}"
                )

            run = HarvestRun(
                timestamp=datetime.now(tz=UTC).isoformat(),
                status=status,
                repos_harvested=harvested,
                gaps_detected=[],
                gaps_recovered=[],
                gaps_permanent=[],
                error="; ".join(error_parts) if error_parts else None,
            )
            _append_log(vault_path, run)
            release_lock(vault_path)
            _commit_and_push(vault_path, vault_token, vault_repo,
                             f"data: harvest {date.today().isoformat()} [skip ci]")

        except Exception as exc:
            release_lock(vault_path)
            _append_log(vault_path, HarvestRun(
                timestamp=datetime.now(tz=UTC).isoformat(),
                status="failed", repos_harvested=harvested,
                gaps_detected=[], gaps_recovered=[], gaps_permanent=[],
                error=str(exc),
            ))
            try:
                _commit_and_push(vault_path, vault_token, vault_repo,
                                 "data: harvest failed — log updated [skip ci]")
            finally:
                raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())

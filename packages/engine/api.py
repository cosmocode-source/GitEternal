from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
MAX_RETRIES = 3


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "User-Agent": "RepoEternal-Harvester/1.0",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _to_iso_date(ts: str) -> str:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).date().isoformat()


async def _get_json(
    client: httpx.AsyncClient,
    path: str,
    token: str,
    *,
    params: dict[str, Any] | None = None,
) -> Any:
    url = f"{GITHUB_API_BASE}{path}"
    for attempt in range(MAX_RETRIES + 1):
        response = await client.get(url, params=params, headers=_headers(token))
        if 200 <= response.status_code < 300:
            return response.json()

        retryable = response.status_code == 429 or 500 <= response.status_code <= 599
        if retryable and attempt < MAX_RETRIES:
            await asyncio.sleep(2**attempt)
            continue

        response.raise_for_status()

    raise RuntimeError("unreachable")


async def fetch_clones(
    owner: str,
    repo: str,
    token: str,
    *,
    client: httpx.AsyncClient,
) -> list[dict[str, Any]]:
    data = await _get_json(
        client,
        f"/repos/{owner}/{repo}/traffic/clones",
        token,
        params={"per": "day"},
    )
    return [
        {
            "date": _to_iso_date(item["timestamp"]),
            "count": item["count"],
            "uniques": item["uniques"],
        }
        for item in data.get("clones", [])
    ]


async def fetch_views(
    owner: str,
    repo: str,
    token: str,
    *,
    client: httpx.AsyncClient,
) -> list[dict[str, Any]]:
    data = await _get_json(
        client,
        f"/repos/{owner}/{repo}/traffic/views",
        token,
        params={"per": "day"},
    )
    return [
        {
            "date": _to_iso_date(item["timestamp"]),
            "count": item["count"],
            "uniques": item["uniques"],
        }
        for item in data.get("views", [])
    ]


async def fetch_referrers(
    owner: str,
    repo: str,
    token: str,
    *,
    client: httpx.AsyncClient,
) -> list[dict[str, Any]]:
    data = await _get_json(client, f"/repos/{owner}/{repo}/traffic/referrers", token)
    captured_on = date.today().isoformat()
    return [
        {
            "captured_on": captured_on,
            "source": item["referrer"],
            "count": item["count"],
            "uniques": item["uniques"],
        }
        for item in data
    ]


async def check_rate_limit(token: str, *, client: httpx.AsyncClient) -> dict[str, int]:
    data = await _get_json(client, "/rate_limit", token)
    core = data.get("resources", {}).get("core", {})
    remaining = int(core.get("remaining", 0))
    reset = int(core.get("reset", 0))
    if remaining < 100:
        reset_at = datetime.fromtimestamp(reset, tz=UTC).isoformat() if reset else "unknown"
        logger.warning("GitHub rate limit low: remaining=%s reset=%s", remaining, reset_at)
    return {"remaining": remaining, "reset": reset}


async def fetch_repo_info(
    owner: str,
    repo: str,
    token: str,
    *,
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    """Fetch repo metadata: stars, forks, watchers, language, topics, open issues."""
    data = await _get_json(client, f"/repos/{owner}/{repo}", token)
    return {
        "stars":       data.get("stargazers_count", 0),
        "forks":       data.get("forks_count", 0),
        "watchers":    data.get("subscribers_count", 0),
        "open_issues": data.get("open_issues_count", 0),
        "language":    data.get("language") or "",
        "topics":      data.get("topics", []),
        "description": data.get("description") or "",
    }

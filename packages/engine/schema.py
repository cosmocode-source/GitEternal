from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator


class TrafficEntry(BaseModel):
    date: date
    count: int
    uniques: int

    @field_validator("count", "uniques")
    @classmethod
    def non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("must be non-negative")
        return v


class Referrer(BaseModel):
    captured_on: date
    source: str
    count: int
    uniques: int

    @field_validator("count", "uniques")
    @classmethod
    def non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("must be non-negative")
        return v


class MonthLedger(BaseModel):
    month: str
    repo: str
    clones: list[TrafficEntry]
    views: list[TrafficEntry]
    referrers: list[Referrer]
    checksum: str

    @model_validator(mode="after")
    def enforce_sorted_no_dupes(self) -> "MonthLedger":
        for field_name in ("clones", "views"):
            entries = getattr(self, field_name)
            dates = [entry.date for entry in entries]
            if dates != sorted(dates):
                raise ValueError(f"{field_name} must be sorted ascending by date")
            if len(dates) != len(set(dates)):
                raise ValueError(f"{field_name} contains duplicate dates")
        return self


class RepoMeta(BaseModel):
    first_date: str
    last_date: str
    total_clone_days: int
    lifetime_clones: int
    lifetime_uniques: int
    available_months: list[str]
    last_harvest: str
    description: str = ""


class VaultIndex(BaseModel):
    version: int
    repos: dict[str, RepoMeta]

    @field_validator("version")
    @classmethod
    def version_must_be_two(cls, v: int) -> int:
        if v != 2:
            raise ValueError("version must be 2")
        return v


class HarvestRun(BaseModel):
    timestamp: str
    status: Literal["success", "partial_failure", "failed"]
    repos_harvested: list[str]
    gaps_detected: list[str]
    gaps_recovered: list[str]
    gaps_permanent: list[str]
    error: str | None = None


class HarvestLog(BaseModel):
    runs: list[HarvestRun]

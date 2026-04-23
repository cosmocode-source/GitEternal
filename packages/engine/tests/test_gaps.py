from datetime import date

from packages.engine import merge


class _FakeDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 4, 20)


def test_detect_gaps_returns_correct_missing_dates(monkeypatch):
    monkeypatch.setattr(merge, "date", _FakeDate)
    ledger_clones = [
        {"date": "2026-04-20", "count": 1, "uniques": 1},
        {"date": "2026-04-18", "count": 1, "uniques": 1},
    ]
    gaps = merge.detect_gaps(ledger_clones, lookback_days=3)
    assert gaps == ["2026-04-19"]


def test_detect_gaps_returns_empty_when_no_gaps(monkeypatch):
    monkeypatch.setattr(merge, "date", _FakeDate)
    ledger_clones = [
        {"date": "2026-04-20", "count": 1, "uniques": 1},
        {"date": "2026-04-19", "count": 1, "uniques": 1},
        {"date": "2026-04-18", "count": 1, "uniques": 1},
    ]
    gaps = merge.detect_gaps(ledger_clones, lookback_days=3)
    assert gaps == []


def test_backfill_recovers_available_dates():
    recovered, missing = merge.backfill(
        ["2026-04-19", "2026-04-18"],
        [
            {"date": "2026-04-19", "count": 3, "uniques": 2},
            {"date": "2026-04-20", "count": 1, "uniques": 1},
        ],
    )
    assert recovered == [{"date": "2026-04-19", "count": 3, "uniques": 2}]
    assert missing == ["2026-04-18"]


def test_backfill_identifies_still_missing_dates():
    recovered, missing = merge.backfill(
        ["2026-04-19", "2026-04-18"],
        [{"date": "2026-04-20", "count": 1, "uniques": 1}],
    )
    assert recovered == []
    assert missing == ["2026-04-19", "2026-04-18"]

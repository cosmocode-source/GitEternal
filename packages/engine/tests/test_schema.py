import pytest

from packages.engine.schema import MonthLedger, TrafficEntry


def _base_month() -> dict:
    return {
        "month": "2026-04",
        "repo": "acme/demo",
        "clones": [
            {"date": "2026-04-10", "count": 1, "uniques": 1},
            {"date": "2026-04-11", "count": 2, "uniques": 1},
        ],
        "views": [
            {"date": "2026-04-10", "count": 1, "uniques": 1},
            {"date": "2026-04-11", "count": 2, "uniques": 2},
        ],
        "referrers": [
            {
                "captured_on": "2026-04-11",
                "source": "google.com",
                "count": 1,
                "uniques": 1,
            }
        ],
        "checksum": "sha256:abc",
    }


def test_month_ledger_rejects_unsorted_clones():
    data = _base_month()
    data["clones"] = [
        {"date": "2026-04-11", "count": 2, "uniques": 1},
        {"date": "2026-04-10", "count": 1, "uniques": 1},
    ]
    with pytest.raises(ValueError):
        MonthLedger.model_validate(data)


def test_month_ledger_rejects_duplicate_dates():
    data = _base_month()
    data["clones"] = [
        {"date": "2026-04-10", "count": 1, "uniques": 1},
        {"date": "2026-04-10", "count": 2, "uniques": 1},
    ]
    with pytest.raises(ValueError):
        MonthLedger.model_validate(data)


def test_month_ledger_rejects_negative_counts():
    data = _base_month()
    data["views"] = [
        {"date": "2026-04-10", "count": -1, "uniques": 1},
    ]
    with pytest.raises(ValueError):
        MonthLedger.model_validate(data)


def test_traffic_entry_rejects_negative_uniques():
    with pytest.raises(ValueError):
        TrafficEntry.model_validate({"date": "2026-04-10", "count": 1, "uniques": -1})

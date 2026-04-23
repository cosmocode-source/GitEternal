from packages.engine.merge import compute_checksum, merge_month
from packages.engine.schema import MonthLedger


def test_merge_month_empty_existing_creates_valid_month_ledger():
    out = merge_month(
        None,
        incoming_clones=[{"date": "2026-04-10", "count": 2, "uniques": 1}],
        incoming_views=[{"date": "2026-04-10", "count": 5, "uniques": 3}],
        incoming_referrers=[
            {
                "captured_on": "2026-04-10",
                "source": "google.com",
                "count": 4,
                "uniques": 2,
            }
        ],
        month="2026-04",
        repo="acme/demo",
    )
    assert isinstance(out, MonthLedger)
    assert out.month == "2026-04"
    assert out.repo == "acme/demo"


def test_merge_month_overlap_dedupes_and_incoming_wins():
    existing = merge_month(
        None,
        incoming_clones=[{"date": "2026-04-10", "count": 1, "uniques": 1}],
        incoming_views=[{"date": "2026-04-10", "count": 2, "uniques": 1}],
        incoming_referrers=[],
        month="2026-04",
        repo="acme/demo",
    )

    out = merge_month(
        existing,
        incoming_clones=[
            {"date": "2026-04-10", "count": 9, "uniques": 8},
            {"date": "2026-04-11", "count": 3, "uniques": 2},
        ],
        incoming_views=[
            {"date": "2026-04-10", "count": 10, "uniques": 9},
            {"date": "2026-04-11", "count": 4, "uniques": 3},
        ],
        incoming_referrers=[],
        month="2026-04",
        repo="acme/demo",
    )

    assert [x.date.isoformat() for x in out.clones] == ["2026-04-10", "2026-04-11"]
    assert out.clones[0].count == 9
    assert out.clones[0].uniques == 8


def test_merge_month_output_dates_sorted():
    out = merge_month(
        None,
        incoming_clones=[
            {"date": "2026-04-11", "count": 3, "uniques": 2},
            {"date": "2026-04-10", "count": 2, "uniques": 1},
        ],
        incoming_views=[
            {"date": "2026-04-11", "count": 4, "uniques": 3},
            {"date": "2026-04-10", "count": 5, "uniques": 4},
        ],
        incoming_referrers=[],
        month="2026-04",
        repo="acme/demo",
    )
    assert [x.date.isoformat() for x in out.clones] == ["2026-04-10", "2026-04-11"]
    assert [x.date.isoformat() for x in out.views] == ["2026-04-10", "2026-04-11"]


def test_merge_month_checksum_matches_recomputed():
    out = merge_month(
        None,
        incoming_clones=[{"date": "2026-04-10", "count": 2, "uniques": 1}],
        incoming_views=[{"date": "2026-04-10", "count": 5, "uniques": 3}],
        incoming_referrers=[],
        month="2026-04",
        repo="acme/demo",
    )
    expected = compute_checksum(
        [x.model_dump(mode="json") for x in out.clones],
        [x.model_dump(mode="json") for x in out.views],
    )
    assert out.checksum == expected


def test_merge_month_invalid_data_raises_value_error():
    try:
        merge_month(
            None,
            incoming_clones=[{"date": "2026-04-10", "count": -1, "uniques": 1}],
            incoming_views=[{"date": "2026-04-10", "count": 1, "uniques": 1}],
            incoming_referrers=[],
            month="2026-04",
            repo="acme/demo",
        )
        raise AssertionError("Expected ValueError")
    except ValueError:
        pass


def test_merge_month_idempotent_for_same_input():
    first = merge_month(
        None,
        incoming_clones=[{"date": "2026-04-10", "count": 2, "uniques": 1}],
        incoming_views=[{"date": "2026-04-10", "count": 5, "uniques": 3}],
        incoming_referrers=[],
        month="2026-04",
        repo="acme/demo",
    )
    second = merge_month(
        first,
        incoming_clones=[{"date": "2026-04-10", "count": 2, "uniques": 1}],
        incoming_views=[{"date": "2026-04-10", "count": 5, "uniques": 3}],
        incoming_referrers=[],
        month="2026-04",
        repo="acme/demo",
    )
    assert first.model_dump(mode="json") == second.model_dump(mode="json")

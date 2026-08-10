"""Tests for the roster maths: capacity, open spots, flattening."""

import datetime as dt

import pytest

from pinkbee_mcp import roster


def week(*timeblocks, code="SO", shift_id=3, groups=(2,)):
    """One shift with the given day entries, shaped like the Pinkbee API."""
    return [
        {
            "id": shift_id,
            "code": code,
            "description": "Shop morning",
            "start_time": "11:00:00",
            "end_time": "14:00:00",
            "employee_group_ids": list(groups),
            "timeblocks": list(timeblocks),
        }
    ]


def block(date="2026-08-12", capacity=2, registrations=(), block_id=1):
    return {"id": block_id, "date": date, "capacity": capacity, "registrations": list(registrations)}


def test_monday_of_snaps_back_to_monday():
    assert roster.monday_of(dt.date(2026, 8, 13)) == dt.date(2026, 8, 10)


def test_monday_of_keeps_a_monday_as_is():
    assert roster.monday_of(dt.date(2026, 8, 10)) == dt.date(2026, 8, 10)


def test_iso_week_label():
    assert roster.iso_week(dt.date(2026, 8, 13)) == "2026-W33"


def test_a_normal_registration_takes_a_spot():
    assert roster.count_taken_spots(block(registrations=[{"id": 1}])) == 1


def test_an_absent_registration_frees_the_spot():
    assert roster.count_taken_spots(block(registrations=[{"id": 1, "is_absent": True}])) == 0


def test_the_indicator_warning_does_not_free_the_spot():
    entry = {"id": 1, "indicators": {"is_absent": True}}
    assert roster.count_taken_spots(block(registrations=[entry])) == 1


def test_open_spots_is_capacity_minus_taken():
    rows = roster.flatten_week(week(block(capacity=2, registrations=[{"id": 1}])))
    assert rows[0]["capacity"] == 2
    assert rows[0]["taken"] == 1
    assert rows[0]["open_spots"] == 1


def test_flatten_week_makes_one_row_per_day():
    rows = roster.flatten_week(
        week(block(date="2026-08-10", block_id=1), block(date="2026-08-11", block_id=2))
    )
    assert [row["date"] for row in rows] == ["2026-08-10", "2026-08-11"]
    assert [row["weekday"] for row in rows] == ["Mon", "Tue"]


def test_flatten_week_copies_the_shift_details_onto_every_row():
    row = roster.flatten_week(week(block()))[0]
    assert row["shift_id"] == 3
    assert row["code"] == "SO"
    assert row["description"] == "Shop morning"
    assert row["group_ids"] == [2]
    assert row["start_time"] == "11:00"
    assert row["end_time"] == "14:00"


def test_flatten_week_uppercases_the_code():
    assert roster.flatten_week(week(block(), code="so"))[0]["code"] == "SO"


def test_flatten_week_skips_days_without_a_date():
    rows = roster.flatten_week(week(block(date=None), block(date="2026-08-11", block_id=2)))
    assert [row["date"] for row in rows] == ["2026-08-11"]


def test_flatten_week_handles_a_shift_without_timeblocks():
    shift = {"id": 9, "code": "OP", "date": "2026-08-12", "capacity": 1, "registrations": []}
    rows = roster.flatten_week([shift])
    assert rows[0]["date"] == "2026-08-12"
    assert rows[0]["open_spots"] == 1


def test_flatten_week_sorts_by_date_then_code():
    payload = week(block(date="2026-08-11", block_id=2), code="SM") + week(
        block(date="2026-08-10", block_id=1), code="OP"
    )
    rows = roster.flatten_week(payload)
    assert [row["date"] for row in rows] == ["2026-08-10", "2026-08-11"]


def test_flatten_week_rejects_something_that_is_not_a_list():
    with pytest.raises(ValueError, match="must be a list"):
        roster.flatten_week({"code": "SO"})


def test_only_open_drops_full_and_zero_capacity_shifts():
    payload = week(
        block(date="2026-08-10", capacity=0, block_id=1),
        block(date="2026-08-11", capacity=1, registrations=[{"id": 1}], block_id=2),
        block(date="2026-08-12", capacity=1, block_id=3),
    )
    rows = roster.only_open(roster.flatten_week(payload))
    assert [row["date"] for row in rows] == ["2026-08-12"]


def test_short_time_trims_seconds_and_handles_missing_values():
    assert roster.short_time("14:00:00") == "14:00"
    assert roster.short_time(None) == ""

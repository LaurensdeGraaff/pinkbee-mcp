"""Tests for the built-in mock data source."""

import datetime as dt

import pytest

from pinkbee_mcp import roster
from pinkbee_mcp.mock import EMPLOYEES, GROUPS, SHIFTS, MockPinkbee, stable_number


@pytest.fixture
def mock():
    return MockPinkbee()


def test_stable_number_is_the_same_every_time():
    assert stable_number("shift", 3, "2026-08-10") == stable_number("shift", 3, "2026-08-10")


def test_stable_number_differs_per_input():
    assert stable_number("shift", 3, "2026-08-10") != stable_number("shift", 3, "2026-08-11")


async def test_week_schedule_returns_seven_days_per_shift(mock):
    week = await mock.week_schedule("2026-08-10")
    assert len(week) == len(SHIFTS)
    for shift in week:
        assert len(shift["timeblocks"]) == 7


async def test_week_schedule_starts_on_the_monday_you_asked_for(mock):
    week = await mock.week_schedule("2026-08-10")
    dates = [block["date"] for block in week[0]["timeblocks"]]
    assert dates[0] == "2026-08-10"
    assert dates[-1] == "2026-08-16"


async def test_week_schedule_is_deterministic(mock):
    first = await mock.week_schedule("2026-08-10")
    second = await mock.week_schedule("2026-08-10")
    assert first == second


async def test_week_schedule_gives_zero_capacity_outside_the_shift_weekdays(mock):
    week = await mock.week_schedule("2026-08-10")
    tower = next(shift for shift in week if shift["code"] == "TG")
    by_date = {block["date"]: block for block in tower["timeblocks"]}
    assert by_date["2026-08-10"]["capacity"] == 0  # Monday: no tower guides
    assert by_date["2026-08-15"]["capacity"] > 0  # Saturday: yes


async def test_week_schedule_can_be_flattened_by_the_roster_module(mock):
    rows = roster.flatten_week(await mock.week_schedule("2026-08-10"))
    assert rows
    assert all(row["capacity"] >= row["taken"] >= 0 for row in rows)


async def test_the_mock_contains_both_open_and_full_shifts(mock):
    """Otherwise the open-shift tool would have nothing meaningful to show."""
    rows = []
    for offset in range(0, 8):
        monday = (dt.date(2026, 8, 10) + dt.timedelta(days=7 * offset)).isoformat()
        rows += roster.flatten_week(await mock.week_schedule(monday))
    with_capacity = [row for row in rows if row["capacity"] > 0]
    assert any(row["open_spots"] > 0 for row in with_capacity)
    assert any(row["open_spots"] == 0 for row in with_capacity)


async def test_registrations_never_exceed_capacity(mock):
    for offset in range(0, 6):
        monday = (dt.date(2026, 8, 10) + dt.timedelta(days=7 * offset)).isoformat()
        for row in roster.flatten_week(await mock.week_schedule(monday)):
            assert row["taken"] <= row["capacity"]


async def test_groups_lists_every_group_with_its_members(mock):
    groups = await mock.groups()
    assert [group["id"] for group in groups] == [group["id"] for group in GROUPS]
    shop = next(group for group in groups if group["name"] == "Shop")
    assert shop["employees"]


async def test_shifts_expose_the_group_link(mock):
    week = await mock.week_schedule("2026-08-10")
    shop_morning = next(shift for shift in week if shift["code"] == "SO")
    assert shop_morning["employee_group_ids"] == [2, 15]


async def test_contacts_filters_on_group(mock):
    rows = await mock.contacts([1], ["now", "future"])
    names = {row["name"] for row in rows}
    assert "Femke Visser" in names  # in the Tower guides group
    assert "Anke Bakker" not in names  # shop only


async def test_contacts_filters_on_employment_status(mock):
    now_only = await mock.contacts([2], ["now"])
    including_past = await mock.contacts([2], ["now", "past"])
    assert len(including_past) > len(now_only)


async def test_contacts_use_example_org_addresses(mock):
    """Mock addresses must be undeliverable, so a mistake cannot reach anyone."""
    rows = await mock.contacts([group["id"] for group in GROUPS], ["now", "future", "past"])
    assert rows
    assert all(row["email"].endswith("@example.org") for row in rows)


async def test_registrations_stay_inside_the_date_range(mock):
    rows = await mock.registrations([], "2026-08-10", "2026-08-16")
    assert rows
    assert all("2026-08-10" <= row["date"] <= "2026-08-16" for row in rows)


async def test_registrations_can_be_filtered_by_shift(mock):
    rows = await mock.registrations([3], "2026-08-01", "2026-09-30")
    assert rows
    assert {row["shiftcode"] for row in rows} == {"SO"}


async def test_registrations_agree_with_the_week_schedule(mock):
    """The report and the roster must tell the same story."""
    week = await mock.week_schedule("2026-08-10")
    from_week = sum(
        len(block["registrations"]) for shift in week for block in shift["timeblocks"]
    )
    from_report = len(await mock.registrations([], "2026-08-10", "2026-08-16"))
    assert from_report == from_week


async def test_every_registration_points_at_a_known_volunteer(mock):
    known = {person["id"] for person in EMPLOYEES}
    rows = await mock.registrations([], "2026-08-10", "2026-09-30")
    assert all(row["employeeId"] in known for row in rows)


async def test_describe_says_it_is_mock_data(mock):
    assert "mock" in mock.describe().lower()

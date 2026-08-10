"""Tests for the six MCP tools, running against the mock data source."""

import datetime as dt
import json

import pytest

from pinkbee_mcp import server
from pinkbee_mcp.config import Config
from pinkbee_mcp.mock import MockPinkbee

THIS_MONDAY = dt.date.today() - dt.timedelta(days=dt.date.today().weekday())


@pytest.fixture(autouse=True)
def use_mock_data():
    """Every test starts with mock data and personal data switched off."""
    server.setup(Config(), MockPinkbee())


def allow_personal_data():
    server.setup(Config(allow_personal_data=True), MockPinkbee())


# --- 1. connection check ---------------------------------------------------


async def test_check_connection_reports_the_mock_source():
    answer = await server.pinkbee_check_connection()
    assert answer.startswith("OK:")
    assert "mock" in answer
    assert "Personal data: off" in answer


async def test_check_connection_reports_personal_data_on():
    allow_personal_data()
    assert "Personal data: on" in await server.pinkbee_check_connection()


async def test_check_connection_reports_a_broken_source():
    class Broken:
        def describe(self):
            return "broken"

        async def week_schedule(self, monday):
            raise ValueError("cannot reach Pinkbee")

    server.setup(Config(), Broken())
    assert await server.pinkbee_check_connection() == "Error: cannot reach Pinkbee"


# --- 2. groups and shifts -------------------------------------------------


async def test_groups_and_shifts_lists_ids_and_names():
    data = json.loads(await server.pinkbee_list_groups_and_shifts())
    names = {group["name"]: group["id"] for group in data["groups"]}
    assert names["Shop"] == 2
    assert names["Closing"] == 4


async def test_groups_and_shifts_maps_shifts_to_their_groups():
    data = json.loads(await server.pinkbee_list_groups_and_shifts())
    shop_morning = next(shift for shift in data["shifts"] if shift["code"] == "SO")
    assert shop_morning["group_ids"] == [2, 15]


async def test_groups_and_shifts_maps_groups_back_to_their_shifts():
    data = json.loads(await server.pinkbee_list_groups_and_shifts())
    shop = next(group for group in data["groups"] if group["id"] == 2)
    assert sorted(shop["shift_ids"]) == [3, 4]


async def test_groups_and_shifts_counts_members():
    data = json.loads(await server.pinkbee_list_groups_and_shifts())
    assert all(group["member_count"] >= 0 for group in data["groups"])
    assert any(group["member_count"] > 0 for group in data["groups"])


async def test_groups_and_shifts_contains_no_names_or_emails():
    """This tool must be safe with personal data switched off."""
    text = await server.pinkbee_list_groups_and_shifts()
    assert "@" not in text


# --- 3. week schedule -----------------------------------------------------


async def test_week_schedule_snaps_a_date_to_its_monday():
    data = json.loads(await server.pinkbee_get_week_schedule(dates=["2026-08-13"]))
    assert data["weeks"][0]["week_start"] == "2026-08-10"
    assert data["weeks"][0]["iso_week"] == "2026-W33"


async def test_week_schedule_accepts_several_dates():
    data = json.loads(await server.pinkbee_get_week_schedule(dates=["2026-08-13", "2026-08-20"]))
    assert [week["week_start"] for week in data["weeks"]] == ["2026-08-10", "2026-08-17"]


async def test_week_schedule_reads_a_repeated_week_only_once():
    data = json.loads(
        await server.pinkbee_get_week_schedule(dates=["2026-08-10", "2026-08-13", "2026-08-16"])
    )
    assert len(data["weeks"]) == 1
    assert data["weeks"][0]["requested_dates"] == ["2026-08-10", "2026-08-13", "2026-08-16"]


async def test_week_schedule_accepts_dutch_date_order():
    data = json.loads(await server.pinkbee_get_week_schedule(dates=["13-08-2026"]))
    assert data["weeks"][0]["week_start"] == "2026-08-10"


async def test_week_schedule_rejects_an_unreadable_date():
    answer = await server.pinkbee_get_week_schedule(dates=["13 augustus"])
    assert answer.startswith("Error: date must be YYYY-MM-DD or DD-MM-YYYY")


async def test_week_schedule_includes_full_shifts_by_default():
    data = json.loads(await server.pinkbee_get_week_schedule(dates=["2026-08-10"]))
    days = data["weeks"][0]["shift_days"]
    assert any(day["open_spots"] <= 0 for day in days)


async def test_week_schedule_can_show_only_open_shifts():
    data = json.loads(
        await server.pinkbee_get_week_schedule(dates=["2026-08-10"], only_open_shifts=True)
    )
    days = data["weeks"][0]["shift_days"]
    assert days
    assert all(day["open_spots"] > 0 for day in days)


async def test_week_schedule_counts_open_spots():
    data = json.loads(await server.pinkbee_get_week_schedule(dates=["2026-08-10"]))
    week = data["weeks"][0]
    expected = sum(day["open_spots"] for day in week["shift_days"] if day["open_spots"] > 0)
    assert week["open_spot_total"] == expected


async def test_week_schedule_contains_no_names():
    assert "@" not in await server.pinkbee_get_week_schedule(dates=["2026-08-10"])


# --- 4. open shifts -------------------------------------------------------


async def test_open_shifts_defaults_to_today_and_three_weeks():
    data = json.loads(await server.pinkbee_list_open_shifts())
    assert data["start_date"] == dt.date.today().isoformat()
    assert len(data["weeks_read"]) == 3
    assert data["weeks_read"][0] == THIS_MONDAY.isoformat()


async def test_open_shifts_only_returns_shifts_with_room():
    data = json.loads(await server.pinkbee_list_open_shifts(start_date="2026-08-10", weeks=2))
    assert data["shift_days"]
    assert all(day["open_spots"] > 0 for day in data["shift_days"])


async def test_open_shifts_leaves_out_days_before_the_start_date():
    data = json.loads(await server.pinkbee_list_open_shifts(start_date="2026-08-13", weeks=1))
    assert all(day["date"] >= "2026-08-13" for day in data["shift_days"])


async def test_open_shifts_can_filter_on_shift_id():
    data = json.loads(
        await server.pinkbee_list_open_shifts(start_date="2026-08-10", weeks=4, shift_ids=[3])
    )
    assert data["shift_days"]
    assert {day["shift_id"] for day in data["shift_days"]} == {3}


async def test_open_shifts_can_filter_on_group_id():
    data = json.loads(
        await server.pinkbee_list_open_shifts(start_date="2026-08-10", weeks=4, group_ids=[1])
    )
    assert data["shift_days"]
    assert all(1 in day["group_ids"] for day in data["shift_days"])


async def test_open_shifts_says_how_many_days_away_each_shift_is():
    data = json.loads(await server.pinkbee_list_open_shifts(start_date="2026-08-10", weeks=2))
    for day in data["shift_days"]:
        expected = (dt.date.fromisoformat(day["date"]) - dt.date(2026, 8, 10)).days
        assert day["days_from_now"] == expected


# --- 5. group emails ------------------------------------------------------


async def test_emails_are_refused_when_personal_data_is_off():
    answer = await server.pinkbee_list_group_emails(group_ids=[2])
    assert answer.startswith("Error: this tool returns personal data")


async def test_emails_are_returned_when_personal_data_is_on():
    allow_personal_data()
    data = json.loads(await server.pinkbee_list_group_emails(group_ids=[2]))
    assert data["count"] == len(data["emails"])
    assert all("@" in address for address in data["emails"])


async def test_emails_are_lowercase_sorted_and_unique():
    allow_personal_data()
    data = json.loads(await server.pinkbee_list_group_emails(group_ids=[2, 15]))
    assert data["emails"] == sorted(set(address.lower() for address in data["emails"]))


async def test_emails_combine_several_groups():
    allow_personal_data()
    shop = json.loads(await server.pinkbee_list_group_emails(group_ids=[2]))
    tower = json.loads(await server.pinkbee_list_group_emails(group_ids=[1]))
    both = json.loads(await server.pinkbee_list_group_emails(group_ids=[1, 2]))
    assert set(both["emails"]) == set(shop["emails"]) | set(tower["emails"])


async def test_emails_can_include_names_on_request():
    allow_personal_data()
    without = json.loads(await server.pinkbee_list_group_emails(group_ids=[2]))
    with_names = json.loads(
        await server.pinkbee_list_group_emails(group_ids=[2], with_names=True)
    )
    assert "people" not in without
    assert with_names["people"][0]["name"]


async def test_emails_reject_an_unknown_employment_value():
    allow_personal_data()
    answer = await server.pinkbee_list_group_emails(group_ids=[2], employment=["soon"])
    assert answer.startswith("Error: unknown employment value(s) ['soon']")


async def test_emails_respect_the_employment_filter():
    allow_personal_data()
    now_only = json.loads(await server.pinkbee_list_group_emails(group_ids=[2], employment=["now"]))
    with_past = json.loads(
        await server.pinkbee_list_group_emails(group_ids=[2], employment=["now", "past"])
    )
    assert with_past["count"] > now_only["count"]


# --- 6. registrations -----------------------------------------------------


async def test_registrations_are_refused_when_personal_data_is_off():
    answer = await server.pinkbee_list_registrations(
        start_date="2026-08-10", end_date="2026-08-16"
    )
    assert answer.startswith("Error: this tool returns personal data")


async def test_registrations_are_returned_when_personal_data_is_on():
    allow_personal_data()
    data = json.loads(
        await server.pinkbee_list_registrations(start_date="2026-08-10", end_date="2026-08-16")
    )
    assert data["count"] == len(data["registrations"])
    assert all(row["name"] for row in data["registrations"])


async def test_registrations_stay_inside_the_date_range():
    allow_personal_data()
    data = json.loads(
        await server.pinkbee_list_registrations(start_date="2026-08-10", end_date="2026-08-16")
    )
    assert all("2026-08-10" <= row["date"] <= "2026-08-16" for row in data["registrations"])


async def test_registrations_reject_a_backwards_date_range():
    allow_personal_data()
    answer = await server.pinkbee_list_registrations(
        start_date="2026-08-16", end_date="2026-08-10"
    )
    assert answer.startswith("Error: end_date")


async def test_registrations_can_filter_on_shift_id():
    allow_personal_data()
    data = json.loads(
        await server.pinkbee_list_registrations(
            start_date="2026-08-01", end_date="2026-09-30", shift_ids=[3]
        )
    )
    assert data["shift_ids"] == [3]
    assert {row["code"] for row in data["registrations"]} == {"SO"}


async def test_registrations_translate_group_ids_into_shift_ids():
    allow_personal_data()
    data = json.loads(
        await server.pinkbee_list_registrations(
            start_date="2026-08-01", end_date="2026-09-30", group_ids=[1]
        )
    )
    assert data["shift_ids"] == [5]  # the tower guide shift


async def test_registrations_add_the_shift_id_back_to_each_row():
    allow_personal_data()
    data = json.loads(
        await server.pinkbee_list_registrations(start_date="2026-08-10", end_date="2026-08-16")
    )
    assert all(row["shift_id"] is not None for row in data["registrations"])


# --- the tool list itself -------------------------------------------------


async def test_exactly_six_read_only_tools_are_registered():
    tools = await server.mcp.list_tools()
    assert {tool.name for tool in tools} == {
        "pinkbee_check_connection",
        "pinkbee_list_groups_and_shifts",
        "pinkbee_get_week_schedule",
        "pinkbee_list_open_shifts",
        "pinkbee_list_group_emails",
        "pinkbee_list_registrations",
    }
    for tool in tools:
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False


async def test_every_tool_argument_has_a_description():
    for tool in await server.mcp.list_tools():
        for name, field in tool.input_schema.get("properties", {}).items():
            assert field.get("description"), f"{tool.name}.{name} has no description"


async def test_required_arguments_are_marked_as_such():
    tools = {tool.name: tool for tool in await server.mcp.list_tools()}
    assert tools["pinkbee_get_week_schedule"].input_schema["required"] == ["dates"]
    assert tools["pinkbee_list_group_emails"].input_schema["required"] == ["group_ids"]
    assert sorted(tools["pinkbee_list_registrations"].input_schema["required"]) == [
        "end_date",
        "start_date",
    ]

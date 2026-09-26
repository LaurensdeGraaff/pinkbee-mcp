"""Tests for the MCP tools, running against the mock data source."""

import json
import datetime as dt

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from pinkbee_mcp import server
from pinkbee_mcp.config import AVAILABLE_CALLS, Config
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


async def test_check_connection_fails_loudly_on_a_broken_source():
    class Broken:
        def describe(self):
            return "broken"

        async def week_schedule(self, monday):
            raise ValueError("cannot reach Pinkbee")

    server.setup(Config(), Broken())
    with pytest.raises(ToolError, match="cannot reach Pinkbee"):
        await server.pinkbee_check_connection()


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
    with pytest.raises(ToolError, match="date must be YYYY-MM-DD or DD-MM-YYYY"):
        await server.pinkbee_get_week_schedule(dates=["13 augustus"])


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
    with pytest.raises(ToolError, match="returns personal data"):
        await server.pinkbee_list_group_emails(group_ids=[2])


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
    with pytest.raises(ToolError, match=r"unknown employment value\(s\) \['soon'\]"):
        await server.pinkbee_list_group_emails(group_ids=[2], employment=["soon"])


async def test_emails_reject_a_group_that_does_not_exist():
    allow_personal_data()
    with pytest.raises(ToolError, match=r"no volunteer group with id \[999999\]"):
        await server.pinkbee_list_group_emails(group_ids=[999999])


async def test_emails_respect_the_employment_filter():
    allow_personal_data()
    now_only = json.loads(await server.pinkbee_list_group_emails(group_ids=[2], employment=["now"]))
    with_past = json.loads(
        await server.pinkbee_list_group_emails(group_ids=[2], employment=["now", "past"])
    )
    assert with_past["count"] > now_only["count"]


# --- 6. registrations -----------------------------------------------------


async def test_registrations_are_refused_when_personal_data_is_off():
    with pytest.raises(ToolError, match="returns personal data"):
        await server.pinkbee_list_registrations(
            start_date="2026-08-10", end_date="2026-08-16", all_shifts=True
        )


async def test_registrations_are_returned_when_personal_data_is_on():
    allow_personal_data()
    data = json.loads(
        await server.pinkbee_list_registrations(
            start_date="2026-08-10", end_date="2026-08-16", all_shifts=True
        )
    )
    assert data["count"] == len(data["registrations"])
    assert all(row["name"] for row in data["registrations"])


async def test_registrations_stay_inside_the_date_range():
    allow_personal_data()
    data = json.loads(
        await server.pinkbee_list_registrations(
            start_date="2026-08-10", end_date="2026-08-16", all_shifts=True
        )
    )
    assert all("2026-08-10" <= row["date"] <= "2026-08-16" for row in data["registrations"])


async def test_registrations_reject_a_backwards_date_range():
    allow_personal_data()
    with pytest.raises(ToolError, match="end_date"):
        await server.pinkbee_list_registrations(
            start_date="2026-08-16", end_date="2026-08-10", all_shifts=True
        )


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
        await server.pinkbee_list_registrations(
            start_date="2026-08-10", end_date="2026-08-16", all_shifts=True
        )
    )
    assert all(row["shift_id"] is not None for row in data["registrations"])


# --- the tool list itself -------------------------------------------------


async def test_seven_tools_have_appropriate_annotations():
    tools = await server.mcp.list_tools()
    assert {tool.name for tool in tools} == AVAILABLE_CALLS
    for tool in tools:
        is_write = tool.name == "pinkbee_set_week_registration_possibilities"
        assert tool.annotations.read_only_hint is not is_write
        assert tool.annotations.destructive_hint is is_write
        assert tool.annotations.idempotent_hint is True


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
    assert sorted(tools["pinkbee_set_week_registration_possibilities"].input_schema["required"]) == [
        "date", "mode",
    ]


async def test_mock_write_normalizes_dates_and_updates_only_the_selected_week():
    mock = MockPinkbee()
    server.setup(Config(enable_write_to_pinkbee=True), mock)
    assert json.loads(await server.pinkbee_set_week_registration_possibilities(
        date="13-08-2026", mode="registration"
    )) == {"week_start": "2026-08-10", "mode": "registration"}
    await server.pinkbee_set_week_registration_possibilities(date="2026-08-20", mode="both")
    await server.pinkbee_set_week_registration_possibilities(
        date="2026-08-16", mode="deregistration"
    )
    assert mock.registration_possibilities == {
        "2026-08-10": "deregistration", "2026-08-17": "both",
    }


@pytest.mark.parametrize("mode", ["../both", "Both", "registration/", "", "both?x=1"])
async def test_write_rejects_unexpected_modes_before_accessing_the_source(mode):
    server.setup(Config(enable_write_to_pinkbee=True), MockPinkbee())
    with pytest.raises(ToolError, match="mode must be exactly"):
        await server.pinkbee_set_week_registration_possibilities(date="2026-08-13", mode=mode)


async def test_write_rejects_invalid_date_before_accessing_the_source():
    server.setup(Config(enable_write_to_pinkbee=True), MockPinkbee())
    with pytest.raises(ToolError, match="date must be"):
        await server.pinkbee_set_week_registration_possibilities(
            date="2026-08-13/../other", mode="both"
        )


async def test_live_tool_gate_prevents_any_source_io():
    class NoIO:
        def describe(self):
            return "no I/O"

        async def set_week_registration_possibilities(self, monday, mode):
            pytest.fail("write source was called")

    server.setup(Config(data_source="live"), NoIO())
    with pytest.raises(ToolError, match="ENABLE_WRITE_TO_PINKBEE"):
        await server.pinkbee_set_week_registration_possibilities(date="2026-08-13", mode="both")


async def test_mock_tool_also_requires_opt_in():
    with pytest.raises(ToolError, match="ENABLE_WRITE_TO_PINKBEE"):
        await server.pinkbee_set_week_registration_possibilities(date="2026-08-13", mode="both")


async def test_live_tool_calls_source_when_enabled():
    class Recorder(MockPinkbee):
        async def set_week_registration_possibilities(self, date, mode):
            self.sent_date = date
            await super().set_week_registration_possibilities(date, mode)

    mock = Recorder()
    server.setup(Config(data_source="live", enable_write_to_pinkbee=True), mock)
    result = json.loads(await server.pinkbee_set_week_registration_possibilities(
        date="2026-08-13", mode="both"
    ))
    assert result == {"week_start": "2026-08-10", "mode": "both"}
    assert mock.sent_date == "2026-08-13"
    assert mock.registration_possibilities == {"2026-08-10": "both"}


async def test_timeblock_tools_require_opt_in_before_reading_source():
    class NoIO:
        async def week_schedule(self, monday):
            pytest.fail("schedule was read before the write gate")

    server.setup(Config(data_source="live"), NoIO())
    with pytest.raises(ToolError, match="ENABLE_WRITE_TO_PINKBEE"):
        await server.pinkbee_set_shift_capacity(
            date="2099-01-01", shift_id=3, capacity=2
        )


async def test_capacity_write_selects_one_dated_timeblock():
    class Recorder(MockPinkbee):
        async def update_timeblock(self, timeblock_id, changes):
            self.updated = (timeblock_id, changes)

    mock = Recorder()
    server.setup(Config(enable_write_to_pinkbee=True), mock)
    target = server.today()
    result = json.loads(await server.pinkbee_set_shift_capacity(
        date=target.isoformat(), shift_id=3, capacity=4
    ))
    assert result["date"] == target.isoformat()
    assert result["shift_id"] == 3
    assert mock.updated[1] == {"capacity": 4}


async def test_time_tool_rejects_end_before_start():
    server.setup(Config(enable_write_to_pinkbee=True), MockPinkbee())
    with pytest.raises(ToolError, match="end_time must be after start_time"):
        await server.pinkbee_set_shift_time(
            date="2099-01-01", shift_id=3, start_time="12:00", end_time="11:00"
        )


# --- the filter must never widen by accident ------------------------------


async def test_registrations_refuse_a_group_that_does_not_exist():
    """The leak this replaced: an unmatched group became an empty = unfiltered query."""
    allow_personal_data()
    with pytest.raises(ToolError, match=r"no volunteer group with id \[999999\]"):
        await server.pinkbee_list_registrations(
            start_date="2026-08-10", end_date="2026-08-31", group_ids=[999999]
        )


async def test_registrations_refuse_a_shift_that_does_not_exist():
    allow_personal_data()
    with pytest.raises(ToolError, match=r"no shift with id \[999999\]"):
        await server.pinkbee_list_registrations(
            start_date="2026-08-10", end_date="2026-08-31", shift_ids=[999999]
        )


async def test_registrations_refuse_one_unknown_id_among_valid_ones():
    allow_personal_data()
    with pytest.raises(ToolError, match=r"\[999999\]"):
        await server.pinkbee_list_registrations(
            start_date="2026-08-10", end_date="2026-08-31", group_ids=[1, 999999]
        )


async def test_registrations_need_a_filter_or_an_explicit_all_shifts():
    allow_personal_data()
    with pytest.raises(ToolError, match="all_shifts=true"):
        await server.pinkbee_list_registrations(
            start_date="2026-08-10", end_date="2026-08-31"
        )


async def test_registrations_allow_everything_when_asked_explicitly():
    allow_personal_data()
    data = json.loads(
        await server.pinkbee_list_registrations(
            start_date="2026-08-10", end_date="2026-08-31", all_shifts=True
        )
    )
    assert data["shift_ids"] == []
    assert data["all_shifts"] is True
    assert data["count"] > 0


async def test_registrations_refuse_all_shifts_together_with_a_filter():
    allow_personal_data()
    with pytest.raises(ToolError, match="cannot be combined"):
        await server.pinkbee_list_registrations(
            start_date="2026-08-10", end_date="2026-08-31", group_ids=[2], all_shifts=True
        )


# --- limits ---------------------------------------------------------------


async def test_registrations_refuse_too_long_a_date_range():
    allow_personal_data()
    with pytest.raises(ToolError, match="at most 120"):
        await server.pinkbee_list_registrations(
            start_date="2026-01-01", end_date="2026-12-31", all_shifts=True
        )
async def test_registrations_refuse_an_oversized_id_list():
    allow_personal_data()
    with pytest.raises(ToolError, match="at most 50"):
        await server.pinkbee_list_registrations(
            start_date="2026-08-10",
            end_date="2026-08-31",
            shift_ids=list(range(100)),
        )


async def test_week_schedule_refuses_too_many_dates():
    dates = [(dt.date(2026, 8, 10) + dt.timedelta(weeks=week)).isoformat() for week in range(13)]
    with pytest.raises(ToolError, match="at most 12"):
        await server.pinkbee_get_week_schedule(dates=dates)


async def test_open_shifts_refuses_too_many_weeks():
    with pytest.raises(ToolError, match="at most 12"):
        await server.pinkbee_list_open_shifts(weeks=13)


async def test_open_shifts_refuses_an_oversized_id_list():
    with pytest.raises(ToolError, match="at most 50"):
        await server.pinkbee_list_open_shifts(group_ids=list(range(51)))

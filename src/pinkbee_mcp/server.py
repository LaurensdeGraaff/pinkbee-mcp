"""The MCP server: six read-only tools for a Pinkbee volunteer roster.

Each tool is a plain async function. It gets the data from the current data source
(mock or live), reshapes it, and returns JSON text.

When something goes wrong a tool raises `ToolError` with a sentence explaining what
to do about it. The SDK turns that into a tool result flagged `isError: true`, so the
client can see it really failed, while the model still gets the actionable sentence.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Annotated
from zoneinfo import ZoneInfo

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from . import roster
from .config import Config, load_config
from .live import LivePinkbee, PinkbeeError
from .logs import RequestLogger, StrictArguments
from .mock import MockPinkbee

log = logging.getLogger("pinkbee_mcp.tools")

# Refuses arguments that do not exist. setup() fills in the real argument names,
# once every tool is registered and its schema is known.
strict_arguments = StrictArguments({})

mcp = MCPServer(
    name="pinkbee_mcp",
    title="Pinkbee volunteer roster",
    instructions=(
        "Read-only access to a Pinkbee volunteer roster (shift planning for "
        "volunteers). Start with pinkbee_list_groups_and_shifts to learn the "
        "group and shift ids, then use the other tools. No tool can book, "
        "cancel or change anything in Pinkbee."
    ),
    version="0.2.0",
    # Two pieces of cross-cutting behaviour, both in logs.py.
    middleware=[strict_arguments, RequestLogger()],
)

READ_ONLY = {
    "read_only_hint": True,
    "destructive_hint": False,
    "idempotent_hint": True,
    "open_world_hint": True,
}

# Fixed safety limits keep responses useful and prevent bulk personal-data exports
# without adding deployment knobs that almost nobody needs.
MAX_REGISTRATION_DAYS = 120
MAX_IDS_PER_FILTER = 50
MAX_DATES = 12
MAX_WEEKS = 12

# Set by setup(); the tools read these.
config: Config | None = None
source: MockPinkbee | LivePinkbee | None = None


async def allowed_arguments() -> dict[str, set[str]]:
    """The argument names each tool really has, taken from its own schema."""
    return {
        tool.name: set(tool.input_schema.get("properties", {}))
        for tool in await mcp.list_tools()
    }


def setup(new_config: Config | None = None, new_source=None) -> None:
    """Choose the settings and the data source. Called once at startup."""
    global config, source
    config = new_config or load_config()
    if new_source is not None:
        source = new_source
    elif config.is_live:
        source = LivePinkbee(
            config.base_url, config.login, config.password, timeout=config.timeout_seconds
        )
    else:
        source = MockPinkbee()
    log.info("data source: %s", source.describe())


def today() -> dt.date:
    """Today in the roster's own timezone, not the container's UTC clock."""
    return dt.datetime.now(ZoneInfo(config.timezone)).date()


def parse_date(text: str) -> dt.date:
    """Accept 2026-08-13 or 13-08-2026."""
    cleaned = text.strip()
    for date_format in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return dt.datetime.strptime(cleaned, date_format).date()  # noqa: DTZ007
        except ValueError:
            continue
    raise ValueError(f"date must be YYYY-MM-DD or DD-MM-YYYY, got {text!r}")


def as_json(payload) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False)


def as_tool_error(problem: Exception) -> ToolError:
    """Turn any failure into a ToolError carrying one actionable sentence."""
    if isinstance(problem, ToolError):
        return problem
    if isinstance(problem, PinkbeeError | ValueError | KeyError):
        log.debug("handled %s: %s", type(problem).__name__, problem)
        return ToolError(str(problem))
    # Unexpected: keep the traceback in the log, where an operator can see it.
    log.exception("unexpected failure in a tool")
    return ToolError(f"unexpected {type(problem).__name__}: {problem}")


def require_personal_data() -> None:
    """Stop here unless the operator switched personal data on."""
    if not config.allow_personal_data:
        raise ToolError(
            "this tool returns personal data (names and email addresses) and is "
            "switched off. Start the server with PINKBEE_ALLOW_PERSONAL_DATA=true to "
            "allow it."
        )


def check_id_list(name: str, ids: list[int] | None) -> None:
    """Refuse an id filter longer than the safety limit."""
    if ids is not None and len(ids) > MAX_IDS_PER_FILTER:
        raise ToolError(
            f"{name} has {len(ids)} entries; at most {MAX_IDS_PER_FILTER} are allowed."
        )


# ---------------------------------------------------------------------------
# 1. Check the connection
# ---------------------------------------------------------------------------


@mcp.tool(
    name="pinkbee_check_connection",
    annotations=ToolAnnotations(title="Check the Pinkbee connection", **READ_ONLY),
)
async def pinkbee_check_connection() -> str:
    """Report which data source is in use and whether it answers.

    Reads this week's roster as a test. Use this first when another tool fails,
    to see whether the problem is the connection or your arguments.

    Returns:
        str: One line, for example "OK: built-in mock data (no connection to any
        Pinkbee instance). Week 2026-W33 has 42 shift days. Personal data: off."
        On failure the tool fails with an explanation of what to change.
    """
    try:
        monday = roster.monday_of(today())
        week = await source.week_schedule(monday.isoformat())
        rows = roster.flatten_week(week)
        return (
            f"OK: {source.describe()}. "
            f"Week {roster.iso_week(monday)} has {len(rows)} shift days. "
            f"Personal data: {'on' if config.allow_personal_data else 'off'}."
        )
    except Exception as problem:
        raise as_tool_error(problem) from problem


# ---------------------------------------------------------------------------
# 2. Groups and shifts (the id lookup table)
# ---------------------------------------------------------------------------


@mcp.tool(
    name="pinkbee_list_groups_and_shifts",
    annotations=ToolAnnotations(title="List volunteer groups and shift types", **READ_ONLY),
)
async def pinkbee_list_groups_and_shifts() -> str:
    """List every volunteer group and every shift type, with their ids.

    This is the lookup table for the other tools: they take group ids and shift
    ids, and this is where you find them. It also shows which groups may sign up
    for which shift, so you can go from a shift to its groups and back.

    Group names are free text chosen by the Pinkbee administrator, so match them
    yourself against what the user asked for (wording and capitalisation may
    differ).

    Returns:
        str: JSON with this shape:
        {
          "groups": [
            {"id": int, "name": str, "member_count": int, "shift_ids": [int]}
          ],
          "shifts": [
            {"id": int, "code": str, "description": str,
             "start_time": str, "end_time": str, "group_ids": [int]}
          ]
        }
        On failure the tool fails with an explanation of what to change.

    Examples:
        - "What is the id of the Shop group?" -> read it from "groups".
        - "Which groups belong to shift 4?" -> read "group_ids" of that shift.
    """
    try:
        groups = await source.groups()
        # The week endpoint is the one place that tells us, per shift, which
        # volunteer groups may register. Any week will do.
        week = await source.week_schedule(roster.monday_of(today()).isoformat())

        shifts = [
            {
                "id": shift.get("id"),
                "code": str(shift.get("code") or "").upper(),
                "description": shift.get("description") or "",
                "start_time": roster.short_time(shift.get("start_time")),
                "end_time": roster.short_time(shift.get("end_time")),
                "group_ids": shift.get("employee_group_ids") or [],
            }
            for shift in week
            if isinstance(shift, dict)
        ]
        shifts.sort(key=lambda shift: shift["id"] or 0)

        group_rows = [
            {
                "id": group.get("id"),
                "name": group.get("name") or "",
                "member_count": len(group.get("employees") or []),
                "shift_ids": [s["id"] for s in shifts if group.get("id") in s["group_ids"]],
            }
            for group in groups
            if isinstance(group, dict)
        ]
        group_rows.sort(key=lambda group: group["id"] or 0)

        return as_json({"groups": group_rows, "shifts": shifts})
    except Exception as problem:
        raise as_tool_error(problem) from problem


# ---------------------------------------------------------------------------
# 3. Week roster for one or more dates
# ---------------------------------------------------------------------------


@mcp.tool(
    name="pinkbee_get_week_schedule",
    annotations=ToolAnnotations(title="Get the roster for whole weeks", **READ_ONLY),
)
async def pinkbee_get_week_schedule(
    dates: Annotated[
        list[str],
        Field(
            description=(
                "One or more dates, as YYYY-MM-DD or DD-MM-YYYY. Each date returns the "
                "whole Monday-to-Sunday week it falls in. Dates in the same week are "
                "read only once."
            ),
            min_length=1,
        ),
    ],
    only_open_shifts: Annotated[
        bool,
        Field(description="Only return shift days that still have open spots."),
    ] = False,
) -> str:
    """Get the full roster for the week around each date you pass in.

    A Pinkbee week always runs Monday to Sunday, so any date is snapped back to
    its Monday. Every shift day is returned with its capacity, how many spots are
    taken, and how many are still open. No volunteer names are included, so this
    tool works whether or not personal data is switched on.

    Returns:
        str: JSON with this shape:
        {
          "weeks": [
            {
              "week_start": str,   # the Monday, e.g. "2026-08-10"
              "iso_week": str,     # e.g. "2026-W33"
              "requested_dates": [str],
              "shift_day_count": int,
              "open_spot_total": int,
              "shift_days": [
                {"date": str, "weekday": str, "shift_id": int, "code": str,
                 "description": str, "start_time": str, "end_time": str,
                 "group_ids": [int], "capacity": int, "taken": int,
                 "open_spots": int, "timeblock_id": int}
              ]
            }
          ]
        }
        On failure the tool fails with an explanation of what to change.

    Examples:
        - "What does the roster look like on 13 August?" -> dates=["2026-08-13"].
        - "Compare this week and next week" -> dates=["2026-08-13", "2026-08-20"].
        - "Where are the gaps in that week?" -> add only_open_shifts=true.
    """
    try:
        if len(dates) > MAX_DATES:
            raise ToolError(
                f"{len(dates)} dates given; at most {MAX_DATES} are allowed."
            )

        # Several dates can land in the same week. Read each week only once, but
        # remember every date that asked for it.
        dates_per_week: dict[str, list[str]] = {}
        for text in dates:
            monday = roster.monday_of(parse_date(text)).isoformat()
            dates_per_week.setdefault(monday, []).append(text.strip())

        weeks = []
        for monday in sorted(dates_per_week):
            rows = roster.flatten_week(await source.week_schedule(monday))
            if only_open_shifts:
                rows = roster.only_open(rows)
            open_spots = sum(row["open_spots"] for row in rows if row["open_spots"] > 0)
            log.debug(
                "week %s: %s shift days, %s open spots", monday, len(rows), open_spots
            )
            weeks.append(
                {
                    "week_start": monday,
                    "iso_week": roster.iso_week(dt.date.fromisoformat(monday)),
                    "requested_dates": dates_per_week[monday],
                    "shift_day_count": len(rows),
                    "open_spot_total": open_spots,
                    "shift_days": rows,
                }
            )
        return as_json({"weeks": weeks})
    except Exception as problem:
        raise as_tool_error(problem) from problem


# ---------------------------------------------------------------------------
# 4. Open shifts over a range of weeks
# ---------------------------------------------------------------------------


@mcp.tool(
    name="pinkbee_list_open_shifts",
    annotations=ToolAnnotations(title="List shifts that still need people", **READ_ONLY),
)
async def pinkbee_list_open_shifts(
    start_date: Annotated[
        str | None,
        Field(description="First date to look at, YYYY-MM-DD or DD-MM-YYYY. Defaults to today."),
    ] = None,
    weeks: Annotated[
        int,
        Field(
            description="How many weeks to look at, counted from start_date's week.",
            ge=1,
        ),
    ] = 3,
    shift_ids: Annotated[
        list[int] | None,
        Field(description="Only these shift types. Find ids with pinkbee_list_groups_and_shifts."),
    ] = None,
    group_ids: Annotated[
        list[int] | None,
        Field(description="Only shifts that these volunteer groups may sign up for."),
    ] = None,
) -> str:
    """List the shifts that still have open spots, over the coming weeks.

    Shifts in the past are left out, and so are shifts that are already full.
    Contains no volunteer names.

    Returns:
        str: JSON with this shape:
        {
          "start_date": str, "weeks": int, "weeks_read": [str],
          "shift_day_count": int, "open_spot_total": int,
          "shift_days": [
            {"date": str, "weekday": str, "shift_id": int, "code": str,
             "description": str, "start_time": str, "end_time": str,
             "group_ids": [int], "capacity": int, "taken": int,
             "open_spots": int, "timeblock_id": int, "days_from_now": int}
          ]
        }
        On failure the tool fails with an explanation of what to change.

    Examples:
        - "Which shifts still need volunteers?" -> no arguments needed.
        - "Any gaps for the Shop group in the next 6 weeks?" -> group_ids=[2], weeks=6.
    """
    try:
        if weeks > MAX_WEEKS:
            raise ToolError(f"{weeks} weeks asked for; at most {MAX_WEEKS} are allowed.")
        check_id_list("shift_ids", shift_ids)
        check_id_list("group_ids", group_ids)

        first_day = parse_date(start_date) if start_date else today()
        first_monday = roster.monday_of(first_day)

        weeks_read = []
        found = []
        for week_number in range(weeks):
            monday = first_monday + dt.timedelta(days=7 * week_number)
            weeks_read.append(monday.isoformat())
            week = await source.week_schedule(monday.isoformat())
            for row in roster.only_open(roster.flatten_week(week)):
                day = dt.date.fromisoformat(row["date"])
                if day < first_day:
                    continue
                if shift_ids and row["shift_id"] not in shift_ids:
                    continue
                if group_ids and not set(group_ids) & set(row["group_ids"]):
                    continue
                found.append({**row, "days_from_now": (day - first_day).days})

        log.debug(
            "read %s weeks from %s, kept %s open shift days",
            len(weeks_read),
            first_monday,
            len(found),
        )
        return as_json(
            {
                "start_date": first_day.isoformat(),
                "weeks": weeks,
                "weeks_read": weeks_read,
                "shift_day_count": len(found),
                "open_spot_total": sum(row["open_spots"] for row in found),
                "shift_days": found,
            }
        )
    except Exception as problem:
        raise as_tool_error(problem) from problem


# ---------------------------------------------------------------------------
# 5. Email addresses of a group (personal data)
# ---------------------------------------------------------------------------


@mcp.tool(
    name="pinkbee_list_group_emails",
    annotations=ToolAnnotations(title="List email addresses of volunteer groups", **READ_ONLY),
)
async def pinkbee_list_group_emails(
    group_ids: Annotated[
        list[int],
        Field(
            description="Volunteer group ids, for example [2, 16]. Groups are combined with OR.",
            min_length=1,
            max_length=50,
        ),
    ],
    employment: Annotated[
        list[str],
        Field(description="Which volunteers to include: 'now', 'future' and/or 'past'."),
    ] = ["now", "future"],  # noqa: B006 - only read, never changed
    with_names: Annotated[
        bool,
        Field(description="Also return each volunteer's name next to their address."),
    ] = False,
) -> str:
    """List the email addresses of the volunteers in one or more groups.

    Returns personal data, so it only works when the server runs with
    PINKBEE_ALLOW_PERSONAL_DATA=true. Do not copy the addresses into files,
    tickets or logs.

    Returns:
        str: JSON with this shape:
        {
          "group_ids": [int], "employment": [str], "count": int,
          "emails": [str],                                   # always
          "people": [{"id": int, "name": str, "email": str}]  # only with_names
        }
        On failure, or when personal data is switched off, the tool fails with an
        explanation of what to change.

    Examples:
        - "Email addresses for groups 2 and 16" -> group_ids=[2, 16].
        - "Who is in the Opening group, with names?" -> group_ids=[5], with_names=true.
    """
    try:
        require_personal_data()
        check_id_list("group_ids", group_ids)

        wanted = [status.strip().lower() for status in employment if status.strip()]
        unknown = sorted(set(wanted) - {"now", "future", "past"})
        if unknown:
            raise ToolError(
                f"unknown employment value(s) {unknown}. Use 'now', 'future' or 'past'."
            )

        # An id that does not exist must be an error, not a filter that quietly
        # matches nothing or, worse, everything.
        existing_groups, _ = await known_ids()
        unknown_groups = sorted(set(group_ids) - existing_groups)
        if unknown_groups:
            raise ToolError(
                f"no volunteer group with id {unknown_groups}. Use "
                "pinkbee_list_groups_and_shifts to see the ids that exist."
            )

        log.debug("asking for contacts of groups %s with status %s", group_ids, wanted)
        rows = await source.contacts(group_ids, wanted or ["now", "future"])
        if not isinstance(rows, list):
            raise ToolError("Pinkbee did not return a list of contacts.")

        emails = sorted(
            {str(row.get("email", "")).strip().lower() for row in rows if row.get("email")}
        )
        result = {
            "group_ids": group_ids,
            "employment": wanted,
            "count": len(emails),
            "emails": emails,
        }
        if with_names:
            result["people"] = [
                {
                    "id": row.get("id"),
                    "name": row.get("name") or "",
                    "email": row.get("email") or "",
                }
                for row in rows
                if row.get("email")
            ]
        return as_json(result)
    except Exception as problem:
        raise as_tool_error(problem) from problem


# ---------------------------------------------------------------------------
# 6. Registrations in a date range (personal data)
# ---------------------------------------------------------------------------


@mcp.tool(
    name="pinkbee_list_registrations",
    annotations=ToolAnnotations(title="List who signed up for which shift", **READ_ONLY),
)
async def pinkbee_list_registrations(
    start_date: Annotated[str, Field(description="First date, YYYY-MM-DD or DD-MM-YYYY.")],
    end_date: Annotated[str, Field(description="Last date, YYYY-MM-DD or DD-MM-YYYY.")],
    shift_ids: Annotated[
        list[int] | None,
        Field(description="Only these shift types, for example [4, 6, 14]. Omit for all shifts."),
    ] = None,
    group_ids: Annotated[
        list[int] | None,
        Field(
            description=(
                "Only shifts belonging to these volunteer groups. Translated into shift "
                "ids for you, so you do not have to look them up first."
            )
        ),
    ] = None,
    all_shifts: Annotated[
        bool,
        Field(
            description=(
                "Include every shift. Only needed when you pass no shift_ids and no "
                "group_ids, and it cannot be combined with either."
            )
        ),
    ] = False,
) -> str:
    """List the volunteers who signed up for shifts between two dates.

    Returns names, so it only works when the server runs with
    PINKBEE_ALLOW_PERSONAL_DATA=true.

    Say which shifts you mean with shift_ids or group_ids. An id that does not exist
    is an error rather than an empty filter, so a typo can never widen the answer to
    the whole roster. To ask for every shift on purpose, pass all_shifts=true.

    The date range is limited to keep one call from exporting months of personal
    data at once.

    Returns:
        str: JSON with this shape:
        {
          "start_date": str, "end_date": str, "shift_ids": [int], "count": int,
          "registrations": [
            {"id": int, "date": str, "shift_id": int | null, "code": str,
             "shift": str, "employee_id": int, "name": str,
             "start_time": str, "end_time": str, "hours": float}
          ]
        }
        On failure, or when personal data is switched off, the tool fails with an
        explanation of what to change.

    Examples:
        - "Who signed up for the Shop shifts?" -> group_ids=[2].
        - "Who is scheduled in August?" -> start_date="2026-08-01",
          end_date="2026-08-31", all_shifts=true.
    """
    try:
        require_personal_data()
        check_id_list("shift_ids", shift_ids)
        check_id_list("group_ids", group_ids)

        first_day = parse_date(start_date)
        last_day = parse_date(end_date)
        if last_day < first_day:
            raise ToolError(f"end_date {last_day} is before start_date {first_day}.")
        days = (last_day - first_day).days + 1
        if days > MAX_REGISTRATION_DAYS:
            raise ToolError(
                f"that range is {days} days; at most {MAX_REGISTRATION_DAYS} are "
                "allowed. Ask for a shorter period."
            )

        wanted_shift_ids = await resolve_shift_filter(shift_ids, group_ids, all_shifts)
        log.debug(
            "registrations for shifts %s over %s days from %s",
            wanted_shift_ids or "all (asked for explicitly)",
            days,
            first_day,
        )

        rows = await source.registrations(
            wanted_shift_ids, first_day.isoformat(), last_day.isoformat()
        )
        if not isinstance(rows, list):
            raise ToolError("Pinkbee did not return a list of registrations.")

        # The report only gives a shift code, so add the shift id back.
        shift_id_of_code = await shift_id_by_code()
        registrations = [
            {
                "id": row.get("id"),
                "date": row.get("date"),
                "shift_id": shift_id_of_code.get(str(row.get("shiftcode") or "").upper()),
                "code": row.get("shiftcode"),
                "shift": row.get("shift"),
                "employee_id": row.get("employeeId"),
                "name": row.get("employeeName"),
                "start_time": roster.short_time(row.get("shiftStartTime")),
                "end_time": roster.short_time(row.get("shiftEndTime")),
                "hours": row.get("shiftDuration"),
            }
            for row in rows
        ]
        return as_json(
            {
                "start_date": first_day.isoformat(),
                "end_date": last_day.isoformat(),
                "shift_ids": wanted_shift_ids,
                "all_shifts": all_shifts,
                "count": len(registrations),
                "registrations": registrations,
            }
        )
    except Exception as problem:
        raise as_tool_error(problem) from problem


# ---------------------------------------------------------------------------
# Small helpers that need the data source
# ---------------------------------------------------------------------------


async def shift_ids_for_groups(group_ids: list[int]) -> list[int]:
    """Which shift types the given volunteer groups may sign up for."""
    week = await source.week_schedule(roster.monday_of(today()).isoformat())
    wanted = set(group_ids)
    return [
        shift["id"]
        for shift in week
        if isinstance(shift, dict) and wanted & set(shift.get("employee_group_ids") or [])
    ]


async def known_ids() -> tuple[set[int], set[int]]:
    """The group ids and shift ids that actually exist right now."""
    week = await source.week_schedule(roster.monday_of(today()).isoformat())
    groups = await source.groups()
    group_ids = {group.get("id") for group in groups if isinstance(group, dict)}
    shift_ids = {shift.get("id") for shift in week if isinstance(shift, dict)}
    return group_ids, shift_ids


async def resolve_shift_filter(
    shift_ids: list[int] | None, group_ids: list[int] | None, all_shifts: bool
) -> list[int]:
    """Work out which shift ids a filter means, refusing anything unclear.

    An empty list means "every shift" to Pinkbee, so it must only ever be returned
    when the caller deliberately asked for that. A filter that matches nothing has to
    be an error: silently widening it to every shift would hand back the whole
    roster, including everyone's name.
    """
    asked_for_a_filter = bool(shift_ids) or bool(group_ids)

    if not asked_for_a_filter:
        if not all_shifts:
            raise ToolError(
                "give shift_ids or group_ids to say which shifts you mean, or pass "
                "all_shifts=true if you really want every shift. Use "
                "pinkbee_list_groups_and_shifts to find the ids."
            )
        return []  # deliberately unfiltered

    if all_shifts:
        raise ToolError(
            "all_shifts=true cannot be combined with shift_ids or group_ids. Drop the "
            "filter, or drop all_shifts."
        )

    existing_groups, existing_shifts = await known_ids()

    unknown_groups = sorted(set(group_ids or []) - existing_groups)
    if unknown_groups:
        raise ToolError(
            f"no volunteer group with id {unknown_groups}. Use "
            "pinkbee_list_groups_and_shifts to see the ids that exist."
        )

    unknown_shifts = sorted(set(shift_ids or []) - existing_shifts)
    if unknown_shifts:
        raise ToolError(
            f"no shift with id {unknown_shifts}. Use pinkbee_list_groups_and_shifts "
            "to see the ids that exist."
        )

    resolved = set(shift_ids or [])
    if group_ids:
        from_groups = await shift_ids_for_groups(group_ids)
        log.debug("groups %s map to shifts %s", group_ids, from_groups)
        if not from_groups and not resolved:
            raise ToolError(
                f"group {sorted(group_ids)} exists but has no shifts, so there is "
                "nothing to report on."
            )
        resolved |= set(from_groups)

    return sorted(resolved)


async def shift_id_by_code() -> dict[str, int]:
    """Look up a shift id by its code, because the report only gives the code."""
    week = await source.week_schedule(roster.monday_of(today()).isoformat())
    return {
        str(shift.get("code") or "").upper(): shift.get("id")
        for shift in week
        if isinstance(shift, dict) and shift.get("code")
    }

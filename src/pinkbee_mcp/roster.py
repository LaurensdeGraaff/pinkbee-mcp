"""Turns a raw Pinkbee week into a simple, flat list of shifts.

The week endpoint gives you a list of shift types, each with a `timeblocks` list
holding one entry per day. This module flattens that into one row per shift per
day, and works out how many spots are still open.
"""

from __future__ import annotations

import datetime as dt

WEEKDAYS_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def monday_of(day: dt.date) -> dt.date:
    """The Monday of the week that `day` falls in."""
    return day - dt.timedelta(days=day.weekday())


def iso_week(day: dt.date) -> str:
    """A week label such as "2026-W33"."""
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def count_taken_spots(timeblock: dict) -> int:
    """How many spots are actually taken.

    A registration marked `is_absent` frees the spot again. The similar-looking
    `indicators.is_absent` is only a warning shown in the Pinkbee interface and
    does *not* free the spot, so it is ignored here on purpose.
    """
    registrations = timeblock.get("registrations")
    if not isinstance(registrations, list):
        return 0
    return sum(1 for entry in registrations if not entry.get("is_absent"))


def timeblocks_of(shift: dict) -> list[dict]:
    """The day entries of a shift. Some shifts are their own single entry."""
    blocks = shift.get("timeblocks")
    if not isinstance(blocks, list):
        blocks = [shift]
    return [block for block in blocks if isinstance(block, dict)]


def flatten_week(week: list) -> list[dict]:
    """One row per shift per day, sorted by date, then shift code.

    Each row has: date, weekday, shift_id, code, description, start_time,
    end_time, group_ids, capacity, taken, open_spots, timeblock_id.
    """
    if not isinstance(week, list):
        # ValueError, not TypeError: the tools turn it into an "Error: ..." message.
        raise ValueError("A Pinkbee week must be a list of shifts")  # noqa: TRY004

    rows = []
    for shift in week:
        if not isinstance(shift, dict):
            continue
        for block in timeblocks_of(shift):
            date = block.get("date")
            if not date:
                continue
            capacity = int(block.get("capacity") or 0)
            taken = count_taken_spots(block)
            day = dt.date.fromisoformat(str(date)[:10])
            rows.append(
                {
                    "date": day.isoformat(),
                    "weekday": WEEKDAYS_SHORT[day.weekday()],
                    "shift_id": shift.get("id"),
                    "code": str(shift.get("code") or "").upper(),
                    "description": shift.get("description") or "",
                    "start_time": short_time(block.get("start_time") or shift.get("start_time")),
                    "end_time": short_time(block.get("end_time") or shift.get("end_time")),
                    "group_ids": shift.get("employee_group_ids") or [],
                    "capacity": capacity,
                    "taken": taken,
                    "open_spots": capacity - taken,
                    "timeblock_id": block.get("id"),
                }
            )
    return sorted(rows, key=lambda row: (row["date"], row["code"], str(row["timeblock_id"])))


def short_time(value: object) -> str:
    """Turn "14:00:00" into "14:00". Missing times become an empty string."""
    if not value:
        return ""
    return str(value)[:5]


def only_open(rows: list[dict]) -> list[dict]:
    """Keep the shifts that still need people."""
    return [row for row in rows if row["open_spots"] > 0]

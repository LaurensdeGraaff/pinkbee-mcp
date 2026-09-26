"""Built-in sample data, shaped exactly like a real Pinkbee instance.

This is the default data source. You can run and test the whole server without
credentials and without touching anyone's production roster.

The data is generated from the small tables below, so any week you ask for gets
an answer. It is deterministic: the same date always gives the same result,
because the numbers come from a checksum of the date instead of a random number.

Names, emails and group names here are invented.
"""

from __future__ import annotations

import datetime as dt
import zlib

# Volunteer groups: "who someone is".
GROUPS = [
    {"id": 1, "name": "Tower guides"},
    {"id": 2, "name": "Shop"},
    {"id": 4, "name": "Closing"},
    {"id": 5, "name": "Opening"},
    {"id": 6, "name": "Catering"},
    {"id": 15, "name": "Standby shop"},
]

# Shift types: "what needs doing". `employee_group_ids` is the link between a
# shift and the volunteer groups allowed to sign up for it.
SHIFTS = [
    {
        "id": 1, "code": "OP", "description": "Opening",
        "employee_group_ids": [5], "shift_group": {"id": 3, "name": "Opening"},
        "start_time": "11:00:00", "end_time": "12:00:00",
        "weekdays": [0, 1, 2, 3, 4, 5], "capacity": 1,
    },
    {
        "id": 2, "code": "CL", "description": "Closing",
        "employee_group_ids": [4], "shift_group": {"id": 4, "name": "Closing"},
        "start_time": "15:00:00", "end_time": "16:00:00",
        "weekdays": [0, 1, 2, 3, 4, 5], "capacity": 1,
    },
    {
        "id": 3, "code": "SO", "description": "Shop morning",
        "employee_group_ids": [2, 15], "shift_group": {"id": 1, "name": "Shop"},
        "start_time": "11:00:00", "end_time": "14:00:00",
        "weekdays": [0, 1, 2, 3, 4, 5], "capacity": 2,
    },
    {
        "id": 4, "code": "SM", "description": "Shop afternoon",
        "employee_group_ids": [2, 15], "shift_group": {"id": 1, "name": "Shop"},
        "start_time": "14:00:00", "end_time": "17:00:00",
        "weekdays": [0, 1, 2, 3, 4, 5], "capacity": 2,
    },
    {
        "id": 5, "code": "TG", "description": "Tower guide",
        "employee_group_ids": [1], "shift_group": {"id": 2, "name": "Tower guides"},
        "start_time": "13:00:00", "end_time": "14:30:00",
        "weekdays": [5, 6], "capacity": 1,
    },
    {
        "id": 6, "code": "CA", "description": "Coffee and tea",
        "employee_group_ids": [6], "shift_group": {"id": 5, "name": "Catering"},
        "start_time": "10:00:00", "end_time": "12:00:00",
        "weekdays": [6], "capacity": 2,
    },
]

# Volunteers. `groups` is which volunteer groups they belong to.
EMPLOYEES = [
    {"id": 11, "first_name": "Anke", "last_name": "Bakker", "groups": [2], "status": "now"},
    {"id": 12, "first_name": "Bram", "last_name": "de Vries", "groups": [2, 4], "status": "now"},
    {"id": 13, "first_name": "Carla", "last_name": "Smit", "groups": [2, 15], "status": "now"},
    {"id": 14, "first_name": "Dirk", "last_name": "Jansen", "groups": [5], "status": "now"},
    {"id": 15, "first_name": "Eva", "last_name": "Molenaar", "groups": [4, 5], "status": "now"},
    {"id": 16, "first_name": "Femke", "last_name": "Visser", "groups": [1], "status": "now"},
    {"id": 17, "first_name": "Gerrit", "last_name": "Post", "groups": [1, 6], "status": "now"},
    {"id": 18, "first_name": "Hanna", "last_name": "Willems", "groups": [6], "status": "future"},
    {"id": 19, "first_name": "Ivo", "last_name": "Lemmens", "groups": [15], "status": "now"},
    {"id": 20, "first_name": "Joke", "last_name": "Terpstra", "groups": [2], "status": "past"},
]


def stable_number(*parts: object) -> int:
    """A number that is always the same for the same input.

    Used instead of a random number so that mock data never changes between two
    calls, which would make tests flaky and results confusing.
    """
    text = "|".join(str(part) for part in parts)
    return zlib.crc32(text.encode())


def employees_for_shift(shift: dict) -> list[dict]:
    """The volunteers allowed to sign up for this shift."""
    allowed = set(shift["employee_group_ids"])
    return [person for person in EMPLOYEES if allowed & set(person["groups"])]


def full_name(person: dict) -> str:
    return f"{person['first_name']} {person['last_name']}"


class MockPinkbee:
    """Answers the same questions as LivePinkbee, from the tables above."""

    def __init__(self) -> None:
        self.registration_possibilities: dict[str, str] = {}

    async def set_week_registration_possibilities(self, date: str, mode: str) -> None:
        """Remember a week's selected mode without changing other weeks."""
        day = dt.date.fromisoformat(date)
        monday = day - dt.timedelta(days=day.weekday())
        self.registration_possibilities[monday.isoformat()] = mode

    def describe(self) -> str:
        return "built-in mock data (no connection to any Pinkbee instance)"

    async def close(self) -> None:
        return None

    async def log_in(self) -> None:
        return None

    async def week_schedule(self, monday: str) -> list:
        """Build one week of shifts, the same shape the real API returns."""
        first_day = dt.date.fromisoformat(monday)
        week = []
        for shift in SHIFTS:
            timeblocks = []
            for day_number in range(7):
                day = first_day + dt.timedelta(days=day_number)
                capacity = shift["capacity"] if day.weekday() in shift["weekdays"] else 0
                timeblocks.append(
                    {
                        "id": stable_number("timeblock", shift["id"], day) % 100000,
                        "date": day.isoformat(),
                        "start_time": shift["start_time"],
                        "end_time": shift["end_time"],
                        "capacity": capacity,
                        "comment": "",
                        "registrations": mock_registrations(shift, day, capacity),
                    }
                )
            week.append(
                {
                    "id": shift["id"],
                    "code": shift["code"],
                    "description": shift["description"],
                    "start_time": shift["start_time"],
                    "end_time": shift["end_time"],
                    "employee_group_ids": shift["employee_group_ids"],
                    "shift_group": shift["shift_group"],
                    "permissions": "register",
                    "timeblocks": timeblocks,
                }
            )
        return week

    async def groups(self) -> list:
        return [
            {
                "id": group["id"],
                "name": group["name"],
                "employees": [
                    {"id": person["id"], "status": person["status"]}
                    for person in EMPLOYEES
                    if group["id"] in person["groups"]
                ],
            }
            for group in GROUPS
        ]

    async def shifts(self) -> list:
        return [
            {
                "id": shift["id"],
                "code": shift["code"],
                "description": shift["description"],
                "start_time": shift["start_time"],
                "end_time": shift["end_time"],
                "shift_group": shift["shift_group"]["id"],
            }
            for shift in SHIFTS
        ]

    async def shift_group_links(self) -> list:
        links = []
        for shift in SHIFTS:
            for group_id in shift["employee_group_ids"]:
                links.append(
                    {
                        "id": len(links) + 1,
                        "permissions": "register",
                        "employee_group": group_id,
                        "shift": shift["id"],
                        "shift_group": shift["shift_group"]["id"],
                    }
                )
        return links

    async def contacts(self, group_ids: list[int], employment: list[str]) -> list:
        wanted_groups = set(group_ids)
        wanted_status = set(employment)
        rows = []
        for person in EMPLOYEES:
            if not wanted_groups & set(person["groups"]):
                continue
            if person["status"] not in wanted_status:
                continue
            rows.append(
                {
                    "id": person["id"],
                    "name": full_name(person),
                    "first_name": person["first_name"],
                    "last_name_prefix": "",
                    "last_name": person["last_name"],
                    "email": mock_email(person),
                    "phone": "",
                    "mobilePhone": "06 000 000 00",
                    "address": "Sample Street 1",
                    "postalCode": "1000 AA",
                    "city": "Sampletown",
                    "country": "Nederland",
                    "archived": False,
                }
            )
        return rows

    async def registrations(self, shift_ids: list[int], start_date: str, end_date: str) -> list:
        """Rebuild the registration report from the generated weeks.

        This keeps the mock self-consistent: the report always agrees with what
        `week_schedule` shows.
        """
        first = dt.date.fromisoformat(start_date)
        last = dt.date.fromisoformat(end_date)
        wanted = set(shift_ids)
        shifts_by_id = {shift["id"]: shift for shift in SHIFTS}

        rows = []
        monday = first - dt.timedelta(days=first.weekday())
        while monday <= last:
            for shift in await self.week_schedule(monday.isoformat()):
                if wanted and shift["id"] not in wanted:
                    continue
                for block in shift["timeblocks"]:
                    day = dt.date.fromisoformat(block["date"])
                    if day < first or day > last:
                        continue
                    for registration in block["registrations"]:
                        person = employee_by_id(registration["employee"])
                        rows.append(
                            {
                                "id": registration["id"],
                                "date": block["date"],
                                "shiftcode": shift["code"],
                                "shift": shift["description"],
                                "employeeId": person["id"],
                                "employeeName": full_name(person),
                                "employeeFirstName": person["first_name"],
                                "employeeLastNamePrefix": "",
                                "employeeLastName": person["last_name"],
                                "shiftStartTime": shift["start_time"],
                                "shiftEndTime": shift["end_time"],
                                "shiftDuration": shift_hours(shifts_by_id[shift["id"]]),
                            }
                        )
            monday += dt.timedelta(days=7)
        return sorted(rows, key=lambda row: (row["date"], row["shiftcode"], row["id"]))


def employee_by_id(employee_id: int) -> dict:
    for person in EMPLOYEES:
        if person["id"] == employee_id:
            return person
    raise KeyError(f"No mock employee with id {employee_id}")


def mock_email(person: dict) -> str:
    """An obviously fake address. example.org can never receive mail."""
    return f"{person['first_name']}.{person['last_name']}@example.org".replace(" ", "").lower()


def shift_hours(shift: dict) -> float:
    start = dt.time.fromisoformat(shift["start_time"])
    end = dt.time.fromisoformat(shift["end_time"])
    minutes = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
    return round(minutes / 60, 2)


def mock_registrations(shift: dict, day: dt.date, capacity: int) -> list:
    """Fill some of the capacity, so there are both full and open shifts.

    One registration in four is marked absent, which frees the spot again. That
    matches the real Pinkbee rule and keeps the open-shift logic exercised.
    """
    if capacity <= 0:
        return []
    candidates = employees_for_shift(shift)
    if not candidates:
        return []

    # How many people signed up: 0, 1 or capacity, decided by the date.
    how_many = stable_number("count", shift["id"], day) % (capacity + 1)
    registrations = []
    for slot in range(how_many):
        seed = stable_number("who", shift["id"], day, slot)
        person = candidates[seed % len(candidates)]
        if any(existing["employee"] == person["id"] for existing in registrations):
            continue
        registrations.append(
            {
                "id": stable_number("registration", shift["id"], day, slot) % 100000,
                "employee": person["id"],
                "registered_by": 1,
                "is_absent": seed % 4 == 0,
                "indicators": {"is_absent": False, "double_registration": False},
            }
        )
    return registrations

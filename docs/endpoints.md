# The Pinkbee API

Pinkbee publishes no API documentation. Everything below was found by logging
into a Pinkbee instance and watching which URLs its own web app calls. It is
accurate for the instance it was checked against; another instance could differ.

All paths are relative to `https://<your-organisation>.mijnpinkbee.nl`.

## Logging in

Pinkbee is a Django website. There is no API key: you log in like a browser and
get a session cookie.

| Step | Request | Why |
| --- | --- | --- |
| 1 | `GET /accounts/login/` | Get the login page and the `csrftoken` cookie |
| 2 | — | Read `<input name="csrfmiddlewaretoken" value="…">` out of the HTML and unescape it |
| 3 | `POST /accounts/login/` | Form fields: `csrfmiddlewaretoken`, `next=/`, `login`, `password` |
| 4 | — | Keep using the `sessionid` cookie for every later GET |

Two things to know:

- **A failed login also answers HTTP 200**, with the login form rendered again. A
  successful one redirects to `/`. So you cannot tell them apart by status code
  or URL — check whether the returned page *is* the login form. `live.py` looks
  for a page that has both a CSRF token and a password field.
- **Sessions expire.** `live.py` logs in again once and retries when a request
  comes back 401/403 or returns the login page.

The opt-in weekly setting below also uses PUT. Without the write opt-in, login is
the only non-GET request.

## An unknown path answers HTTP 200

Pinkbee serves its web app for any URL it does not recognise, including under
`/api/`. So a 200 with `content-type: text/html` means *"this endpoint does not
exist"*, not "success". Guessing paths is unreliable; `live.py` treats a non-JSON
answer as an error and says the path is probably wrong.

## `GET /api/schedule/week/<YYYY-MM-DD>`

One roster week. The date **must be the Monday** that starts the week; this server
snaps any date back to its Monday for you.

Returns a list of shift types. Each has a `timeblocks` list with one entry per day
of that week.

```jsonc
[
  {
    "id": 3,                          // shift id
    "code": "SO",
    "description": "Shop morning",
    "start_time": "11:00:00",
    "end_time": "14:00:00",
    "employee_group_ids": [2, 15],    // groups allowed to sign up  <-- the link
    "shift_group": { "id": 1, "name": "Shop" },
    "permissions": "register",
    "timeblocks": [
      {
        "id": 6871,                   // timeblock id: this shift on this day
        "date": "2026-08-16",
        "capacity": 2,                // total spots
        "registrations": [
          { "id": 1, "employee": 70 },                            // takes a spot
          { "id": 2, "employee": 71, "is_absent": true },          // frees the spot
          { "id": 3, "employee": 72,
            "indicators": { "is_absent": true } }                 // still takes it
        ]
      }
    ]
  }
]
```

Counting open spots:

```
open_spots = capacity - (registrations that are not is_absent)
```

The trap: a registration has a top-level `is_absent` **and** an
`indicators.is_absent`. Only the top-level one frees the spot. The one under
`indicators` is a warning Pinkbee shows in its interface (for example "this person
said they are unavailable") and the spot stays taken. `roster.py` implements this,
and a test covers each case.

Also note `capacity: 0` — a shift that does not run on that weekday still appears,
with zero capacity. Those are not open shifts.

This endpoint is also the answer to *"how do I get from a shift to a group?"*: the
`employee_group_ids` field. Nothing else needs to be looked up.

## `PUT /api/schedule/week/<YYYY-MM-DD>/registration-possibilities/<mode>`

Sets which actions volunteers may take for the week containing the date. The UI
capture used a Thursday (`2026-10-29`), so the MCP sends the selected date in the
path rather than replacing it with Monday. The tool also returns the Monday as
`week_start` to identify the affected week.

| Mode | Volunteers may |
| --- | --- |
| `registration` | Sign up only |
| `deregistration` | Cancel a sign-up only |
| `both` | Sign up and cancel |

The request has no body. The captured UI sent an `x-csrftoken` header and received
`204 No Content` for `registration` and `both`; `deregistration` is the third mode
identified for this endpoint. The MCP uses the login session's CSRF cookie and
requires `ENABLE_WRITE_TO_PINKBEE=true` before sending a PUT. It treats anything
other than 204 as unconfirmed and does not replay a write after a session failure.
The capture did not include a GET of the current mode, so this project does not
claim to read back or automatically restore the previous value.

## `GET /api/group/`

Every volunteer group, with its members.

```jsonc
[
  {
    "id": 2,
    "name": "Shop",
    "employees": [ { "id": 36, "status": "now" }, { "id": 33, "status": "past" } ],
    "show_in_clientschedule": false,
    "deletability": {}
  }
]
```

`status` is `now`, `future` or `past`. Group names are free text.

## `GET /api/report/employees/contact?filter=<url-encoded JSON>`

Contact details of volunteers, filtered by group. The filter is a **JSON object
inside the query string**:

```json
{ "employmentStatus": ["future", "now"], "group": [2, 16], "groupAndOr": "OR" }
```

Returns rows with `id`, `name`, `first_name`, `last_name_prefix`, `last_name`,
`email`, `phone`, `mobilePhone`, `address`, `postalCode`, `city`, `country`,
`archived`.

Calling this endpoint with plain query parameters (`?employment=now&...`, the form
the browser URL uses) answers **HTTP 500**. It only accepts the JSON filter.

## `GET /api/report/schedule/registrations?shift_id=…&start_date=…&end_date=…`

Who signed up for which shift, over a date range. Unlike the contact report, this
one takes **plain query parameters**, with `shift_id` repeated once per shift:

```
?shift_id=14&shift_id=6&shift_id=4&start_date=2026-07-10&end_date=2026-09-10
```

`start_date` and `end_date` are required; leaving them out returns HTTP 400 with
a field-by-field error. Rows look like:

```jsonc
{
  "id": 2780,
  "date": "2026-07-11",
  "shiftcode": "VM",          // the code, not the shift id
  "shift": "Shop afternoon",
  "employeeId": 31,
  "employeeName": "…",
  "employeeFirstName": "…",
  "employeeLastNamePrefix": "",
  "employeeLastName": "…",
  "shiftStartTime": "14:00:00",
  "shiftEndTime": "17:00:00",
  "shiftDuration": 3.0
}
```

The rows carry a shift **code** but no shift id, so `server.py` adds the id back
by looking the code up in the week schedule.

## The `/api/v2/` layer

`GET /api/schedule/` lists a second, cleaner set of endpoints:

| Path | Contents |
| --- | --- |
| `/api/v2/schedule/shift` | All shift types: `id`, `code`, `description`, times, `shift_group` |
| `/api/v2/schedule/shift-group` | Shift groups: `id`, `name`, `color`, `order` |
| `/api/v2/schedule/shift-employee-group` | Which volunteer group may work which shift or shift group |
| `/api/v2/schedule/shift-capacity` | Capacity per weekday, per shift, over a date range |

`live.py` exposes `shifts()` and `shift_group_links()` for these. The tools do not
need them today, because the week schedule already carries the same information,
but they are useful if you extend the server: `shift-capacity` in particular gives
the planned capacity pattern without reading week after week.

## Other write endpoints this project does not use

The web app also calls endpoints for creating and changing registrations, absences,
employees and shifts. They are deliberately absent from this codebase, so no tool
can reach them.

## Finding more endpoints

The web app is the reference. Open Pinkbee in a browser with the developer tools
network tab, do the thing you want to automate, and note which `/api/` URL it
calls. You can also read the paths straight out of the front-end bundle: the
`<script type="module" src="/assets/pinkbee/main-*.js">` in any page contains
every route as a plain string.

When you add one, put the URL in `live.py`, give `mock.py` a matching method so
tests and mock mode keep working, and only then write a tool for it.

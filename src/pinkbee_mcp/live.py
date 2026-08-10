"""Talks to a real Pinkbee instance.

Pinkbee is a Django website. There is no API key: you log in with a username and
password, and Pinkbee gives you a session cookie that you send with every later
request.

Everything here is a GET, except the one login POST. Nothing in this file can
change data in Pinkbee.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import time
import urllib.parse

import httpx

log = logging.getLogger("pinkbee_mcp.live")

LOGIN_PATH = "/accounts/login/"

# Pinkbee hides a CSRF token in the login form. We need to send it back.
CSRF_PATTERN = re.compile(
    r"name=['\"]csrfmiddlewaretoken['\"][^>]*value=['\"]([^'\"]+)", re.IGNORECASE
)
PASSWORD_PATTERN = re.compile(r"type=['\"]?password", re.IGNORECASE)


class PinkbeeError(Exception):
    """Something went wrong while talking to Pinkbee."""


class LivePinkbee:
    """Reads data from a real Pinkbee instance."""

    def __init__(self, base_url: str, login: str, password: str, timeout: int = 20,
                 client: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.login_name = login
        self.password = password
        self.logged_in = False
        # Counts successful logins. Used to tell "my session went stale" apart
        # from "another request already replaced the session while I waited".
        self.session_number = 0
        self.login_lock = asyncio.Lock()
        self.http = client or httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "pinkbee-mcp/0.2"},
        )

    def describe(self) -> str:
        return f"live Pinkbee at {self.base_url} (as {self.login_name})"

    async def close(self) -> None:
        await self.http.aclose()

    # --- logging in ------------------------------------------------------

    async def ensure_logged_in(self, after_session: int | None = None) -> None:
        """Make sure we have a working session, logging in at most once at a time.

        The lock matters because several tool calls can arrive at the same moment.
        Without it, each one would see "not logged in yet" and start its own login.

        Pass `after_session` (the session number you were using) when a request
        came back logged out. If another request already logged in since then,
        this does nothing and you can simply retry.
        """
        async with self.login_lock:
            if self.logged_in and after_session != self.session_number:
                log.debug("session %s is already fresh, no login needed", self.session_number)
                return
            await self.log_in()

    async def log_in(self) -> None:
        """Get a session cookie from Pinkbee. Always performs the login.

        Prefer `ensure_logged_in()`, which skips the work when it is not needed.
        """
        started = time.perf_counter()
        log.info("logging in to %s as %s", self.base_url, self.login_name)

        page = await self.http.get(LOGIN_PATH)
        log.debug("GET %s -> %s", LOGIN_PATH, page.status_code)
        match = CSRF_PATTERN.search(page.text)
        if not match:
            raise PinkbeeError(
                f"Could not find the CSRF token on {LOGIN_PATH}. "
                "Check that PINKBEE_BASE_URL points at a Pinkbee site."
            )

        answer = await self.http.post(
            LOGIN_PATH,
            data={
                "csrfmiddlewaretoken": html.unescape(match.group(1)),
                "next": "/",
                "login": self.login_name,
                "password": self.password,
            },
            headers={"Referer": f"{self.base_url}{LOGIN_PATH}"},
        )
        log.debug("POST %s -> %s", LOGIN_PATH, answer.status_code)
        if shows_login_form(answer.text):
            log.warning("login refused by %s for %s", self.base_url, self.login_name)
            raise PinkbeeError(
                "Pinkbee did not accept the login. Check PINKBEE_LOGIN and PINKBEE_PASSWORD."
            )
        self.logged_in = True
        self.session_number += 1
        log.info(
            "logged in, session %s ready (took %.0fms)",
            self.session_number,
            (time.perf_counter() - started) * 1000,
        )

    # --- reading data ----------------------------------------------------

    async def get_json(self, path: str):
        """GET one Pinkbee URL and return the parsed JSON.

        Logs in first if needed, and logs in again once if the session expired.
        """
        await self.ensure_logged_in()
        session = self.session_number

        answer = await self.timed_get(path)
        if answer.status_code in (401, 403) or shows_login_form(answer.text):
            # The session went stale. Get a new one and try this read once more.
            log.info("session %s looks logged out on %s, logging in again", session, path)
            await self.ensure_logged_in(after_session=session)
            answer = await self.timed_get(path)
            if shows_login_form(answer.text):
                # Logging in worked, yet Pinkbee still shows the login form. Say so
                # plainly instead of blaming the path further down.
                raise PinkbeeError(
                    f"Pinkbee keeps asking us to log in when reading {path}. "
                    "The account may lack permission for this data, or the session "
                    "is being dropped immediately."
                )

        if answer.status_code >= 400:
            raise PinkbeeError(f"Pinkbee answered HTTP {answer.status_code} for {path}")

        content_type = answer.headers.get("content-type", "")
        if "json" not in content_type:
            # Pinkbee serves its web app for unknown paths, so HTML here means
            # "this URL does not exist".
            raise PinkbeeError(
                f"Pinkbee did not return JSON for {path} (got {content_type!r}). "
                "The path is probably wrong."
            )
        try:
            payload = answer.json()
        except (json.JSONDecodeError, ValueError):
            raise PinkbeeError(f"Pinkbee returned broken JSON for {path}") from None

        # Log the shape, never the content: these payloads hold names and addresses.
        log.debug(
            "%s returned a %s of %s",
            path,
            type(payload).__name__,
            len(payload) if hasattr(payload, "__len__") else "?",
        )
        return payload

    async def timed_get(self, path: str) -> httpx.Response:
        """GET one URL and log how it went. Never logs the body."""
        started = time.perf_counter()
        answer = await self.http.get(path)
        log.debug(
            "GET %s -> %s %s, %s bytes in %.0fms",
            path,
            answer.status_code,
            answer.headers.get("content-type", "?").split(";")[0],
            len(answer.content),
            (time.perf_counter() - started) * 1000,
        )
        return answer

    async def week_schedule(self, monday: str) -> list:
        """All shifts and registrations for the week starting on `monday`."""
        return await self.get_json(f"/api/schedule/week/{monday}")

    async def groups(self) -> list:
        """All volunteer groups, with their id and name."""
        return await self.get_json("/api/group/")

    async def shifts(self) -> list:
        """All shift types, with the shift group they belong to."""
        return await self.get_json("/api/v2/schedule/shift")

    async def shift_group_links(self) -> list:
        """Which volunteer group may register for which shift or shift group."""
        return await self.get_json("/api/v2/schedule/shift-employee-group")

    async def contacts(self, group_ids: list[int], employment: list[str]) -> list:
        """Contact rows for the volunteers in the given groups."""
        # This report wants its filter as JSON inside the query string.
        report_filter = json.dumps(
            {"employmentStatus": employment, "group": group_ids, "groupAndOr": "OR"}
        )
        return await self.get_json(
            "/api/report/employees/contact?filter=" + urllib.parse.quote(report_filter)
        )

    async def registrations(self, shift_ids: list[int], start_date: str, end_date: str) -> list:
        """Who is signed up for which shift, between two dates."""
        # This report wants plain query parameters, one shift_id per shift.
        query = [("shift_id", str(shift_id)) for shift_id in shift_ids]
        query += [("start_date", start_date), ("end_date", end_date)]
        return await self.get_json(
            "/api/report/schedule/registrations?" + urllib.parse.urlencode(query)
        )


def shows_login_form(page_text: str) -> bool:
    """True if this page is the login form.

    Checked by looking at the page itself, not the URL: Django answers a failed
    login with HTTP 200 on the same URL, and a successful one with a redirect.
    """
    if "csrfmiddlewaretoken" not in page_text:
        return False
    return PASSWORD_PATTERN.search(page_text) is not None

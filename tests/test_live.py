"""Tests for the live Pinkbee client, using a fake HTTP layer.

Nothing here touches a real Pinkbee instance.
"""

import asyncio

import httpx
import pytest

from pinkbee_mcp.live import LivePinkbee, PinkbeeError, shows_login_form

BASE = "https://example.test"
LOGIN_PAGE = (
    '<form method="post">'
    '<input type="hidden" name="csrfmiddlewaretoken" value="token&amp;123">'
    '<input type="password" name="password">'
    "</form>"
)
DASHBOARD = "<h1>Welcome</h1>"


def build(handler):
    """A LivePinkbee whose HTTP calls go to `handler` instead of the network."""
    fake_http = httpx.AsyncClient(
        base_url=BASE, transport=httpx.MockTransport(handler), follow_redirects=True
    )
    return LivePinkbee(BASE, "someone@example.org", "secret", client=fake_http)


def login_then(json_answer, status=200, content_type="application/json"):
    """A handler that serves the login flow, then one JSON answer."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/accounts/login/":
            if request.method == "GET":
                return httpx.Response(200, text=LOGIN_PAGE)
            return httpx.Response(200, text=DASHBOARD)
        if content_type == "application/json":
            return httpx.Response(status, json=json_answer)
        return httpx.Response(status, text="<html></html>", headers={"content-type": content_type})

    return handler


def test_shows_login_form_recognises_the_form():
    assert shows_login_form(LOGIN_PAGE) is True


def test_shows_login_form_ignores_a_normal_page():
    assert shows_login_form(DASHBOARD) is False


def test_shows_login_form_ignores_a_page_with_only_a_csrf_token():
    """A dashboard can carry a CSRF token for its own forms; that is not a login."""
    assert shows_login_form('<input name="csrfmiddlewaretoken" value="x">') is False


async def test_login_sends_the_unescaped_csrf_token_and_the_credentials():
    sent = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=LOGIN_PAGE)
        sent["body"] = request.content.decode()
        return httpx.Response(200, text=DASHBOARD)

    await build(handler).log_in()
    assert "csrfmiddlewaretoken=token%26123" in sent["body"]
    assert "login=someone%40example.org" in sent["body"]
    assert "password=secret" in sent["body"]


async def test_login_explains_a_missing_csrf_token():
    client = build(lambda request: httpx.Response(200, text="<p>not pinkbee</p>"))
    with pytest.raises(PinkbeeError, match="CSRF token"):
        await client.log_in()


async def test_login_explains_wrong_credentials():
    """Django answers a failed login with the form again, on HTTP 200."""
    client = build(lambda request: httpx.Response(200, text=LOGIN_PAGE))
    with pytest.raises(PinkbeeError, match="did not accept the login"):
        await client.log_in()


async def test_get_json_logs_in_first():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/accounts/login/":
            return httpx.Response(200, text=LOGIN_PAGE if request.method == "GET" else DASHBOARD)
        return httpx.Response(200, json=[{"id": 1}])

    result = await build(handler).get_json("/api/group/")
    assert result == [{"id": 1}]
    assert calls[:2] == [("GET", "/accounts/login/"), ("POST", "/accounts/login/")]


async def test_get_json_logs_in_only_once_for_several_reads():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.url.path == "/accounts/login/":
            return httpx.Response(200, text=LOGIN_PAGE if request.method == "GET" else DASHBOARD)
        return httpx.Response(200, json=[])

    client = build(handler)
    await client.get_json("/api/group/")
    await client.get_json("/api/schedule/week/2026-08-10")
    assert calls.count("POST") == 1


async def test_get_json_logs_in_again_when_the_session_expired():
    state = {"reads": 0, "logins": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/accounts/login/":
            if request.method == "GET":
                return httpx.Response(200, text=LOGIN_PAGE)
            state["logins"] += 1
            return httpx.Response(200, text=DASHBOARD)
        state["reads"] += 1
        if state["reads"] == 1:
            return httpx.Response(403, json={"detail": "expired"})
        return httpx.Response(200, json={"ok": True})

    assert await build(handler).get_json("/api/group/") == {"ok": True}
    assert state["logins"] == 2


async def test_get_json_explains_an_error_status():
    client = build(login_then(None, status=500))
    with pytest.raises(PinkbeeError, match="HTTP 500"):
        await client.get_json("/api/group/")


async def test_get_json_explains_a_wrong_path():
    """Pinkbee serves its web app for unknown paths, so HTML means 'no such URL'."""
    client = build(login_then(None, content_type="text/html; charset=utf-8"))
    with pytest.raises(PinkbeeError, match="did not return JSON"):
        await client.get_json("/api/does-not-exist")


async def test_only_the_login_uses_post():
    methods = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append((request.method, request.url.path))
        if request.url.path == "/accounts/login/":
            return httpx.Response(200, text=LOGIN_PAGE if request.method == "GET" else DASHBOARD)
        return httpx.Response(200, json=[])

    client = build(handler)
    await client.week_schedule("2026-08-10")
    await client.groups()
    await client.shifts()
    await client.shift_group_links()
    await client.contacts([2], ["now"])
    await client.registrations([3], "2026-08-01", "2026-08-31")

    posts = [call for call in methods if call[0] == "POST"]
    assert posts == [("POST", "/accounts/login/")]


async def test_each_read_uses_the_expected_url():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/accounts/login/":
            return httpx.Response(200, text=LOGIN_PAGE if request.method == "GET" else DASHBOARD)
        seen.append(str(request.url).replace(BASE, ""))
        return httpx.Response(200, json=[])

    client = build(handler)
    await client.week_schedule("2026-08-10")
    await client.groups()
    await client.shifts()
    await client.shift_group_links()
    assert seen == [
        "/api/schedule/week/2026-08-10",
        "/api/group/",
        "/api/v2/schedule/shift",
        "/api/v2/schedule/shift-employee-group",
    ]


async def test_contacts_send_the_filter_as_json():
    import json

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/accounts/login/":
            return httpx.Response(200, text=LOGIN_PAGE if request.method == "GET" else DASHBOARD)
        seen["filter"] = request.url.params.get("filter")
        return httpx.Response(200, json=[])

    await build(handler).contacts([2, 16], ["future", "now"])
    assert json.loads(seen["filter"]) == {
        "employmentStatus": ["future", "now"],
        "group": [2, 16],
        "groupAndOr": "OR",
    }


async def test_registrations_repeat_the_shift_id_parameter():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/accounts/login/":
            return httpx.Response(200, text=LOGIN_PAGE if request.method == "GET" else DASHBOARD)
        seen["query"] = str(request.url.query.decode())
        return httpx.Response(200, json=[])

    await build(handler).registrations([14, 6, 4], "2026-07-10", "2026-09-10")
    assert seen["query"] == (
        "shift_id=14&shift_id=6&shift_id=4&start_date=2026-07-10&end_date=2026-09-10"
    )


async def test_describe_mentions_the_base_url_but_not_the_password():
    text = build(login_then([])).describe()
    assert BASE in text
    assert "secret" not in text


async def test_several_reads_share_one_login():
    """The session cookie is reused; a read does not log in again."""
    logins = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/accounts/login/":
            if request.method == "GET":
                return httpx.Response(200, text=LOGIN_PAGE)
            logins["n"] += 1
            return httpx.Response(200, text=DASHBOARD)
        return httpx.Response(200, json=[])

    client = build(handler)
    for _ in range(5):
        await client.get_json("/api/group/")
    assert logins["n"] == 1


async def test_requests_arriving_together_log_in_only_once():
    """Without the lock, every waiting request would start its own login."""
    logins = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/accounts/login/":
            if request.method == "GET":
                return httpx.Response(200, text=LOGIN_PAGE)
            logins["n"] += 1
            await asyncio.sleep(0.02)  # logging in takes a moment
            return httpx.Response(200, text=DASHBOARD)
        return httpx.Response(200, json=[])

    client = build(handler)
    await asyncio.gather(*(client.get_json(f"/api/group/?{i}") for i in range(6)))
    assert logins["n"] == 1


async def test_requests_that_expire_together_log_in_only_once():
    logins = {"n": 0}
    expired = {"yes": False}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/accounts/login/":
            if request.method == "GET":
                return httpx.Response(200, text=LOGIN_PAGE)
            logins["n"] += 1
            await asyncio.sleep(0.02)
            expired["yes"] = False
            return httpx.Response(200, text=DASHBOARD)
        if expired["yes"]:
            return httpx.Response(200, text=LOGIN_PAGE)
        return httpx.Response(200, json=[])

    client = build(handler)
    await client.ensure_logged_in()
    logins["n"] = 0
    expired["yes"] = True

    await asyncio.gather(*(client.get_json(f"/api/group/?{i}") for i in range(6)))
    assert logins["n"] == 1


async def test_ensure_logged_in_does_nothing_when_the_session_is_fresh():
    logins = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            logins["n"] += 1
            return httpx.Response(200, text=DASHBOARD)
        return httpx.Response(200, text=LOGIN_PAGE)

    client = build(handler)
    await client.ensure_logged_in()
    await client.ensure_logged_in()
    await client.ensure_logged_in()
    assert logins["n"] == 1


async def test_a_read_is_retried_only_once():
    """Two reads at most: the original and one after logging in again."""
    reads = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/accounts/login/":
            return httpx.Response(200, text=LOGIN_PAGE if request.method == "GET" else DASHBOARD)
        reads["n"] += 1
        return httpx.Response(200, text=LOGIN_PAGE)  # never logged in, as far as it is concerned

    client = build(handler)
    with pytest.raises(PinkbeeError, match="keeps asking us to log in"):
        await client.get_json("/api/group/")
    assert reads["n"] == 2


async def test_the_session_number_increases_on_each_login():
    client = build(login_then([]))
    assert client.session_number == 0
    await client.log_in()
    assert client.session_number == 1
    await client.log_in()
    assert client.session_number == 2

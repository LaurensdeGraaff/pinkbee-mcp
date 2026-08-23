"""Tests for HTTP sender filtering and bearer authentication."""

import socket

import pytest

from pinkbee_mcp.__main__ import (
    allow_senders,
    disable_calls,
    reject_browser_requests,
    require_token,
)

# --- bearer auth ----------------------------------------------------------


class Recorder:
    """Collects what an ASGI app sent back."""

    def __init__(self):
        self.messages = []

    async def __call__(self, message):
        self.messages.append(message)

    @property
    def status(self):
        return next(m["status"] for m in self.messages if m["type"] == "http.response.start")

    @property
    def headers(self):
        start = next(m for m in self.messages if m["type"] == "http.response.start")
        return {key.decode().lower(): value.decode() for key, value in start["headers"]}

    @property
    def body(self):
        return b"".join(m.get("body", b"") for m in self.messages if m["type"] == "http.response.body")


async def call(app, headers: dict[str, str], sender: str = "192.168.1.42"):
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (sender, 54321),
    }
    recorder = Recorder()

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    await app(scope, receive, recorder)
    return recorder


async def reached(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"reached"})


# --- sender filtering -----------------------------------------------------


@pytest.mark.asyncio
async def test_every_sender_is_allowed_by_default():
    answer = await call(allow_senders(reached, ()), {}, sender="203.0.113.10")
    assert answer.status == 200


@pytest.mark.asyncio
async def test_an_allowed_sender_ip_gets_through():
    answer = await call(allow_senders(reached, ("192.168.1.42",)), {})
    assert answer.status == 200


@pytest.mark.asyncio
async def test_a_different_sender_ip_is_forbidden():
    answer = await call(
        allow_senders(reached, ("192.168.1.50",)),
        {},
        sender="192.168.1.42",
    )
    assert answer.status == 403
    assert b"sender IP" in answer.body


@pytest.mark.asyncio
async def test_a_sender_domain_is_resolved_to_its_ip(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.42", 0))
        ],
    )
    answer = await call(allow_senders(reached, ("agent.example.com",)), {})
    assert answer.status == 200


@pytest.mark.asyncio
async def test_browser_origin_requests_are_forbidden():
    answer = await call(
        reject_browser_requests(reached),
        {"origin": "https://malicious.example"},
    )
    assert answer.status == 403


@pytest.mark.asyncio
async def test_normal_mcp_request_without_origin_gets_through():
    answer = await call(reject_browser_requests(reached), {})
    assert answer.status == 200


def test_disabled_calls_are_removed_individually():
    class Server:
        def __init__(self):
            self.removed = []

        def remove_tool(self, name):
            self.removed.append(name)

    server = Server()
    disable_calls(server, ("pinkbee_list_group_emails", "pinkbee_list_registrations"))
    assert server.removed == ["pinkbee_list_group_emails", "pinkbee_list_registrations"]


@pytest.mark.asyncio
async def test_a_missing_token_gives_401_with_a_challenge():
    answer = await call(require_token(reached, "secret"), {})
    assert answer.status == 401
    assert answer.headers["www-authenticate"] == 'Bearer realm="pinkbee-mcp"'


@pytest.mark.asyncio
async def test_a_wrong_token_gives_401():
    answer = await call(require_token(reached, "secret"), {"authorization": "Bearer nope"})
    assert answer.status == 401
    assert b"reached" not in answer.body


@pytest.mark.asyncio
async def test_the_right_token_gets_through():
    answer = await call(require_token(reached, "secret"), {"authorization": "Bearer secret"})
    assert answer.status == 200
    assert answer.body == b"reached"

"""Tests for the HTTP transport: Origin/Host protection and bearer auth."""

import pytest
from mcp.server.transport_security import TransportSecuritySettings

from pinkbee_mcp.__main__ import require_token, transport_security
from pinkbee_mcp.config import Config


def settings(**kwargs) -> TransportSecuritySettings:
    return transport_security(Config(**kwargs))


def test_dns_rebinding_protection_is_on():
    assert settings().enable_dns_rebinding_protection is True


def test_loopback_is_allowed_out_of_the_box():
    allowed = settings()
    assert "127.0.0.1" in allowed.allowed_hosts
    assert "localhost" in allowed.allowed_hosts
    assert "http://localhost" in allowed.allowed_origins


def test_any_loopback_port_is_allowed():
    """Docker publishes the container's port on a different host port."""
    allowed = settings()
    assert "127.0.0.1:*" in allowed.allowed_hosts
    assert "localhost:*" in allowed.allowed_hosts
    assert "http://127.0.0.1:*" in allowed.allowed_origins
    assert "https://localhost:*" in allowed.allowed_origins


def test_a_foreign_origin_is_not_allowed():
    allowed = settings()
    assert "https://evil.example" not in allowed.allowed_origins
    assert "evil.example" not in allowed.allowed_hosts


def test_extra_origins_and_hosts_come_from_the_environment():
    allowed = settings(
        allowed_origins=("https://roster.example.org",),
        allowed_hosts=("roster.example.org",),
    )
    assert "https://roster.example.org" in allowed.allowed_origins
    assert "roster.example.org" in allowed.allowed_hosts
    # and loopback still works
    assert "localhost:*" in allowed.allowed_hosts


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


async def call(app, headers: dict[str, str]):
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }
    recorder = Recorder()

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    await app(scope, receive, recorder)
    return recorder


async def reached(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"reached"})


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

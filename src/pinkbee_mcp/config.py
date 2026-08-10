"""Reads the settings from environment variables.

Everything the server needs comes from the environment, so no secret is ever
stored in the code or in the Docker image.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MOCK = "mock"
LIVE = "live"


class ConfigError(Exception):
    """The environment is missing something, or a value is not valid."""


def read_text(name: str, default: str = "") -> str:
    """Read an environment variable as text."""
    return os.environ.get(name, default).strip()


def read_flag(name: str, default: bool = False) -> bool:
    """Read an environment variable as a true/false flag."""
    value = read_text(name)
    if not value:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def read_number(name: str, default: int) -> int:
    """Read an environment variable as a whole number."""
    value = read_text(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number, got {value!r}") from None


@dataclass(frozen=True)
class Config:
    """All settings for one running server."""

    # Where the data comes from: "mock" (built-in sample data) or "live".
    data_source: str = MOCK

    # Only needed when data_source is "live".
    base_url: str = ""
    login: str = ""
    password: str = ""

    # Tools that return names or email addresses are off until this is on.
    allow_personal_data: bool = False

    # "Today" follows this timezone, not the container's UTC clock.
    timezone: str = "Europe/Amsterdam"

    # How the MCP server is reachable.
    transport: str = "streamable-http"
    host: str = "0.0.0.0"
    port: int = 8080
    path: str = "/mcp"
    token: str = ""

    timeout_seconds: int = 20

    def __repr__(self) -> str:
        """Never show the password or the token, not even in a stack trace."""
        return (
            f"Config(data_source={self.data_source!r}, base_url={self.base_url!r}, "
            f"login={self.login!r}, allow_personal_data={self.allow_personal_data}, "
            f"timezone={self.timezone!r}, transport={self.transport!r}, port={self.port})"
        )

    @property
    def is_live(self) -> bool:
        return self.data_source == LIVE


def load_config() -> Config:
    """Build a Config from the environment, or explain what is missing."""
    data_source = read_text("PINKBEE_DATA_SOURCE", MOCK).lower() or MOCK
    if data_source not in {MOCK, LIVE}:
        raise ConfigError(f"PINKBEE_DATA_SOURCE must be '{MOCK}' or '{LIVE}', got {data_source!r}")

    base_url = read_text("PINKBEE_BASE_URL").rstrip("/")
    login = read_text("PINKBEE_LOGIN")
    password = os.environ.get("PINKBEE_PASSWORD", "")

    # Mock mode must work with no credentials at all: that is what makes the
    # default safe. Live mode needs all three.
    if data_source == LIVE:
        missing = [
            name
            for name, value in [
                ("PINKBEE_BASE_URL", base_url),
                ("PINKBEE_LOGIN", login),
                ("PINKBEE_PASSWORD", password),
            ]
            if not value
        ]
        if missing:
            raise ConfigError(
                "PINKBEE_DATA_SOURCE=live needs: " + ", ".join(missing) + ". See .env.example."
            )
        if not base_url.startswith(("http://", "https://")):
            raise ConfigError("PINKBEE_BASE_URL must start with http:// or https://")

    timezone = read_text("PINKBEE_TIMEZONE", "Europe/Amsterdam") or "Europe/Amsterdam"
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError(f"PINKBEE_TIMEZONE {timezone!r} is not a known timezone name") from None

    transport = read_text("PINKBEE_MCP_TRANSPORT", "streamable-http").lower() or "streamable-http"
    if transport not in {"streamable-http", "stdio"}:
        raise ConfigError("PINKBEE_MCP_TRANSPORT must be 'streamable-http' or 'stdio'")

    return Config(
        data_source=data_source,
        base_url=base_url,
        login=login,
        password=password,
        allow_personal_data=read_flag("PINKBEE_ALLOW_PERSONAL_DATA", False),
        timezone=timezone,
        transport=transport,
        host=read_text("PINKBEE_MCP_HOST", "0.0.0.0") or "0.0.0.0",
        port=read_number("PINKBEE_MCP_PORT", 8080),
        path=read_text("PINKBEE_MCP_PATH", "/mcp") or "/mcp",
        token=read_text("PINKBEE_MCP_TOKEN"),
        timeout_seconds=read_number("PINKBEE_TIMEOUT_SECONDS", 20),
    )

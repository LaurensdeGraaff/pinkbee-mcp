"""Reads the settings from environment variables.

Everything the server needs comes from the environment, so no secret is ever
stored in the code or in the Docker image.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MOCK = "mock"
LIVE = "live"

#: Host names that count as "this machine" for the plain-HTTP opt-in and for the
#: default Origin/Host allowlist.
LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1", "[::1]")


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


def read_list(name: str) -> list[str]:
    """Read a comma-separated environment variable into a list."""
    return [item.strip() for item in read_text(name).split(",") if item.strip()]


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

    # Plain HTTP to Pinkbee would put the password on the wire in clear text, so it
    # is refused unless this is on AND the host is this machine.
    allow_insecure_http_to_localhost: bool = False

    # Upper bounds on what one tool call may ask for. They keep a single call from
    # exporting a year of personal data or producing an answer too large to read.
    max_registration_days: int = 120
    max_ids_per_filter: int = 50
    max_dates: int = 12
    max_weeks: int = 12

    # "Today" follows this timezone, not the container's UTC clock.
    timezone: str = "Europe/Amsterdam"

    # How the MCP server is reachable.
    transport: str = "streamable-http"
    host: str = "0.0.0.0"
    port: int = 8080
    path: str = "/mcp"
    token: str = ""

    # Origin and Host values the HTTP transport accepts, on top of loopback. Needed
    # when a reverse proxy fronts the server under its own name.
    allowed_origins: tuple[str, ...] = field(default_factory=tuple)
    allowed_hosts: tuple[str, ...] = field(default_factory=tuple)

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

    allow_insecure = read_flag("PINKBEE_ALLOW_INSECURE_HTTP_TO_LOCALHOST", False)

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
        check_base_url_is_safe(base_url, allow_insecure)

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
        allow_insecure_http_to_localhost=allow_insecure,
        max_registration_days=positive("PINKBEE_MAX_REGISTRATION_DAYS", 120),
        max_ids_per_filter=positive("PINKBEE_MAX_IDS_PER_FILTER", 50),
        max_dates=positive("PINKBEE_MAX_DATES", 12),
        max_weeks=positive("PINKBEE_MAX_WEEKS", 12),
        timezone=timezone,
        transport=transport,
        host=read_text("PINKBEE_MCP_HOST", "0.0.0.0") or "0.0.0.0",
        port=read_number("PINKBEE_MCP_PORT", 8080),
        path=read_text("PINKBEE_MCP_PATH", "/mcp") or "/mcp",
        token=read_text("PINKBEE_MCP_TOKEN"),
        allowed_origins=tuple(read_list("PINKBEE_ALLOWED_ORIGINS")),
        allowed_hosts=tuple(read_list("PINKBEE_ALLOWED_HOSTS")),
        timeout_seconds=read_number("PINKBEE_TIMEOUT_SECONDS", 20),
    )


def positive(name: str, default: int) -> int:
    """A limit that has to be at least 1."""
    value = read_number(name, default)
    if value < 1:
        raise ConfigError(f"{name} must be 1 or more, got {value}")
    return value


def is_loopback(host: str) -> bool:
    return host.split(":")[0].lower() in LOOPBACK_HOSTS or host.lower() in LOOPBACK_HOSTS


def check_base_url_is_safe(base_url: str, allow_insecure: bool) -> None:
    """Refuse to send Pinkbee credentials over plain HTTP.

    Logging in POSTs the username and password as a form, so http:// would put them
    on the wire in clear text. Plain HTTP is allowed only against this machine, and
    only when the operator has explicitly asked for it, which is what a local test
    Pinkbee needs.
    """
    parsed = urlparse(base_url)
    if parsed.scheme == "https":
        return
    if parsed.scheme != "http":
        raise ConfigError("PINKBEE_BASE_URL must start with https:// (or http:// for localhost)")

    host = parsed.hostname or ""
    if not is_loopback(host):
        raise ConfigError(
            f"PINKBEE_BASE_URL uses plain http:// for {host!r}. Logging in sends your "
            "Pinkbee password, so https:// is required for anything but this machine."
        )
    if not allow_insecure:
        raise ConfigError(
            "PINKBEE_BASE_URL uses plain http:// for localhost. That sends your Pinkbee "
            "password unencrypted; set PINKBEE_ALLOW_INSECURE_HTTP_TO_LOCALHOST=true if "
            "that is really what you want (a local test instance, for example)."
        )

"""Starts the server: `python -m pinkbee_mcp`.

Two ways to run it:

- streamable-http (the default, and what the Docker container uses): serves the
  MCP endpoint over HTTP, optionally behind a bearer token.
- stdio: for a desktop MCP client running on the same machine.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
import sys

from mcp.server.transport_security import TransportSecuritySettings

from .config import LOOPBACK_HOSTS, Config, ConfigError, load_config
from .logs import setup_logging
from .server import allowed_arguments, mcp, setup, strict_arguments

log = logging.getLogger("pinkbee_mcp")


def require_token(app, token: str):
    """Wrap the web app so every request must send the right bearer token.

    This is deliberately simple: one shared token for a private deployment. It is not
    MCP's OAuth authorization, so there is no protected-resource metadata to point a
    client at. The `WWW-Authenticate` header at least tells a client *how* to
    authenticate, as HTTP requires of a 401.
    """
    from starlette.responses import JSONResponse

    expected = f"Bearer {token}"
    challenge = {"WWW-Authenticate": 'Bearer realm="pinkbee-mcp"'}

    async def check(scope, receive, send):
        if scope["type"] == "http":
            headers = {key.decode().lower(): value.decode() for key, value in scope["headers"]}
            if not hmac.compare_digest(headers.get("authorization", ""), expected):
                answer = JSONResponse(
                    {"error": "unauthorized", "error_description": "a bearer token is required"},
                    status_code=401,
                    headers=challenge,
                )
                await answer(scope, receive, send)
                return
        await app(scope, receive, send)

    return check


def transport_security(config: Config) -> TransportSecuritySettings:
    """Which Origin and Host values the HTTP transport accepts.

    A browser page on any site can POST to a localhost port. Without this check, such
    a page could drive this server and read a whole roster: the DNS-rebinding attack
    the MCP transport spec requires servers to block. An unknown Host is answered
    with 421 and an unknown Origin with 403.

    Loopback is allowed out of the box, with any port. The port has to be a wildcard
    because Docker publishes the container's 8080 on whatever host port you choose,
    and the Host header carries the port the *client* used. Any port on loopback is
    still loopback, so this gives nothing away.

    A reverse proxy fronting the server under its own name adds it through
    PINKBEE_ALLOWED_HOSTS and PINKBEE_ALLOWED_ORIGINS.
    """
    hosts = [pattern for base in LOOPBACK_HOSTS for pattern in (base, f"{base}:*")]
    origins = [
        f"{scheme}://{base}{suffix}"
        for scheme in ("http", "https")
        for base in LOOPBACK_HOSTS
        for suffix in ("", ":*")
    ]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts + list(config.allowed_hosts),
        allowed_origins=origins + list(config.allowed_origins),
    )


def main() -> int:
    # Read the log level straight from the environment: it has to work even when
    # the configuration below turns out to be broken.
    setup_logging(os.environ.get("PINKBEE_LOG_LEVEL", "INFO"))
    try:
        config = load_config()
    except ConfigError as problem:
        print(f"Configuration error: {problem}", file=sys.stderr)
        return 2

    setup(config)
    # Tell the strict-argument check what each tool actually accepts.
    strict_arguments.allowed_arguments = asyncio.run(allowed_arguments())

    if config.data_source == "live":
        log.warning("Reading from a live Pinkbee instance. All requests are read-only.")

    if config.transport == "stdio":
        mcp.run(transport="stdio")
        return 0

    security = transport_security(config)
    log.info(
        "accepting Host %s and Origin %s",
        ", ".join(security.allowed_hosts),
        ", ".join(security.allowed_origins),
    )

    app = mcp.streamable_http_app(
        streamable_http_path=config.path,
        stateless_http=True,
        host=config.host,
        transport_security=security,
    )
    if config.token:
        app = require_token(app, config.token)
    else:
        log.warning(
            "PINKBEE_MCP_TOKEN is not set, so anyone who can reach the port can use "
            "this server. Only do this on a trusted network."
        )

    import uvicorn

    uvicorn.run(app, host=config.host, port=config.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

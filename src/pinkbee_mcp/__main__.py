"""Starts the server: `python -m pinkbee_mcp`.

Serves the MCP endpoint over streamable HTTP, optionally behind a bearer token
and/or a sender-IP allowlist.
"""

from __future__ import annotations

import asyncio
import hmac
import ipaddress
import logging
import os
import socket
import sys

from mcp.server.transport_security import TransportSecuritySettings

from .config import ConfigError, load_config
from .logs import setup_logging
from .server import allowed_arguments, mcp, setup, strict_arguments

log = logging.getLogger("pinkbee_mcp")

HTTP_HOST = "0.0.0.0"
HTTP_PORT = 8080
HTTP_PATH = "/mcp"


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


def reject_browser_requests(app):
    """Reject browser-originated requests without adding a Host/Origin allowlist.

    Normal MCP clients do not send Origin. Rejecting every supplied Origin blocks a
    web page from driving a LAN MCP through DNS rebinding while keeping deployment
    independent of the destination hostname used by non-browser clients.
    """
    from starlette.responses import JSONResponse

    async def check(scope, receive, send):
        if scope["type"] == "http":
            headers = {key.decode().lower(): value.decode() for key, value in scope["headers"]}
            if headers.get("origin"):
                answer = JSONResponse(
                    {
                        "error": "forbidden",
                        "error_description": "browser Origin requests are not accepted",
                    },
                    status_code=403,
                )
                await answer(scope, receive, send)
                return
        await app(scope, receive, send)

    return check


def resolve_senders(entries: tuple[str, ...]) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve exact IP addresses and DNS names to the sender IPs they permit."""
    addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for entry in entries:
        try:
            addresses.add(ipaddress.ip_address(entry))
            continue
        except ValueError:
            pass
        try:
            answers = socket.getaddrinfo(entry, None, type=socket.SOCK_STREAM)
        except socket.gaierror as problem:
            raise ConfigError(
                f"PINKBEE_ALLOWED_SENDERS entry {entry!r} could not be resolved: {problem}"
            ) from problem
        addresses.update(ipaddress.ip_address(answer[4][0]) for answer in answers)
    return addresses


def allow_senders(app, entries: tuple[str, ...]):
    """Allow all senders by default, or only TCP peers selected by IP/DNS name."""
    if not entries:
        return app

    allowed = resolve_senders(entries)
    from starlette.responses import JSONResponse

    async def check(scope, receive, send):
        if scope["type"] == "http":
            client = scope.get("client")
            try:
                sender = ipaddress.ip_address(client[0])
            except (TypeError, ValueError):
                sender = None
            if sender not in allowed:
                answer = JSONResponse(
                    {
                        "error": "forbidden",
                        "error_description": "the sender IP is not in PINKBEE_ALLOWED_SENDERS",
                    },
                    status_code=403,
                )
                await answer(scope, receive, send)
                return
        await app(scope, receive, send)

    return check


def disable_calls(server, names: tuple[str, ...]) -> None:
    """Remove blacklisted calls so clients neither discover nor invoke them."""
    for name in names:
        server.remove_tool(name)
        log.info("disabled MCP call: %s", name)


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
    disable_calls(mcp, config.disabled_calls)
    # Tell the strict-argument check what each tool actually accepts.
    strict_arguments.allowed_arguments = asyncio.run(allowed_arguments())

    if config.data_source == "live":
        log.warning("Reading from a live Pinkbee instance. All requests are read-only.")

    app = mcp.streamable_http_app(
        streamable_http_path=HTTP_PATH,
        stateless_http=True,
        host=HTTP_HOST,
        # Sender access is enforced below. Destination Host/Origin configuration
        # made LAN and reverse-proxy deployments unnecessarily fragile.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    app = reject_browser_requests(app)
    if config.token:
        app = require_token(app, config.token)
    else:
        log.warning(
            "PINKBEE_MCP_TOKEN is not set, so anyone who can reach the port can use "
            "this server. Only do this on a trusted network."
        )
    try:
        app = allow_senders(app, config.allowed_senders)
    except ConfigError as problem:
        print(f"Configuration error: {problem}", file=sys.stderr)
        return 2
    if config.allowed_senders:
        log.info(
            "allowing sender IPs resolved from PINKBEE_ALLOWED_SENDERS: %s",
            ", ".join(config.allowed_senders),
        )
    else:
        log.info("allowing every sender that can reach the MCP port")

    import uvicorn

    uvicorn.run(app, host=HTTP_HOST, port=HTTP_PORT, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

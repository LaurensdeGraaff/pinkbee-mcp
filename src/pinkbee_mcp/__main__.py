"""Starts the server: `python -m pinkbee_mcp`.

Two ways to run it:

- streamable-http (the default, and what the Docker container uses): serves the
  MCP endpoint over HTTP, optionally behind a bearer token.
- stdio: for a desktop MCP client running on the same machine.
"""

from __future__ import annotations

import hmac
import logging
import os
import sys

from .config import ConfigError, load_config
from .logs import setup_logging
from .server import mcp, setup

log = logging.getLogger("pinkbee_mcp")


def require_token(app, token: str):
    """Wrap the web app so every request must send the right bearer token."""
    from starlette.responses import JSONResponse

    expected = f"Bearer {token}"

    async def check(scope, receive, send):
        if scope["type"] == "http":
            headers = {key.decode().lower(): value.decode() for key, value in scope["headers"]}
            if not hmac.compare_digest(headers.get("authorization", ""), expected):
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return
        await app(scope, receive, send)

    return check


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
    if config.data_source == "live":
        log.warning("Reading from a live Pinkbee instance. All requests are read-only.")

    if config.transport == "stdio":
        mcp.run(transport="stdio")
        return 0

    app = mcp.streamable_http_app(
        streamable_http_path=config.path,
        stateless_http=True,
        host=config.host,
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

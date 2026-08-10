"""Container health check: `python -m pinkbee_mcp.healthcheck`.

Checks one thing: is the server accepting connections on its port?

It deliberately does not send an HTTP request. A GET to the MCP endpoint opens a
server-sent-event stream and keeps it open, so it never finishes on its own, and a
POST would need the bearer token. Opening a TCP connection answers the only
question a health check should ask, and answers it immediately.

Whether Pinkbee itself is reachable is a different question: ask the
pinkbee_check_connection tool.
"""

from __future__ import annotations

import os
import socket
import sys


def main() -> int:
    host = "127.0.0.1"
    port = int(os.environ.get("PINKBEE_MCP_PORT", "8080"))
    try:
        with socket.create_connection((host, port), timeout=4):
            return 0
    except OSError as problem:
        print(f"unhealthy: cannot connect to {host}:{port}: {problem}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

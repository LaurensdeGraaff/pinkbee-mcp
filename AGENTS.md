# Repository agent guidance

- For MCP tools, Pinkbee API integration, transports, configuration, validation,
  tests, or deployment, automatically use the `mcp-development` skill.
- When a `.har`/HAR capture is supplied or browser-network behavior must be
  investigated, automatically use the `har-explorer` skill before implementing.
- For a new or changed Pinkbee endpoint, inspect HAR evidence when available,
  implement live and mock data-source methods, add appropriate tests, and update
  relevant documentation.
- Every Pinkbee write must be guarded by `ENABLE_WRITE_TO_PINKBEE` in both the MCP
  tool and live client. Do not make live writes unless explicitly requested.
- If live write testing is explicitly requested, save the original value, use a date
  at least two months in the future, undo the change, and verify restoration.
- Keep changes small, run appropriate checks, and report unavailable checks.

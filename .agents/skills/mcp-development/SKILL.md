---
name: mcp-development
description: Use when developing this Pinkbee MCP server: adding or changing MCP tools, Pinkbee API endpoints, resources, prompts, transports, validation, tests, or deployment. Automatically apply for MCP implementation requests in this repository.
---

# Pinkbee MCP Development

## Workflow
1. Inspect related source, tests, and documentation before editing.
2. For new Pinkbee endpoints, inspect supplied HAR/browser evidence when available;
   document the endpoint and payload instead of guessing.
3. Implement matching data-source methods in `src/pinkbee_mcp/live.py` and
   `src/pinkbee_mcp/mock.py`, then expose a narrowly scoped tool in `server.py`.
4. Validate all model-provided inputs, return structured JSON where appropriate, and
   translate failures using the project's `ToolError` pattern.
5. Gate every write with `ENABLE_WRITE_TO_PINKBEE` in both the MCP tool and live
   client. Never make live writes unless explicitly requested. Do not retry an
   ambiguous write. For explicitly requested live testing, record the old value,
   use a date at least two months ahead, restore the change, and verify restoration.
6. Update README and relevant files in `docs/` when behavior or configuration changes.
7. Run targeted tests, the full test suite, lint, and `git diff --check` when
   available. Report checks that the environment cannot run.

## Rules
- Keep tool descriptions clear and specific; agents use them to decide when to call.
- Keep mock and live data-source methods aligned.
- Reuse existing patterns for timeouts, logging, configuration, and errors.
- Keep writes opt-in, narrowly scoped, and idempotent where possible.
- Keep changes simple, manageable, and documented.

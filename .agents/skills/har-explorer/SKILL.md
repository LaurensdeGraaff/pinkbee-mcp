---
name: har-explorer
description: Use automatically when a Chrome HAR or .har file is supplied, or when identifying Pinkbee API behavior from captured browser traffic. Extract relevant endpoints, methods, payloads, responses, failures, and call order safely.
---

# HAR Explorer

Inspect `.har` files as structured JSON. Focus on `log.entries`; use `jq` or a
short Python script instead of loading a large HAR wholesale.

## Workflow
1. Confirm `log.entries`, entry count, and capture time range.
2. Summarize request time, method, host, path, status, MIME type, duration, and
   initiator when available.
3. Group repeated calls by method and normalized path. Separate API/XHR/fetch calls
   from static assets.
4. Highlight redirects, failures, HTTP status >= 400, slow calls, and unusual order.
5. Inspect headers, query parameters, request bodies, and responses only for relevant
   calls.
6. Finish with concise call-flow notes and a table of important endpoints.
7. For MCP implementation work, pass endpoint and payload findings to the
   `mcp-development` workflow; this skill does not itself modify application code.

## Safety
- Never print cookies, authorization headers, session IDs, CSRF tokens, API keys,
  passwords, or complete personal data.
- Redact sensitive values while preserving field names and payload shapes.
- Do not modify the HAR file.
- State when response bodies are missing because Chrome did not save them.

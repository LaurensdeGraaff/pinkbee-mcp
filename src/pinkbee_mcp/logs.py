"""Logging: showing what the server is doing, without ever printing personal data.

Two levels are useful:

- `INFO` (the default) — one line per tool call, plus every login. Enough to see
  what an assistant asked for and whether it worked.
- `DEBUG` — adds every HTTP request to Pinkbee with its status, size and timing, and
  what each tool made of the answer.

**This project's own log lines never print content.** Volunteer names and email
addresses arrive inside list and object fields, so nothing here prints a list or an
object: only top-level scalars (counts, dates, week labels) and sizes. The password,
the bearer token, the CSRF token and the session cookie are never logged at all.

Third-party libraries are a different matter. At `DEBUG` the MCP SDK and httpx log
whole request and response bodies, which does include names and addresses. Debug is
for troubleshooting, not for running with.
"""

from __future__ import annotations

import json
import logging
import sys
import time

from mcp.server.mcpserver.exceptions import ToolError

log = logging.getLogger("pinkbee_mcp")

#: Longest argument text we put in one log line.
MAX_ARGUMENT_TEXT = 200


LOG_FORMAT = "%(levelname)s %(name)s %(message)s"


def setup_logging(level_name: str) -> None:
    """Send logs to stderr at the level named in PINKBEE_LOG_LEVEL.

    The level applies to everything, libraries included. At `DEBUG` the MCP SDK and
    httpx print whole request and response bodies, so **debug logs do contain
    volunteer names and email addresses**. That is accepted here: debug is a
    troubleshooting switch, not something to leave on. See docs/deploying.md.
    """
    level = getattr(logging, level_name.strip().upper(), logging.INFO)
    logging.basicConfig(level=level, format=LOG_FORMAT, stream=sys.stderr)
    # basicConfig does nothing when something else already added a handler, which an
    # imported library may have done. Apply the level and format ourselves too.
    logging.getLogger().setLevel(level)
    for handler in logging.getLogger().handlers:
        handler.setFormatter(logging.Formatter(LOG_FORMAT))


def summarise_answer(text: str) -> str:
    """Describe a tool's answer in a few words, without revealing its content.

    Keeps only the top-level scalar fields of the JSON, because every field holding
    names or addresses is a list or an object. A non-JSON answer is described by its
    length alone.
    """
    try:
        answer = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return f"{len(text)} chars of text"

    if not isinstance(answer, dict):
        return f"{len(text)} chars of JSON"

    scalars = {
        key: value
        for key, value in answer.items()
        if isinstance(value, (int, float, str, bool)) or value is None
    }
    list_sizes = {
        f"{key}[]": len(value) for key, value in answer.items() if isinstance(value, list)
    }
    parts = [f"{key}={value}" for key, value in {**scalars, **list_sizes}.items()]
    return ", ".join(parts) if parts else f"{len(text)} chars of JSON"


def shorten(text: str, limit: int = MAX_ARGUMENT_TEXT) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def describe_arguments(params: object) -> str:
    """The tool name and its arguments, for the log line.

    Tool arguments are ids, dates and flags, so they are safe to show. Anything
    unexpectedly long is cut short.
    """
    if not isinstance(params, dict):
        return "?"
    name = params.get("name") or "?"
    arguments = params.get("arguments")
    if not isinstance(arguments, dict) or not arguments:
        return f"{name}()"
    shown = ", ".join(f"{key}={json.dumps(value)}" for key, value in sorted(arguments.items()))
    return f"{name}({shorten(shown)})"


def answer_text_of(result: object) -> str | None:
    """Pull the text out of a tool result, whatever shape the SDK used."""
    content = getattr(result, "content", None)
    if content is None and isinstance(result, dict):
        content = result.get("content")
    if not isinstance(content, list) or not content:
        return None
    first = content[0]
    text = getattr(first, "text", None)
    if text is None and isinstance(first, dict):
        text = first.get("text")
    return text if isinstance(text, str) else None


class StrictArguments:
    """Rejects a `tools/call` that carries an argument the tool does not have.

    The SDK validates types, ranges and required arguments, but quietly drops
    arguments it does not recognise. That is dangerous here: writing `group_id`
    instead of `group_ids` on pinkbee_list_registrations would drop the filter
    instead of failing, and a dropped filter means a wider answer than anyone asked
    for. So an unknown argument is refused outright, with a hint at the real names.
    """

    def __init__(self, allowed_arguments: dict[str, set[str]]) -> None:
        self.allowed_arguments = allowed_arguments

    async def __call__(self, ctx, call_next):
        params = ctx.params
        if getattr(ctx, "method", None) == "tools/call" and isinstance(params, dict):
            name = params.get("name")
            arguments = params.get("arguments")
            allowed = self.allowed_arguments.get(name)
            if allowed is not None and isinstance(arguments, dict):
                unknown = sorted(set(arguments) - allowed)
                if unknown:
                    known = ", ".join(sorted(allowed)) or "none"
                    log.warning("%s called with unknown argument(s) %s", name, unknown)
                    raise ToolError(
                        f"{name} has no argument {unknown}. It accepts: {known}."
                    )
        return await call_next(ctx)


class RequestLogger:
    """Logs every inbound MCP request: what was asked, how it went, how long it took.

    An MCP middleware: it wraps each request, so there is one place that knows about
    every call instead of a log line copied into every tool.
    """

    async def __call__(self, ctx, call_next):
        if ctx.request_id is None:
            # A notification, not a request. Nothing worth an INFO line.
            log.debug("notification %s", getattr(ctx, "method", "?"))
            return await call_next(ctx)

        method = getattr(ctx, "method", "?")
        what = describe_arguments(ctx.params) if method == "tools/call" else method
        log.debug("start %s", what)

        started = time.perf_counter()
        try:
            result = await call_next(ctx)
        except Exception as problem:
            log.warning("%s raised %s after %s", what, type(problem).__name__, ms_since(started))
            raise

        took = ms_since(started)
        text = answer_text_of(result)
        if text is None:
            log.info("%s ok in %s", what, took)
        elif text.startswith("Error:"):
            # The tool handled the problem and returned a sentence for the model.
            log.warning("%s in %s -> %s", what, took, shorten(text, 300))
        else:
            log.info("%s ok in %s -> %s", what, took, shorten(summarise_answer(text), 300))
        return result


def ms_since(started: float) -> str:
    return f"{(time.perf_counter() - started) * 1000:.0f}ms"

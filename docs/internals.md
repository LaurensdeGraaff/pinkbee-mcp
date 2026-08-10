# Internals

## Code layout

Small files, each with one job:

| File | Job |
| --- | --- |
| [config.py](../src/pinkbee_mcp/config.py) | Read the environment into one `Config` |
| [mock.py](../src/pinkbee_mcp/mock.py) | The built-in sample data source |
| [live.py](../src/pinkbee_mcp/live.py) | The real Pinkbee data source: log in, then GET |
| [roster.py](../src/pinkbee_mcp/roster.py) | Flatten a week and work out open spots. No network, no I/O |
| [server.py](../src/pinkbee_mcp/server.py) | The six tools |
| [logs.py](../src/pinkbee_mcp/logs.py) | Logging, and the two middlewares |
| [\_\_main\_\_.py](../src/pinkbee_mcp/__main__.py) | Start it, pick the transport, check tokens and origins |

Plus [healthcheck.py](../src/pinkbee_mcp/healthcheck.py) for the container probe.

`mock.py` and `live.py` offer the same six methods — `week_schedule`, `groups`,
`shifts`, `shift_group_links`, `contacts`, `registrations` — so `server.py` cannot
tell which one it is talking to. That is the whole trick behind mock mode, and it is
why the tests never need a real Pinkbee instance.

`roster.py` is deliberately pure: give it a week payload, get rows back. All the
capacity rules live there, which is why they are easy to test and hard to get wrong
twice.

## How failures are reported

Every tool wraps its body in `try` / `except Exception` and re-raises as `ToolError`
with one actionable sentence. The SDK turns that into a result flagged
`isError: true`, so a client can tell a failure from an answer, while the model still
reads something it can act on ("no volunteer group with id [999999]. Use
pinkbee_list_groups_and_shifts to see the ids that exist."). `ruff` is configured to
allow the blind `except` in `server.py` only.

An earlier version *returned* those sentences as normal results, which left
`isError: false` on every failure. Don't go back to that.

## The two middlewares

Both live in `logs.py` and are registered on the `MCPServer`:

- `StrictArguments` refuses a `tools/call` carrying an argument the tool does not
  have. The SDK silently drops unknown arguments, and a dropped argument on
  `pinkbee_list_registrations` is a dropped *filter* — which widens the answer instead
  of failing. `setup()` fills it in from the tools' own schemas, so it cannot drift.
- `RequestLogger` logs every call: what was asked, how long it took, and a summary of
  the answer that contains counts but never rows.

## Never let a filter widen

`resolve_shift_filter()` in `server.py` is the one place that turns a requested filter
into shift ids. It exists because an empty list means *every shift* to Pinkbee, so:

- no filter and no `all_shifts=true` → error;
- a group or shift id that does not exist → error naming the id;
- a group that exists but has no shifts → error;
- `all_shifts=true` together with a filter → error.

Only a deliberate `all_shifts=true` ever produces the empty, unfiltered query. The
bug this replaced returned every registration in the range for `group_ids=[999999]`.

## Ids

Pinkbee has two kinds of id and the tools need both:

- a **group id** is a group of volunteers ("who someone is")
- a **shift id** is a type of work ("what needs doing")

They are linked: every shift lists the groups allowed to sign up for it, in
`employee_group_ids`. So a group id can be turned into shift ids and back.
`pinkbee_list_groups_and_shifts` exposes both directions, and the `group_ids`
argument on the other tools does the translation for you.

## The mock data

`mock.py` holds three small tables — groups, shift types, volunteers — and generates
weeks from them on demand. Two properties matter:

- **Any week works.** There is no recorded date range to fall out of, so the mock
  does not rot as time passes.
- **It is deterministic.** Capacity and sign-ups come from `zlib.crc32` of the date
  and shift, not from a random number, so the same date always gives the same answer.
  Random data would make tests flaky and results confusing.

The generator deliberately produces a mix of full and open shifts, and marks about
one registration in four as absent, so the open-spot rule is exercised rather than
just described.

Every mock address ends in `@example.org`, a reserved domain that cannot receive
mail, and a test asserts it.

## Adding an endpoint

1. Put the URL in `live.py` as a small method.
2. Give `mock.py` a method with the same name, returning the same shape.
3. Only then write a tool in `server.py`.

Skipping step 2 means the tool works in live mode and breaks in mock mode, which is
the one thing this layout is meant to prevent. See [endpoints.md](endpoints.md) for
how to find the URL in the first place.

## Tests and lint

Python 3.11 or newer. If your machine has an older Python, use a container:

```bash
docker run --rm -v "$PWD":/app -w /app python:3.12-slim sh -c "pip install -q -e '.[dev]' && python -m pytest -q"
```

Locally:

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev]' && .venv/bin/pytest -q
```

Lint:

```bash
docker run --rm -v "$PWD":/app -w /app python:3.12-slim sh -c "pip install -q ruff && ruff check ."
```

The suite runs on mock data and `httpx.MockTransport`, so it never reaches a real
Pinkbee instance.

| Test file | Covers |
| --- | --- |
| [test_roster.py](../tests/test_roster.py) | Capacity maths, flattening, the absent-registration rules |
| [test_mock.py](../tests/test_mock.py) | The sample data: determinism, self-consistency, safe addresses |
| [test_live.py](../tests/test_live.py) | Login, session reuse and renewal, which URL each read uses |
| [test_tools.py](../tests/test_tools.py) | The six tools, including the personal-data refusals |
| [test_config.py](../tests/test_config.py) | Environment parsing and every refusal to start |
| [test_logs.py](../tests/test_logs.py) | Log summaries, strict arguments, and no personal data in our lines |
| [test_transport.py](../tests/test_transport.py) | Origin/Host allowlists and the bearer challenge |

## MCP SDK version

Built against MCP SDK 2.0, which replaced `FastMCP` with `MCPServer` and takes
`ToolAnnotations` objects instead of dicts. Older `FastMCP` examples do not apply.

Tool arguments are flat rather than a single nested model, because a `params: Model`
signature produces a `{"params": {...}}` input schema that clients find harder to
fill.

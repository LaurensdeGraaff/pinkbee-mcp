# Deploying

The server is meant to run as a Docker container. It writes nothing to disk, holds no
state worth keeping, and starts on built-in sample data, so a plain
`docker compose up -d` is a complete deployment.

## The image

Published as **`withoutanickname/pinkbee-mcp`** on Docker Hub.

```bash
docker pull withoutanickname/pinkbee-mcp
```

`docker-compose.yml` already points at it. Pin a version rather than `:latest` for
anything you care about:

```yaml
image: withoutanickname/pinkbee-mcp:0.2.0
```

Adding it to an existing stack needs nothing but the image, a port and optionally an
`.env`:

```yaml
services:
  pinkbee-mcp:
    image: withoutanickname/pinkbee-mcp:0.2.0
    restart: unless-stopped
    env_file:
      - path: .env
        required: false
    ports:
      - "127.0.0.1:8087:8080"
    read_only: true
    tmpfs: [/tmp]
    cap_drop: [ALL]
    security_opt: [no-new-privileges:true]
```

### Building it yourself

Uncomment `build: .` in `docker-compose.yml`, then:

```bash
docker compose up -d --build
```

Or plainly:

```bash
docker build -t pinkbee-mcp .
```

`.dockerignore` keeps the build context to `pyproject.toml`, `README.md` and `src/` —
tests, docs, the compose file and, importantly, any `.env` never enter the image.

### Publishing a new version

```bash
docker build -t withoutanickname/pinkbee-mcp:0.2.0 -t withoutanickname/pinkbee-mcp:latest .
docker push withoutanickname/pinkbee-mcp:0.2.0
docker push withoutanickname/pinkbee-mcp:latest
```

For a multi-architecture image (Apple Silicon and x86 servers from one tag):

```bash
docker buildx build --platform linux/amd64,linux/arm64 -t withoutanickname/pinkbee-mcp:0.2.0 --push .
```

Keep the tag in step with `version` in `pyproject.toml`.

## Every setting

All configuration comes from environment variables, so no secret ever ends up in
the image. `.env.example` lists them with their defaults; copy it to `.env`, which
is ignored by git.

### Where the data comes from

| Variable | Default | Meaning |
| --- | --- | --- |
| `PINKBEE_DATA_SOURCE` | `mock` | `mock` for built-in sample data, `live` for a real instance |
| `PINKBEE_BASE_URL` | — | e.g. `https://your-organisation.mijnpinkbee.nl`. Required for `live` |
| `PINKBEE_LOGIN` | — | Pinkbee username. Required for `live` |
| `PINKBEE_PASSWORD` | — | Pinkbee password. Required for `live` |
| `PINKBEE_ALLOW_INSECURE_HTTP_TO_LOCALHOST` | `false` | Allows plain `http://`, and only to this machine |

In `live` mode all three credentials must be present or the server exits with a
message naming what is missing. That refusal is the point: an unconfigured container
can never reach production by accident.

**The URL has to be `https://`.** Logging in POSTs the username and password as a
form, so plain HTTP would put them on the wire in clear text. `http://` is refused
outright for any real host, and allowed for `localhost` only when you also set
`PINKBEE_ALLOW_INSECURE_HTTP_TO_LOCALHOST=true` — which exists for a local test
Pinkbee and nothing else.

### Personal data

| Variable | Default | Meaning |
| --- | --- | --- |
| `PINKBEE_ALLOW_PERSONAL_DATA` | `false` | Allows `pinkbee_list_group_emails` and `pinkbee_list_registrations` |

With this off, both tools return an `Error: ...` explaining they are switched off.
The other four tools never contain a name or an address, so they work either way.

### How it is reachable

| Variable | Default | Meaning |
| --- | --- | --- |
| `PINKBEE_MCP_TRANSPORT` | `streamable-http` | `streamable-http` or `stdio` |
| `PINKBEE_MCP_HOST` | `0.0.0.0` | Bind address inside the container |
| `PINKBEE_MCP_PORT` | `8080` | Port inside the container |
| `PINKBEE_MCP_PATH` | `/mcp` | Path of the MCP endpoint |
| `PINKBEE_MCP_TOKEN` | empty | If set, clients must send `Authorization: Bearer <token>` |
| `PINKBEE_ALLOWED_ORIGINS` | empty | Extra `Origin` values to accept, comma separated |
| `PINKBEE_ALLOWED_HOSTS` | empty | Extra `Host` values to accept, comma separated |

Without a token the server logs a warning at startup and accepts anyone who can
reach the port. Make one with:

```bash
openssl rand -hex 32
```

A rejected request gets `401` with a `WWW-Authenticate: Bearer` challenge. This is a
single shared token for a private deployment — it is deliberately **not** MCP's OAuth
authorization, so there is no protected-resource metadata for a client to discover.
For an internet-facing service you would want the OAuth flow from the MCP
authorization spec instead; put this behind a proxy you trust.

### Limits on one tool call

| Variable | Default | Meaning |
| --- | --- | --- |
| `PINKBEE_MAX_REGISTRATION_DAYS` | `120` | Longest date range `pinkbee_list_registrations` accepts |
| `PINKBEE_MAX_IDS_PER_FILTER` | `50` | Most ids allowed in one `shift_ids` or `group_ids` |
| `PINKBEE_MAX_DATES` | `12` | Most dates allowed in one `pinkbee_get_week_schedule` |
| `PINKBEE_MAX_WEEKS` | `12` | Most weeks `pinkbee_list_open_shifts` will scan |

These stop one call from exporting months of personal data or producing an answer too
large to be useful. Going over a limit is an error naming the variable to raise.

### Other

| Variable | Default | Meaning |
| --- | --- | --- |
| `PINKBEE_TIMEZONE` | `Europe/Amsterdam` | Timezone used to work out "today" |
| `PINKBEE_TIMEOUT_SECONDS` | `20` | HTTP timeout for Pinkbee requests |
| `PINKBEE_LOG_LEVEL` | `INFO` | Python log level |

`PINKBEE_TIMEZONE` is not cosmetic. A container's clock is UTC, so between midnight
and 02:00 Amsterdam time a naive "today" is still yesterday, and every tool that
defaults to today would read the wrong week. An unknown timezone name is rejected at
startup.

## Origin and Host checks

A web page on any site can POST to a port on your machine. Without a check, such a
page could drive this server and read a whole roster — the DNS-rebinding attack the
MCP transport spec requires servers to block.

Two headers are checked on every request:

- **`Host`** — what the client asked for. An unknown value gets **421**.
- **`Origin`** — which page is making the request. An unknown value gets **403**. A
  request with **no** `Origin` is fine: that is what a normal, non-browser MCP client
  sends. Only browsers set it.

`localhost` and `127.0.0.1` are always accepted, on any port. Anything else you add
through `PINKBEE_ALLOWED_HOSTS` and `PINKBEE_ALLOWED_ORIGINS`, comma separated.

**A desktop MCP client with a `Host` of its own** — some clients send the name you
typed. Whatever appears in the log line `Invalid Host header: <value>` is exactly what
to add.

### How matching works

| Allowed value | Request header | Result |
| --- | --- | --- |
| `mcp.example.org` | `Host: mcp.example.org` | ✅ 200 |
| `mcp.example.org` | `Host: mcp.example.org:8443` | ❌ 421 — the port makes it a different string |
| `mcp.example.org:*` | `Host: mcp.example.org:8443` | ✅ 200 |
| `mcp.example.org:*` | `Host: mcp.example.org` | ❌ 421 — `:*` needs a port to be present |
| `mcp.example.org` | `Host: sub.mcp.example.org` | ❌ 421 — no subdomain wildcards |
| `https://mcp.example.org` | `Origin: https://mcp.example.org/` | ❌ 403 — no trailing slash |
| `https://mcp.example.org` | `Origin: http://mcp.example.org` | ❌ 403 — the scheme is part of it |

Three rules follow from that:

1. **List the name twice**, plain and with `:*`. `mcp.example.org:*` does *not* cover
   the portless form, and the portless form does not cover a port. Listing both is
   why every example above has two entries.
2. **The only wildcard is `:*`, for the port.** `*.example.org` matches nothing.
3. **`Origin` is an exact origin**: scheme, host, optional port. No path, no trailing
   slash.

`X-Forwarded-Host` is deliberately **not** consulted, since any client can send it.
Only the real `Host` and `Origin` count.

### When something is refused

The server logs exactly what it rejected, so you do not have to guess:

```
WARNING mcp.server.transport_security Invalid Host header: mcp.example.org:8443
WARNING mcp.server.transport_security Invalid Origin header: https://mcp.example.org/
```

At startup it also logs the full list it will accept, so you can check your
configuration arrived:

```
INFO pinkbee_mcp accepting Host localhost, localhost:*, 127.0.0.1, ... and Origin http://localhost, ...
```

## Ports and TLS

`docker-compose.yml` publishes on `127.0.0.1:8087` deliberately:

```yaml
ports:
  - "127.0.0.1:8087:8080"
```

There is no TLS inside the container. To reach it from elsewhere, terminate TLS in a
reverse proxy in front of it and set `PINKBEE_MCP_TOKEN`. Do not simply change the
binding to `0.0.0.0`: that puts a Pinkbee password behind an unencrypted port.

## Hardening

The compose file drops everything the server does not need:

```yaml
read_only: true          # the server writes nothing
tmpfs: [/tmp]
cap_drop: [ALL]
security_opt: [no-new-privileges:true]
```

The image also runs as an unprivileged user (`uid 10001`), created in the Dockerfile.

## Health check

The container's health check opens a TCP connection to its own port:

```bash
python -m pinkbee_mcp.healthcheck
```

It deliberately does not make an HTTP request. A GET to an MCP endpoint opens a
server-sent-event stream and never finishes, and a POST would need the bearer token.
A TCP connect answers the only question a health check should ask — is the process
accepting connections — and answers it at once.

Whether Pinkbee itself is reachable is a different question, and the
`pinkbee_check_connection` tool is the way to ask it.

## Logs

`PINKBEE_LOG_LEVEL` decides how much you see.

At `INFO`, the default, you get one line per tool call and one per login:

```
INFO pinkbee_mcp.tools data source: built-in mock data (no connection to any Pinkbee instance)
INFO pinkbee_mcp pinkbee_get_week_schedule(dates=["2026-08-13"]) ok in 5ms -> weeks[]=1
INFO pinkbee_mcp.live logging in to https://example.mijnpinkbee.nl as roster@example.org
INFO pinkbee_mcp.live logged in, session 1 ready (took 412ms)
WARNING pinkbee_mcp pinkbee_get_week_schedule(dates=["not a date"]) in 0ms -> Error: date must be YYYY-MM-DD or DD-MM-YYYY, got 'not a date'
```

Note what the summary after `->` contains: counts and list lengths, never the rows
themselves. A tool that returns an `Error: ...` sentence is logged as a `WARNING`,
which makes a misconfigured deployment easy to spot.

At `DEBUG` you additionally get every HTTP request to Pinkbee with its status, size
and timing, and what each tool made of the answer:

```
DEBUG pinkbee_mcp.live GET /api/schedule/week/2026-08-10 -> 200 application/json, 44362 bytes in 231ms
DEBUG pinkbee_mcp.live /api/schedule/week/2026-08-10 returned a list of 14
DEBUG pinkbee_mcp.tools week 2026-08-10: 98 shift days, 24 open spots
DEBUG pinkbee_mcp.tools groups [2] map to shifts [3, 4]
DEBUG pinkbee_mcp.live session 3 is already fresh, no login needed
```

> **`DEBUG` logs personal data.** The level applies to libraries too, and at `DEBUG`
> the MCP SDK and httpx print whole request and response bodies — so volunteer names
> and email addresses end up in the log. This project's own log lines never do that,
> but the libraries' do. Treat debug as a switch you flip while troubleshooting and
> then turn off, and do not ship debug logs anywhere. The password, the bearer token,
> the CSRF token and the session cookie are never logged at any level.

`WARNING` gives you only failures and refused logins.

## Running without Docker

For a desktop MCP client on the same machine, stdio is simpler than HTTP:

```bash
PINKBEE_MCP_TRANSPORT=stdio python -m pinkbee_mcp
```

Needs Python 3.11 or newer and `pip install .`.

## Upgrading

```bash
docker compose pull
docker compose up -d
```

Building from a checkout instead:

```bash
git pull
docker compose up -d --build
```

Nothing is stored between runs. The session cookie lives in memory, so a restart
just means the next read logs in again.

## Checking a deployment

```bash
docker compose ps                       # is it up and healthy?
docker compose logs --tail 20           # which data source did it pick?
```

The log line `Data source: mock` or `Data source: live` on startup is the quickest
confirmation that the container read the configuration you meant. In `live` mode it
also logs that all requests are read-only.

Then call `pinkbee_check_connection` — see
[curl_examples.md](curl_examples.md) — which logs in and reads one week, so it proves
the credentials work rather than just that the process is up.

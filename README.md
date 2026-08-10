# pinkbee-mcp

A read-only [MCP](https://modelcontextprotocol.io) server for **Pinkbee**
(`*.mijnpinkbee.nl`), an online platform for planning shifts and managing
volunteers.

It lets an AI assistant answer questions about a roster — which shifts still need
people, who is scheduled, who is in which group — and nothing more: it cannot book,
cancel or change anything. Works with any Pinkbee instance.

> **Proof of concept.**

## Run it

```bash
docker compose up -d
```

That is all. It pulls `withoutanickname/pinkbee-mcp` and starts on **built-in sample
data**, so there is nothing to configure and no risk to anyone's real roster. The MCP
endpoint is then on `http://127.0.0.1:8087/mcp`.

Without compose:

```bash
docker run -d --name pinkbee-mcp -p 127.0.0.1:8087:8080 withoutanickname/pinkbee-mcp
```

To build from this checkout instead, uncomment `build: .` in `docker-compose.yml` and
run `docker compose up -d --build`.

Point your MCP client at that URL, or try it from the terminal:

```bash
curl -s -X POST http://127.0.0.1:8087/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"pinkbee_check_connection","arguments":{}}}' | sed -n 's/^data: //p' | jq -r '.result.content[0].text'
```

## The six tools

| Tool | What it answers |
| --- | --- |
| `pinkbee_check_connection` | Which data source is in use, and does it answer? |
| `pinkbee_list_groups_and_shifts` | Every group and shift with its id, and which groups may take which shift |
| `pinkbee_get_week_schedule` | The full roster for the week around each date you give |
| `pinkbee_list_open_shifts` | Shifts that still have open spots over the coming weeks |
| `pinkbee_list_group_emails` | Email addresses of the volunteers in a group *(personal data)* |
| `pinkbee_list_registrations` | Who signed up for which shift between two dates *(personal data)* |

Group and shift names are chosen by each Pinkbee administrator, so nothing here
assumes any particular naming: `pinkbee_list_groups_and_shifts` returns the whole
list and the assistant matches the names itself.

## Connect it to a real Pinkbee

```bash
cp .env.example .env
```

Set these four, then `docker compose up -d`:

```dotenv
PINKBEE_DATA_SOURCE=live
PINKBEE_BASE_URL=https://your-organisation.mijnpinkbee.nl
PINKBEE_LOGIN=
PINKBEE_PASSWORD=
```

Use an account that only needs to read the roster. Every other setting is optional;
see [docs/deploying.md](docs/deploying.md).

## Safety

- **Read-only.** Every request to Pinkbee is a GET. The only POST in the whole
  codebase is the login itself.
- **Mock data by default.** Reaching a live instance needs a deliberate
  `PINKBEE_DATA_SOURCE=live` *and* credentials, or the server refuses to start.
- **Personal data is off by default.** The two tools that return names or email
  addresses refuse until you set `PINKBEE_ALLOW_PERSONAL_DATA=true`.
- **Not open to the network.** Optional bearer token, and the container publishes on
  `127.0.0.1` only. There is no TLS inside it, so put a reverse proxy in front if it
  has to leave the host.
- **One exception, on purpose:** `PINKBEE_LOG_LEVEL=DEBUG` also turns on the
  libraries' debug output, which prints whole response bodies — so personal data does
  appear in debug logs. Use it while troubleshooting, not in normal running. See
  [docs/deploying.md](docs/deploying.md#logs).

## Documentation

| Document | Contents |
| --- | --- |
| [docs/deploying.md](docs/deploying.md) | Every setting, TLS, health check, stdio mode, upgrading |
| [docs/curl_examples.md](docs/curl_examples.md) | A worked curl example per tool, and two traps to avoid |
| [docs/endpoints.md](docs/endpoints.md) | The Pinkbee API: login, the endpoints used, how to find more |
| [docs/login_sessions.md](docs/login_sessions.md) | How the session cookie is obtained, reused and renewed |
| [docs/internals.md](docs/internals.md) | Code layout, the mock data, running the tests |

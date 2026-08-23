# pinkbee-mcp
> **Unofficial community integration; not affiliated with or supported by Pinkbee.**
> 
> **Proof of concept.**

A read-only [MCP](https://modelcontextprotocol.io) server for **Pinkbee**
(`*.mijnpinkbee.nl`), an online platform for planning shifts and managing
volunteers. 

It lets an AI assistant answer questions about a roster — which shifts still need
people, who is scheduled, who is in which group — and nothing more: it cannot book,
cancel or change anything. 

## Run it
1. Get the docker compose file
```bash
curl -fsSLO https://raw.githubusercontent.com/withoutanickname/pinkbee-mcp/main/docker-compose.yml
```
2. Deploy docker compose
```bash
docker compose up -d
```
That is all. It pulls `withoutanickname/pinkbee-mcp` and starts on **built-in sample
data**, so there is nothing to configure and no risk to anyone's real roster. The MCP
endpoint is then on `http://<server-lan-ip>:8087/mcp` (and on
`http://127.0.0.1:8087/mcp` from the server itself).

Without compose:

```bash
docker run -d --name pinkbee-mcp -p 8087:8080 withoutanickname/pinkbee-mcp
```

To build from this checkout instead, uncomment `build: .` in `docker-compose.yml` and
run `docker compose up -d --build`.

Point your MCP client at that URL, or try it from the terminal:

```bash
curl -s -X POST http://127.0.0.1:8087/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"pinkbee_check_connection","arguments":{}}}' | sed -n 's/^data: //p' | jq -r '.result.content[0].text'
```

## Available calls

| Call | Arguments | What it answers |
| --- | --- | --- |
| `pinkbee_check_connection` | none | Which data source is in use, and does it answer? |
| `pinkbee_list_groups_and_shifts` | none | Every group and shift with its id, and which groups may take which shift |
| `pinkbee_get_week_schedule` | `dates`, optional `only_open_shifts` | The full roster for the weeks around the supplied dates |
| `pinkbee_list_open_shifts` | optional `start_date`, `weeks`, `shift_ids`, `group_ids` | Shifts that still have open spots over the coming weeks |
| `pinkbee_list_group_emails` | `group_ids`, optional `employment`, `with_names` | Email addresses of volunteers in a group *(personal data)* |
| `pinkbee_list_registrations` | `start_date`, `end_date`, optional `shift_ids`, `group_ids`, `all_shifts` | Who signed up for which shift *(personal data)* |

Group and shift names are chosen by each Pinkbee administrator, so nothing here
assumes any particular naming: `pinkbee_list_groups_and_shifts` returns the whole
list and the assistant matches the names itself.

All calls are enabled by default. Disable one or more by putting their full names in
the comma-separated blacklist:

```dotenv
PINKBEE_DISABLED_CALLS=pinkbee_list_group_emails,pinkbee_list_registrations
```

Disabled calls are removed from discovery as well as invocation. An unknown name is
treated as a configuration error instead of being silently ignored.

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

Use an account that only needs to read the roster. Compose reads these values from
`.env`; every supported variable and default is visible under `environment` in
`docker-compose.yml`.

## Network access

The Compose service listens on all host interfaces so another service on the LAN can
connect without extra configuration. By default, every sender that can reach port
`8087` is allowed. A bearer token is recommended even on a trusted LAN.

When upgrading from an older release that published only on `127.0.0.1`, note that
this default deliberately adds LAN access. Set a token and/or sender allowlist before
upgrading a live deployment if the LAN is not fully trusted.

To restrict access, set exact sender IPs or DNS names:

```dotenv
PINKBEE_ALLOWED_SENDERS=192.168.1.42,agent.domain.example.com
```

This allowlist checks the IP of the **client or service making the MCP request**. It
does not list the current machine's/server's own IP. DNS names are resolved to sender
IPs once when the MCP starts. Behind a reverse proxy, the sender seen by the MCP is
normally the proxy; see [docs/deploying.md](docs/deploying.md).

Browser requests carrying an `Origin` header are rejected to prevent a web page from
driving the LAN service through DNS rebinding. Normal MCP clients do not send it.

## Safety

- **Read-only.** Every request to Pinkbee is a GET. The only POST in the whole
  codebase is the login itself.
- **Mock data by default.** Reaching a live instance needs a deliberate
  `PINKBEE_DATA_SOURCE=live` *and* credentials, or the server refuses to start.
- **Personal data is off by default.** The two tools that return names or email
  addresses refuse until you set `PINKBEE_ALLOW_PERSONAL_DATA=true`.
- **A filter can never widen by accident.** An id that does not exist is an error, an
  unknown argument name is refused, and asking for every shift takes an explicit
  `all_shifts=true`. Date ranges and id lists are capped.
- **Credentials only over HTTPS.** A plain `http://` Pinkbee URL is refused, since
  logging in sends the password.
- **Simple network policy.** LAN access is on by default. Use
  `PINKBEE_ALLOWED_SENDERS` for sender-IP filtering and `PINKBEE_MCP_TOKEN` for a
  shared bearer token. There is no TLS inside the container, so use a trusted LAN or
  put a TLS reverse proxy in front.
- **One exception, on purpose:** `PINKBEE_LOG_LEVEL=DEBUG` also turns on the
  libraries' debug output, which prints whole response bodies — so personal data does
  appear in debug logs. Use it while troubleshooting, not in normal running. See
  [docs/deploying.md](docs/deploying.md#logs).

## Documentation

| Document | Contents |
| --- | --- |
| [docs/deploying.md](docs/deploying.md) | Every setting, sender access, TLS, health check, upgrading |
| [docs/curl_examples.md](docs/curl_examples.md) | A worked curl example per tool, and two traps to avoid |
| [docs/endpoints.md](docs/endpoints.md) | The Pinkbee API: login, the endpoints used, how to find more |
| [docs/login_sessions.md](docs/login_sessions.md) | How the session cookie is obtained, reused and renewed |
| [docs/internals.md](docs/internals.md) | Code layout, the mock data, running the tests |

## Licence

[MIT](LICENSE).

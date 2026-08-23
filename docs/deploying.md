# Deploying

The server is a stateless Docker container. A plain deployment starts with built-in
mock data and listens at `http://<server-lan-ip>:8087/mcp`:

```bash
docker compose up -d
```

No `.env` is required for mock mode. Compose reads `.env` automatically when it is
present and applies its values through the explicit `environment` section in
`docker-compose.yml`.

## Live data

Create `.env` from `.env.example` and set:

```dotenv
PINKBEE_DATA_SOURCE=live
PINKBEE_BASE_URL=https://your-organisation.mijnpinkbee.nl
PINKBEE_LOGIN=roster-reader@example.org
PINKBEE_PASSWORD=change-me
```

All three live values are required. The server refuses non-HTTPS Pinkbee URLs because
login sends the password. A local test Pinkbee can use HTTP only with
`PINKBEE_ALLOW_INSECURE_HTTP_TO_LOCALHOST=true`.

Mock and live modes expose the same MCP calls. Live mode performs only GET requests
after the login POST.

## Configuration

These are all supported deployment variables. Their defaults are also visible in
`docker-compose.yml`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `PINKBEE_DATA_SOURCE` | `mock` | `mock` for built-in data or `live` for Pinkbee |
| `PINKBEE_BASE_URL` | empty | Pinkbee URL, required in live mode |
| `PINKBEE_LOGIN` | empty | Pinkbee login, required in live mode |
| `PINKBEE_PASSWORD` | empty | Pinkbee password, required in live mode |
| `PINKBEE_ALLOW_INSECURE_HTTP_TO_LOCALHOST` | `false` | Permit HTTP only to a local test Pinkbee |
| `PINKBEE_ALLOW_PERSONAL_DATA` | `false` | Enable calls that return names or email addresses |
| `PINKBEE_MCP_TOKEN` | empty | Shared bearer token required from MCP clients |
| `PINKBEE_ALLOWED_SENDERS` | empty | Comma-separated sender IPs or DNS names; empty allows all |
| `PINKBEE_DISABLED_CALLS` | empty | Comma-separated call blacklist; empty enables all |
| `PINKBEE_TIMEZONE` | `Europe/Amsterdam` | Timezone used to determine today |
| `PINKBEE_TIMEOUT_SECONDS` | `20` | Timeout for Pinkbee HTTP requests |
| `PINKBEE_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, or `ERROR` |

The HTTP listener is deliberately fixed at `0.0.0.0:8080/mcp` inside the container.
Compose publishes it as port `8087`. Keeping these internal values fixed prevents the
listener, published port, and health check from drifting apart.

## Sender access

The default is deliberately simple: every sender that can reach the published port
may connect. The Compose port mapping uses all host interfaces:

```yaml
ports:
  - "8087:8080"
```

**Upgrade warning:** older Compose examples published only on `127.0.0.1`. This
version deliberately enables LAN access. Configure a token and/or sender allowlist
before upgrading a live deployment if every LAN device should not have access.

To whitelist requesters, set one or more exact IP addresses or DNS names:

```dotenv
PINKBEE_ALLOWED_SENDERS=192.168.1.42,agent.domain.example.com
```

`PINKBEE_ALLOWED_SENDERS` means the IP of the **client or service sending the MCP
request**. It is not the LAN address of the machine running Pinkbee MCP. For example,
if an automation service at `192.168.1.42` calls an MCP host at `192.168.1.10`, list
`192.168.1.42`, not `192.168.1.10`.

DNS names are resolved once at startup and the resulting IPs are compared with the
TCP peer address. Restart after DNS changes. This is IP filtering, not authenticated
domain identity.

Behind a reverse proxy, the TCP peer is normally the proxy, so the allowlist must
contain the proxy's IP. The application intentionally ignores `X-Forwarded-For`
because an untrusted client can forge it. Enforce original-client policies in a
trusted reverse proxy or firewall.

Docker Desktop may report its internal VM gateway as the TCP peer instead of the
original LAN client. In that environment, enforce per-client IP policy on the host or
a trusted reverse proxy. Native Linux Docker normally preserves the remote peer IP.

Requests carrying a browser `Origin` header are rejected. This blocks DNS-rebinding
attacks without requiring operators to configure destination Host and Origin values.
Normal non-browser MCP clients omit this header.

The sender allowlist is not a replacement for authentication. Set a shared token:

```bash
openssl rand -hex 32
```

```dotenv
PINKBEE_MCP_TOKEN=<generated-value>
```

Clients then send `Authorization: Bearer <generated-value>`. Internet-facing
deployments should also terminate TLS and use stronger authentication at a trusted
reverse proxy.

## Call blacklist

All six calls are enabled by default. Disable calls by full MCP name:

```dotenv
PINKBEE_DISABLED_CALLS=pinkbee_list_group_emails,pinkbee_list_registrations
```

Each disabled call is logged at startup and removed from `tools/list`, so clients do
not discover it. Direct invocation also fails as an unknown tool. A typo or unknown
call name prevents startup and names the invalid value.

Available names:

| Call | Personal data |
| --- | --- |
| `pinkbee_check_connection` | no |
| `pinkbee_list_groups_and_shifts` | no |
| `pinkbee_get_week_schedule` | no |
| `pinkbee_list_open_shifts` | no |
| `pinkbee_list_group_emails` | yes |
| `pinkbee_list_registrations` | yes |

`PINKBEE_ALLOW_PERSONAL_DATA=false` is an additional safety gate. The two personal
data calls remain visible but refuse to return data. Use the blacklist when they
should not be exposed at all.

## Operations

Build locally by uncommenting `build: .` in Compose, then run:

```bash
docker compose up -d --build
```

For published images, pin a version instead of `latest` in production. Upgrade with:

```bash
docker compose pull
docker compose up -d
```

Check startup and health with:

```bash
docker compose ps
docker compose logs --tail 50
```

The image runs as an unprivileged user, has a read-only filesystem, drops Linux
capabilities, and stores no persistent data. Its health check verifies that port 8080
is accepting TCP connections. Use `pinkbee_check_connection` to verify the selected
mock/live source itself.

At `DEBUG`, dependencies may log full response bodies containing personal data. Use
debug logging only while troubleshooting. Credentials, bearer tokens, CSRF tokens,
and session cookies are not logged by this project.

## Logs

Use `docker compose logs -f` to follow calls and startup policy. `INFO` records call
names, timings, the selected data source, every disabled call, and whether all senders
or an allowlist is active. It does not log returned roster rows.

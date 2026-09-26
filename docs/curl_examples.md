# Calling the tools with curl

You can drive every tool from the command line. Four things to know first:

- Always **POST**. A GET opens a server-sent-event stream that never closes, so curl
  appears to hang. That is normal, not a fault.
- Answers come back as a server-sent event: an `event: message` line, then the JSON
  on a `data: ` line. `sed -n 's/^data: //p'` keeps only that line, which you can
  then pipe into `jq`.
- Send `Accept: application/json, text/event-stream`. This server does not insist on
  it, but the MCP spec asks for it and other servers do refuse without it.
- No handshake is needed: the container runs in stateless mode, so you can call
  `tools/call` straight away without `initialize` first.

If you set `PINKBEE_MCP_TOKEN`, add `-H "Authorization: Bearer $PINKBEE_MCP_TOKEN"`
to every command below. Without it you get HTTP 401.

The examples assume the default published port, `127.0.0.1:8087`.

### List the tools and their exact argument names

Start here. This is the source of truth for what each tool accepts:

```bash
curl -s -X POST http://localhost:8087/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | sed -n 's/^data: //p' | jq -r '.result.tools[] | "\(.name)  \(.inputSchema.properties | keys)"'
```

### Check the connection

```bash
curl -s -X POST http://localhost:8087/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"pinkbee_check_connection","arguments":{}}}' | sed -n 's/^data: //p' | jq -r '.result.content[0].text'
```

### Look up group and shift ids

```bash
curl -s -X POST http://localhost:8087/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"pinkbee_list_groups_and_shifts","arguments":{}}}' | sed -n 's/^data: //p' | jq -r '.result.content[0].text | fromjson'
```

### The roster for one or more whole weeks

```bash
curl -s -X POST http://localhost:8087/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"pinkbee_get_week_schedule","arguments":{"dates":["2026-08-13"]}}}' | sed -n 's/^data: //p' | jq -r '.result.content[0].text | fromjson'
```

Several weeks at once, gaps only:

```bash
curl -s -X POST http://localhost:8087/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"pinkbee_get_week_schedule","arguments":{"dates":["2026-08-13","2026-08-20","2026-08-27"],"only_open_shifts":true}}}' | sed -n 's/^data: //p' | jq -r '.result.content[0].text | fromjson'
```

### Shifts that still need people

Note that this tool takes `start_date` and `weeks`, **not** `dates`:

```bash
curl -s -X POST http://localhost:8087/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"pinkbee_list_open_shifts","arguments":{"start_date":"2026-08-13","weeks":6,"group_ids":[2]}}}' | sed -n 's/^data: //p' | jq -r '.result.content[0].text | fromjson'
```

### Email addresses of a group

Needs `PINKBEE_ALLOW_PERSONAL_DATA=true`, otherwise the tool refuses.

```bash
curl -s -X POST http://localhost:8087/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d '{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"pinkbee_list_group_emails","arguments":{"group_ids":[2,15]}}}' | sed -n 's/^data: //p' | jq -r '.result.content[0].text | fromjson'
```

### Who signed up, between two dates

By shift id:

```bash
curl -s -X POST http://localhost:8087/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d '{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"pinkbee_list_registrations","arguments":{"start_date":"2026-07-10","end_date":"2026-09-10","shift_ids":[3,4]}}}' | sed -n 's/^data: //p' | jq -r '.result.content[0].text | fromjson | {count, shift_ids}'
```

Or by group id, which is turned into shift ids for you:

```bash
curl -s -X POST http://localhost:8087/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d '{"jsonrpc":"2.0","id":8,"method":"tools/call","params":{"name":"pinkbee_list_registrations","arguments":{"start_date":"2026-07-10","end_date":"2026-09-10","group_ids":[2]}}}' | sed -n 's/^data: //p' | jq -r '.result.content[0].text | fromjson | {count, shift_ids}'
```

### Set what volunteers may do in a week

Requires `ENABLE_WRITE_TO_PINKBEE=true`; live mode also needs an admin account.
Use a date in the intended week. This call **changes** that week's setting:

```bash
curl -s -X POST http://localhost:8087/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d '{"jsonrpc":"2.0","id":9,"method":"tools/call","params":{"name":"pinkbee_set_week_registration_possibilities","arguments":{"date":"2026-10-29","mode":"registration"}}}' | sed -n 's/^data: //p' | jq -r '.result.content[0].text | fromjson'
```

The modes are `registration` (only sign up), `deregistration` (only cancel) and
`both`. For example, to allow both again, repeat the call with `mode: "both"`.

## Two traps to avoid

### Week dates and Mondays

A Pinkbee week runs Monday to Sunday, and that is the only shape its API offers:
`/api/schedule/week/<date>` expects the **Monday** of the week you want.

So asking for `2026-08-13` (a Thursday) returns a week labelled
`"week_start": "2026-08-10"`. That is not your date being ignored — it is the week
that contains it. The date you asked for is echoed back in `requested_dates` so you
can see what happened.

`pinkbee_list_open_shifts` does the same when it reads the weeks, which is why
`weeks_read` can begin before your `start_date`. The shift days it returns are still
filtered to `start_date` and later.

The write tool reports that Monday too, but sends your chosen date in its PUT URL,
matching the observed Pinkbee UI behavior.

### An unknown argument name is refused

The MCP SDK checks types, ranges and required arguments, but it *drops* arguments it
does not recognise instead of complaining. That is dangerous: writing `group_id`
instead of `group_ids` would remove a filter rather than fail, and a removed filter
means a wider answer than anyone asked for.

So this server refuses them itself:

```json
{"name":"pinkbee_list_open_shifts","arguments":{"dates":["2026-08-13"]}}
```

```
pinkbee_list_open_shifts has no argument ['dates'].
It accepts: group_ids, shift_ids, start_date, weeks.
```

`dates` belongs to `pinkbee_get_week_schedule`; `start_date` and `weeks` belong to
`pinkbee_list_open_shifts`. `tools/list` is always the source of truth.

### Naming shifts is compulsory

`pinkbee_list_registrations` will not guess. Give it `shift_ids` or `group_ids`, and
any id that does not exist is an error rather than a filter that matches nothing:

```
no volunteer group with id [999999]. Use pinkbee_list_groups_and_shifts to see the ids that exist.
```

To ask about every shift on purpose, say so: `all_shifts=true`. It cannot be combined
with a filter. The reason is blunt — an empty filter means "everything" to Pinkbee, so
a silently-unmatched filter would hand back the whole roster including every name.

### Failures are real errors

A tool that cannot do what you asked fails with `isError: true` and a sentence saying
what to change, rather than returning a normal result whose text happens to start with
"Error". Check `isError` before reading `content`.

# Logging in and session handling

Only relevant in `live` mode. In mock mode there is nothing to log in to.

Pinkbee has no API key. You log in like a browser and get a Django session cookie,
so the server has to manage that session itself. All of this lives in
[`live.py`](../src/pinkbee_mcp/live.py).

## What happens

1. **The first read logs in.** Two requests: a GET of the login page to pick up the
   CSRF token, then the login POST.
2. **The session cookie is then reused** for every later read. There is no login per
   request and no check beforehand — a liveness check would cost exactly as much as
   the read it is protecting.
3. **Expiry is discovered, not predicted.** If a read comes back `401`, `403`, or as
   the login page, the server logs in again and retries that read once.
4. **Retried once, then it gives up** with a message saying Pinkbee keeps asking for
   a login, rather than looping.

So a tool call normally costs one GET per week or report, plus two extra requests the
first time and after each expiry.

## Telling "logged out" from "fine"

Django answers a *failed* login with HTTP 200 and re-renders the form, and a
successful one with a redirect. So neither the status code nor the final URL is
reliable. `shows_login_form()` decides from the page itself: a page carrying both a
CSRF token and a password field is the login form. A dashboard may well carry a CSRF
token for its own forms, which is why both have to be present.

## Measured behaviour

Against a fake Pinkbee that counts login POSTs:

| Pattern | Login POSTs | Reads |
| --- | --- | --- |
| 5 reads in a row | 1 | 5 |
| 5 reads, session dies on the 3rd | 2 | 6 |
| 6 reads arriving at the same moment, cold start | 1 | 6 |
| 6 reads arriving at the same moment, dead session | 1 | 7 |

Each row has a test in [`test_live.py`](../tests/test_live.py).

## Why there is a lock and a counter

```python
async def ensure_logged_in(self, after_session: int | None = None) -> None:
    async with self.login_lock:
        if self.logged_in and after_session != self.session_number:
            return
        await self.log_in()
```

Several tool calls can arrive at the same moment. Without the lock each one sees "not
logged in yet" and starts its own login: six simultaneous reads produced six login
POSTs, with interleaved CSRF and cookie updates that could make one of them fail.

The lock alone is not enough, though. A request that waited on the lock would log in
*again*, immediately after the first one already fixed things. That is what
`session_number` is for: it counts successful logins, so a waiting request can tell
"the session I was using went stale" from "someone else already replaced it while I
waited". Callers pass the session number they were using as `after_session`.

`log_in()` is the unconditional version and is used by the tests. Everything else
should call `ensure_logged_in()`.

## Lifetime

The session lives in memory, in one `httpx.AsyncClient` cookie jar for the life of
the process. Restarting the container simply means the next read logs in again. There
is nothing to persist and nothing to clean up.

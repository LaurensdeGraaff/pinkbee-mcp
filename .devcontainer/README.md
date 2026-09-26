# Local development container
place a valid `.env` in the devcontainer root folder and deploy the devcontainer.

The container runs the mcp using the bind-mounted source code, at `http://127.0.0.1:8087/mcp` on the host.\

From the dev terminal example:

```sh
curl -s -X POST http://127.0.0.1:8080/mcp -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"pinkbee_check_connection","arguments":{}}}'
```

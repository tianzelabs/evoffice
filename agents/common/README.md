# agents/common/ — what every agent shares

## Planned files

| file | owns |
|---|---|
| `office_client.py` | HTTP calls to the server + an SSE subscription to the event stream |
| `llm.py` | client for the server's `/llm` gateway — model and Jev calls. The key and the budget live on the server, not here |

## Does not own

Anything role-specific. If only one agent needs it, it lives in that agent's dir.

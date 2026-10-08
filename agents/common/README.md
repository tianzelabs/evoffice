# agents/common/ — what every agent shares

## Planned files

| file | owns |
|---|---|
| `office_client.py` | HTTP calls to the server + an SSE subscription to the event stream |
| `llm.py` | OpenRouter (OpenAI-compatible) client; writes a `spend` event per call and refuses when the role's daily budget is spent |

## Does not own

Anything role-specific. If only one agent needs it, it lives in that agent's dir.

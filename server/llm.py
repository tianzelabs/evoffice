"""The /llm gateway: the only way an agent reaches a model.

Agents hold an office token, never the OpenRouter key. They point an ordinary
OpenAI client at `<office>/llm/v1` with their token as the api key -- rlms needs
no change -- and the gateway checks the budget and the model allowlist, swaps in
the real key, forwards, and records what the call actually cost as a `spend`
event. That makes the budget structural, like the fee model: an agent cannot
spend past its cap, because it has no other way to call.

Cost comes from OpenRouter's own `usage.cost`, never an estimate (an estimate in
this project was once off by 8x). A response without a cost is recorded as
`unpriced` so it is visible, not silently counted as free.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .store import Store

UPSTREAM = "https://openrouter.ai"
BUDGET_USD = {"trader": 0.30, "manager": 0.20}                    # per EMPLOYEE, per UTC day (user, 2026-10-09)
ALLOWED = {
    # haiku-5.5 for trader-1; gemini-3.1-flash-lite for trader-2 -- the only other candidate that kept
    # should_wake and reported its own change truthfully (gpt-5-mini, deepseek-v4-flash failed both)
    "trader": {"anthropic/claude-haiku-5.5", "google/gemini-3.1-flash-lite", "typesafe/jev-1.13"},
    "manager": set(filter(None, os.environ.get("OFFICE_MANAGER_MODELS", "").split(","))) | {"typesafe/jev-1.13"},
}
ROUTES = {"chat": "/api/v1/chat/completions", "decisions": "/api/alpha/decisions"}
# Output cap per call. Found in the first live trial: one call ran away to 65,536
# output tokens ($0.033, 4.5 minutes), and that text then rode in every later
# call's input. A per-turn budget alone did not stop it; capping output does.
MAX_OUTPUT_TOKENS = {"trader": 8192, "manager": 8192}


class GatewayRefused(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status


def load_key() -> str:
    """OPENROUTER_API_KEY from the environment, or from the KEY=VALUE file OFFICE_KEY_FILE."""
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"]
    path = Path(os.path.expanduser(os.environ.get("OFFICE_KEY_FILE", "~/.village.env")))
    for line in path.read_text().splitlines():
        k, _, v = line.partition("=")
        if k.strip() == "OPENROUTER_API_KEY":
            return v.strip().strip('"').strip("'")
    raise RuntimeError(f"OPENROUTER_API_KEY not found in env or {path}")


def spent_today(store: Store, employee: str) -> float:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = store.q("SELECT COALESCE(SUM(json_extract(payload, '$.cost')), 0) AS s FROM events "
                   "WHERE kind = 'spend' AND ts >= ? AND actor = ?", (day, employee))
    return float(rows[0]["s"])


def budget(store: Store, employee: str, role: str) -> dict:
    """Each employee has its own cap: a second trader adds a budget, it does not halve one."""
    cap = BUDGET_USD.get(role, 0.0)
    s = spent_today(store, employee)
    return {"employee": employee, "role": role, "spent_usd": round(s, 6), "cap_usd": cap,
            "left_usd": round(max(0.0, cap - s), 6)}


class Gateway:
    def __init__(self, store: Store, key: str | None = None, transport: httpx.BaseTransport | None = None):
        self.store = store
        self.key = key
        self.client = httpx.Client(base_url=UPSTREAM, timeout=300, transport=transport)

    def forward(self, who: dict, route: str, body: dict) -> dict:
        role = who["role"]
        model = body.get("model", "")
        if model not in ALLOWED.get(role, set()):
            raise GatewayRefused(403, f"model {model!r} is not allowed for role {role!r}")
        b = budget(self.store, who["id"], role)
        if b["left_usd"] <= 0:
            raise GatewayRefused(429, f"today's budget for {who['id']} is spent (${b['spent_usd']:.4f} of ${b['cap_usd']:.2f})")
        if body.get("stream"):
            raise GatewayRefused(400, "streaming is not supported; cost must be read from the response")
        if route == "chat":
            cap = MAX_OUTPUT_TOKENS.get(role, 4096)
            for field in ("max_tokens", "max_completion_tokens"):
                if field in body:
                    body[field] = min(int(body[field] or cap), cap)
            if "max_tokens" not in body and "max_completion_tokens" not in body:
                body["max_tokens"] = cap
        key = self.key or load_key()
        for attempt in (1, 2):
            r = self.client.post(ROUTES[route], json=body, headers={"Authorization": f"Bearer {key}"})
            try:
                data = r.json()
            except ValueError:
                data = {"error": r.text[:500]}
            usage = data.get("usage") or {}
            cost = usage.get("cost")
            # Found live with trader-2: OpenRouter answered 200 with no usage (an upstream provider
            # error in a 200 body). Passed through, it crashed the agent's client. Retry once; then refuse.
            malformed = r.status_code == 200 and (not usage or (route == "chat" and not data.get("choices")))
            self.store.emit(who["id"], "spend", {
                "role": role, "model": model, "route": route, "status": r.status_code, "attempt": attempt,
                "in_tok": usage.get("prompt_tokens", usage.get("input_tokens")),
                "out_tok": usage.get("completion_tokens", usage.get("output_tokens")),
                "cost": float(cost) if cost is not None else 0.0, "unpriced": cost is None and r.status_code == 200,
                **({"malformed": str(data)[:300]} if malformed else {})})
            if not malformed:
                break
        if malformed:
            raise GatewayRefused(502, f"upstream returned 200 without a usable answer: {str(data)[:300]}")
        if r.status_code != 200:
            raise GatewayRefused(r.status_code, f"upstream: {str(data.get('error', data))[:300]}")
        return data

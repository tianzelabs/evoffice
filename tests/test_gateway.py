"""The /llm gateway against a fake upstream. These are the rules that make the
budget structural: an agent has no way to call a model except through here."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from server import llm
from server.app import create_app
from server.market import FakeMarket
from server.store import Store

TOKENS = {"b": {"id": "boss", "role": "boss"}, "t1": {"id": "trader-1", "role": "trader"}}
H = lambda tok: {"Authorization": f"Bearer {tok}"}
CHAT = {"model": "anthropic/claude-haiku-5.5", "messages": [{"role": "user", "content": "hi"}]}


@pytest.fixture
def office(tmp_path):
    seen = []

    def upstream(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        cost = 0.12 if b"expensive" in request.content else 0.001
        if request.url.path.endswith("/decisions"):
            return httpx.Response(200, json={"answers": {"q": {"type": "noul", "noul": 0.7}},
                                             "usage": {"input_tokens": 10, "output_tokens": 2, "cost": 0.0001}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}],
                                         "usage": {"prompt_tokens": 5, "completion_tokens": 1, "cost": cost}})

    store = Store(str(tmp_path / "office.db"))
    gw = llm.Gateway(store, key="sk-real", transport=httpx.MockTransport(upstream))
    return TestClient(create_app(store, FakeMarket(), TOKENS, backstop_every_s=0, gateway=gw)), store, seen


def test_the_agent_never_holds_the_key(office):
    c, _, seen = office
    r = c.post("/llm/v1/chat/completions", json=CHAT, headers=H("t1"))
    assert r.status_code == 200 and r.json()["choices"][0]["message"]["content"] == "hello"
    assert seen[0].headers["authorization"] == "Bearer sk-real"       # swapped in by the server
    assert seen[0].url.path == "/api/v1/chat/completions"


def test_every_call_is_a_spend_event_with_the_real_cost(office):
    c, store, _ = office
    c.post("/llm/v1/chat/completions", json=CHAT, headers=H("t1"))
    c.post("/llm/api/alpha/decisions", json={"model": "typesafe/jev-1.13", "state": {}, "questions": {}}, headers=H("t1"))
    spends = [e["payload"] for e in store.events_since(0) if e["kind"] == "spend"]
    assert [(s["route"], s["cost"]) for s in spends] == [("chat", 0.001), ("decisions", 0.0001)]
    assert c.get("/budget/me", headers=H("t1")).json()["spent_usd"] == pytest.approx(0.0011)


def test_a_model_off_the_allowlist_is_refused_and_costs_nothing(office):
    c, store, seen = office
    r = c.post("/llm/v1/chat/completions", json={**CHAT, "model": "openai/gpt-5"}, headers=H("t1"))
    assert r.status_code == 403 and not seen


def test_the_budget_is_a_wall(office):
    c, _, seen = office
    big = {**CHAT, "messages": [{"role": "user", "content": "expensive"}]}
    for _ in range(3):                                  # 3 x $0.12 crosses the $0.30 trader cap
        c.post("/llm/v1/chat/completions", json=big, headers=H("t1"))
    r = c.post("/llm/v1/chat/completions", json=CHAT, headers=H("t1"))
    assert r.status_code == 429 and "budget for trader-1 is spent" in r.json()["detail"]
    assert len(seen) == 3                               # the refused call never left the office


def test_output_length_is_capped_by_the_office(office):
    c, _, seen = office
    c.post("/llm/v1/chat/completions", json=CHAT, headers=H("t1"))
    c.post("/llm/v1/chat/completions", json={**CHAT, "max_completion_tokens": 999_999}, headers=H("t1"))
    c.post("/llm/v1/chat/completions", json={**CHAT, "max_tokens": 100}, headers=H("t1"))
    bodies = [json.loads(r.content) for r in seen]
    assert bodies[0]["max_tokens"] == llm.MAX_OUTPUT_TOKENS["trader"]          # absent -> the cap
    assert bodies[1]["max_completion_tokens"] == llm.MAX_OUTPUT_TOKENS["trader"]  # too big -> the cap
    assert bodies[2]["max_tokens"] == 100                                       # smaller -> kept


def test_each_trader_has_its_own_budget(tmp_path):
    def upstream(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "x"}}],
                                         "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0.12}})
    tokens = {"t1": {"id": "trader-1", "role": "trader"}, "t2": {"id": "trader-2", "role": "trader"}}
    store = Store(str(tmp_path / "o.db"))
    gw = llm.Gateway(store, key="k", transport=httpx.MockTransport(upstream))
    c = TestClient(create_app(store, FakeMarket(), tokens, backstop_every_s=0, gateway=gw))
    for _ in range(3):
        c.post("/llm/v1/chat/completions", json=CHAT, headers=H("t1"))
    assert c.post("/llm/v1/chat/completions", json=CHAT, headers=H("t1")).status_code == 429
    assert c.post("/llm/v1/chat/completions", json=CHAT, headers=H("t2")).status_code == 200   # untouched by trader-1


def test_a_200_without_usage_is_retried_then_refused(tmp_path):
    calls = []

    def upstream(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(200, json={"error": {"message": "provider hiccup"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}],
                                         "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0.001}})
    store = Store(str(tmp_path / "o.db"))
    gw = llm.Gateway(store, key="k", transport=httpx.MockTransport(upstream))
    c = TestClient(create_app(store, FakeMarket(), {"t1": {"id": "trader-1", "role": "trader"}}, backstop_every_s=0, gateway=gw))
    r = c.post("/llm/v1/chat/completions", json=CHAT, headers=H("t1"))
    assert r.status_code == 200 and len(calls) == 2                        # retried once, then fine
    spends = [e["payload"] for e in store.events_since(0) if e["kind"] == "spend"]
    assert "malformed" in spends[0] and "malformed" not in spends[1]


def test_streaming_is_refused_because_its_cost_could_not_be_read(office):
    c, _, seen = office
    assert c.post("/llm/v1/chat/completions", json={**CHAT, "stream": True}, headers=H("t1")).status_code == 400


def test_an_agent_reports_only_its_own_state(office):
    c, store, _ = office
    assert c.post("/report", json={"kind": "wake", "payload": {"reasons": ["heartbeat"]}}, headers=H("t1")).status_code == 200
    assert c.post("/report", json={"kind": "close", "payload": {}}, headers=H("t1")).status_code == 422
    assert c.post("/report", json={"kind": "wake", "payload": {}}).status_code == 401
    wake = [e for e in store.events_since(0) if e["kind"] == "wake"][0]
    assert wake["actor"] == "trader-1"                  # stamped by the server, not claimed by the body


def test_bars_come_from_the_market(office):
    c, _, _ = office
    assert len(c.get("/bars?minutes=5").json()) == 5

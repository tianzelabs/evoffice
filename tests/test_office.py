"""The office through its API, against a fake market. Each test is a rule of the
world that, if broken, would make the leaderboard or the chat lie."""
import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.market import FakeMarket
from server.store import Store

TOKENS = {"b": {"id": "boss", "role": "boss"}, "m": {"id": "manager", "role": "manager"},
          "t1": {"id": "trader-1", "role": "trader"}, "t2": {"id": "trader-2", "role": "trader"}}
H = lambda tok: {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def office(tmp_path):
    market = FakeMarket()
    store = Store(str(tmp_path / "office.db"))
    client = TestClient(create_app(store, market, TOKENS, backstop_every_s=0))
    return client, market, store


def test_everyone_sees_everyones_chat(office):
    c, _, _ = office
    c.post("/say", json={"text": "早上好", "to": "trader-1"}, headers=H("b"))
    c.post("/say", json={"text": "on it"}, headers=H("t1"))
    says = [e for e in c.get("/events").json() if e["kind"] == "say"]
    assert [(e["actor"], e["payload"]["text"]) for e in says] == [("boss", "早上好"), ("trader-1", "on it")]
    assert says[0]["payload"]["to"] == "trader-1"


def test_no_token_no_voice(office):
    c, _, _ = office
    assert c.post("/say", json={"text": "hi"}).status_code == 401
    assert c.post("/say", json={"text": "hi"}, headers=H("nope")).status_code == 401


def test_events_since_returns_only_newer(office):
    c, _, _ = office
    first = c.post("/say", json={"text": "one"}, headers=H("b")).json()["id"]
    c.post("/say", json={"text": "two"}, headers=H("b"))
    assert [e["payload"]["text"] for e in c.get(f"/events?since={first}").json()] == ["two"]


def test_round_trip_through_the_api_is_net_of_fees(office):
    c, m, _ = office
    p = c.post("/positions/open", json={"side": "long", "size": 0.005, "strategy_version": "v1"}, headers=H("t1")).json()
    assert p["entry_px"] == 80_000.0
    m.prices["BTC/USD"] = 80_020.0               # moved the right way, by less than the fee
    closed = c.post(f"/positions/{p['id']}/close", headers=H("t1")).json()
    assert closed["close_reason"] == "self" and closed["pnl"] < 0


def test_only_traders_trade_and_only_their_own(office):
    c, _, _ = office
    assert c.post("/positions/open", json={"side": "long", "size": 0.005}, headers=H("m")).status_code == 409
    p = c.post("/positions/open", json={"side": "long", "size": 0.005}, headers=H("t1")).json()
    assert c.post(f"/positions/{p['id']}/close", headers=H("t2")).status_code == 409
    assert c.post(f"/positions/{p['id']}/close", headers=H("m")).status_code == 409


def test_a_position_cannot_close_twice(office):
    c, _, _ = office
    p = c.post("/positions/open", json={"side": "short", "size": 0.005}, headers=H("t1")).json()
    assert c.post(f"/positions/{p['id']}/close", headers=H("t1")).status_code == 200
    assert c.post(f"/positions/{p['id']}/close", headers=H("t1")).status_code == 409


def test_a_stale_feed_refuses_to_fill_rather_than_guess(office):
    c, m, store = office
    m.stale = True
    r = c.post("/positions/open", json={"side": "long", "size": 0.005}, headers=H("t1"))
    assert r.status_code == 409 and "no fresh price" in r.json()["detail"]
    assert store.q("SELECT COUNT(*) AS n FROM positions")[0]["n"] == 0
    assert c.get("/price").status_code == 503


def test_size_cap_and_pair_are_enforced(office):
    c, _, _ = office
    assert c.post("/positions/open", json={"side": "long", "size": 0.06}, headers=H("t1")).status_code == 409
    assert c.post("/positions/open", json={"side": "long", "size": 0.01, "pair": "ETH/USD"}, headers=H("t1")).status_code == 409


def test_max_hold_backstop_closes_and_says_why(office):
    from server import positions
    c, m, store = office
    p = c.post("/positions/open", json={"side": "long", "size": 0.005, "max_hold_s": 1}, headers=H("t1")).json()
    store.x("UPDATE positions SET opened_ts = '2020-01-01T00:00:00.000+00:00' WHERE id = ?", (p["id"],))
    m.stale = True
    assert positions.enforce_max_hold(store, m) == []          # stale feed: wait, do not guess
    m.stale = False
    assert positions.enforce_max_hold(store, m) == [p["id"]]
    assert positions.get(store, p["id"])["close_reason"] == "max_hold"


def test_leaderboard_lists_idle_traders_and_scores_per_version(office):
    c, m, _ = office
    for version, exit_px in (("v1", 79_900.0), ("v2", 80_300.0)):
        m.prices["BTC/USD"] = 80_000.0
        p = c.post("/positions/open", json={"side": "long", "size": 0.005, "strategy_version": version}, headers=H("t1")).json()
        m.prices["BTC/USD"] = exit_px
        c.post(f"/positions/{p['id']}/close", headers=H("t1"))
    b = c.get("/leaderboard").json()
    by_emp = {r["employee"]: r for r in b["by_employee"]}
    assert by_emp["trader-2"]["trades"] == 0                     # on the roster, not in the data: still listed
    assert by_emp["trader-1"]["trades"] == 2
    versions = {r["strategy_version"]: r for r in b["by_version"]}
    assert versions["v1"]["net_pnl"] < 0 < versions["v2"]["net_pnl"]

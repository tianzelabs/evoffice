"""The manager's authority: real over the trader, none over the office."""
import json

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.market import FakeMarket
from server.store import Store

H = lambda tok: {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def office(tmp_path):
    tokens = {"b": {"id": "boss", "role": "boss"}, "m": {"id": "manager", "role": "manager"},
              "t1": {"id": "trader-1", "role": "trader"}}
    path = tmp_path / "tokens.json"
    path.write_text(json.dumps(tokens))
    m = FakeMarket()
    store = Store(str(tmp_path / "o.db"))
    return TestClient(create_app(store, m, tokens, backstop_every_s=0, tokens_path=path)), m, store, path


def test_the_manager_sets_params_within_office_limits(office):
    c, *_ = office
    r = c.post("/employees/trader-1/params", json={"heartbeat_min": 30, "max_size": 0.02, "reason": "slow down"}, headers=H("m"))
    assert r.status_code == 200 and r.json()["params"]["max_size"] == 0.02
    assert c.post("/employees/trader-1/params", json={"max_size": 5.0}, headers=H("m")).status_code == 409   # above the office cap
    assert c.post("/employees/trader-1/params", json={"heartbeat_min": 30}, headers=H("t1")).status_code == 409  # not by the trader


def test_a_lowered_size_cap_binds_the_trader(office):
    c, *_ = office
    c.post("/employees/trader-1/params", json={"max_size": 0.003}, headers=H("m"))   # below the Junior level cap
    assert c.post("/positions/open", json={"side": "long", "size": 0.004}, headers=H("t1")).status_code == 409
    assert c.post("/positions/open", json={"side": "long", "size": 0.003}, headers=H("t1")).status_code == 200


def test_firing_keeps_the_record_and_seats_a_successor_on_the_same_token(office):
    c, m, store, path = office
    p = c.post("/positions/open", json={"side": "long", "size": 0.005}, headers=H("t1")).json()
    r = c.post("/employees/trader-1/fire", json={"reason": "never changed"}, headers=H("m")).json()
    assert r["successor"] == "trader-1.2" and r["positions_left_open"] == []
    assert store.q("SELECT close_reason FROM positions WHERE id = ?", (p["id"],))[0]["close_reason"] == "fired"
    assert c.get("/me", headers=H("t1")).json()["id"] == "trader-1.2"              # same token, new employee
    assert json.loads(path.read_text())["t1"]["id"] == "trader-1.2"                 # survives a server restart
    board = {r["employee"]: r for r in c.get("/leaderboard").json()["by_employee"]}
    assert board["trader-1"]["fired"] and board["trader-1"]["trades"] == 1 and "trader-1.2" in board
    again = c.post("/employees/trader-1.2/fire", json={"reason": "again"}, headers=H("b")).json()
    assert again["successor"] == "trader-1.3"


def test_the_trader_cannot_fire(office):
    c, *_ = office
    assert c.post("/employees/trader-1/fire", json={"reason": "x"}, headers=H("t1")).status_code == 409

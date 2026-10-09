"""Agents name themselves; the id stays the key."""
import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.market import FakeMarket
from server.store import Store

TOKENS = {"b": {"id": "boss", "role": "boss"}, "m": {"id": "manager", "role": "manager"},
          "t1": {"id": "trader-1", "role": "trader"}, "t2": {"id": "trader-2", "role": "trader"}}
H = lambda t: {"Authorization": f"Bearer {t}"}


@pytest.fixture
def c(tmp_path):
    return TestClient(create_app(Store(str(tmp_path / "o.db")), FakeMarket(), TOKENS, backstop_every_s=0))


def test_an_agent_names_itself_and_everyone_sees_it(c):
    assert c.post("/me/name", json={"name": "Ada Lovelace"}, headers=H("t1")).status_code == 200
    emp = {e["id"]: e for e in c.get("/employees").json()}
    assert emp["trader-1"]["name"] == "Ada Lovelace"
    assert [e for e in c.get("/events").json() if e["kind"] == "name"][0]["payload"]["name"] == "Ada Lovelace"
    assert {r["employee"]: r["name"] for r in c.get("/leaderboard").json()["by_employee"]}["trader-1"] == "Ada Lovelace"


def test_names_are_unique_and_not_roles(c):
    c.post("/me/name", json={"name": "Rex"}, headers=H("t1"))
    assert c.post("/me/name", json={"name": "rex"}, headers=H("t2")).status_code == 409
    for bad in ("boss", "trader-3", "", "x" * 30, "<script>"):
        assert c.post("/me/name", json={"name": bad}, headers=H("t2")).status_code in (409, 422)
    assert c.post("/me/name", json={"name": "Boss Hog"}, headers=H("b")).status_code == 409   # the boss is the boss


def test_one_rename_a_day(c):
    assert c.post("/me/name", json={"name": "Morgan"}, headers=H("m")).status_code == 200
    assert c.post("/me/name", json={"name": "Morgana"}, headers=H("m")).status_code == 409


def test_cjk_names_are_fine(c):
    assert c.post("/me/name", json={"name": "小明"}, headers=H("t2")).status_code == 200

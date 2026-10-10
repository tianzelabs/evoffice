"""XP is earned by validated improvement; levels unlock size; badges are announced once."""
import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.evaluator import service
from server.market import FakeMarket
from server.store import Store

TOKENS = {"t1": {"id": "trader-1", "role": "trader"}}
H = {"Authorization": "Bearer t1"}


@pytest.fixture
def office(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "CACHE", tmp_path / "heldout")
    results = iter([{"trades": 50, "net_bps_per_trade": -10.0, "ci95_net_bps_per_trade": [-15.0, -5.0]},
                    {"trades": 50, "net_bps_per_trade": -4.0, "ci95_net_bps_per_trade": [-9.0, 1.0]},
                    {"trades": 50, "net_bps_per_trade": 6.0, "ci95_net_bps_per_trade": [1.0, 11.0]}])
    store = Store(str(tmp_path / "o.db"))
    c = TestClient(create_app(store, FakeMarket(), TOKENS, backstop_every_s=0, eval_runner=lambda b, code, detail=False: {"trades": 0} if "precheck" in str(b) else dict(next(results))))
    return c, store


def test_a_new_trader_is_a_junior_with_a_small_cap(office):
    c, _ = office
    p = c.get("/progress").json()["trader-1"]
    assert (p["level"], p["title"], p["max_size"], p["xp"]) == (1, "Junior", 0.005, 0)
    assert c.post("/positions/open", json={"side": "long", "size": 0.01}, headers=H).status_code == 409
    assert c.post("/positions/open", json={"side": "long", "size": 0.005}, headers=H).status_code == 200


def test_improvement_earns_xp_and_an_edge_earns_most(office):
    c, store = office
    for _ in range(3):
        c.post("/evaluate", json={"code": "def decide(b): return None"}, headers=H)
    p = c.get("/progress").json()["trader-1"]
    # 3 tests (+9), two improvements (+15 each), one interval above zero (+50)
    assert p["xp"] == 9 + 30 + 50 and p["level"] == 2 and p["title"] == "Associate"
    assert {"first_test", "improver", "edge"} <= set(p["badges"])
    kinds = [e["kind"] for e in store.events_since(0)]
    assert kinds.count("level") == 1 and kinds.count("badge") == 3          # announced once each


def test_pnl_alone_does_not_level_you_up(office):
    c, store = office
    m = c.app  # noqa: F841
    for _ in range(12):
        pid = c.post("/positions/open", json={"side": "long", "size": 0.005}, headers=H).json()["id"]
        c.post(f"/positions/{pid}/close", headers=H)
    assert c.get("/progress").json()["trader-1"]["xp"] == 10                # capped at +10 a day

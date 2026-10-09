"""The held-out evaluator: what it lets a strategy see, what it charges, and what it reveals."""
import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.evaluator import service
from server.evaluator.sim import aggregate, simulate
from server.market import FakeMarket
from server.store import Store


def bars(prices):
    return [{"m": str(i), "o": p, "h": p, "l": p, "c": p, "v": 1.0} for i, p in enumerate(prices)]


def test_decide_never_sees_the_future():
    seen_last = []
    b = bars([100.0 + i for i in range(1500)])

    def decide(window):
        seen_last.append(window[-1]["c"])
        return {"side": "long", "hold_minutes": 10}
    simulate(b, decide, window=1440)
    # first call sees bars[0:1440]; its last close is bar 1439, never 1440 or later
    assert seen_last[0] == 100.0 + 1439


def test_trades_pay_both_fees_and_do_not_overlap():
    flat = bars([100.0] * 1500)
    r = simulate(flat, lambda w: {"side": "long", "hold_minutes": 30}, window=1440)
    assert r["pnl_bps"] and all(p == pytest.approx(-8.0) for p in r["pnl_bps"])
    assert len(r["pnl_bps"]) == 2              # entered at 1440 and 1470: one at a time, never overlapping


def test_a_crashing_decide_counts_as_no_trade_and_is_reported():
    r = simulate(bars([100.0] * 1500), lambda w: 1 / 0, window=1440)
    assert r["pnl_bps"] == [] and r["decide_errors"] > 0 and "ZeroDivisionError" in r["first_error"]


def test_only_aggregates_come_back():
    a = aggregate([5.0, -3.0, 2.0, -8.0, 1.0, 4.0])
    assert set(a) == {"trades", "net_bps_per_trade", "hit_rate", "total_net_bps", "ci95_net_bps_per_trade"}


TOKENS = {"t1": {"id": "trader-1", "role": "trader"}, "m": {"id": "manager", "role": "manager"}}
H = lambda tok: {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def office(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "CACHE", tmp_path / "heldout")
    calls = []

    def fake_runner(bars_path, code):
        calls.append(code)
        return {"trades": 3, "net_bps_per_trade": -2.0}
    store = Store(str(tmp_path / "o.db"))
    return TestClient(create_app(store, FakeMarket(), TOKENS, backstop_every_s=0, eval_runner=fake_runner)), calls


def test_a_trader_gets_a_few_tries_a_day(office):
    c, calls = office
    for i in range(service.PER_DAY):
        r = c.post("/evaluate", json={"code": "def decide(b): return None"}, headers=H("t1"))
        assert r.status_code == 200 and r.json()["evaluations_used_today"] == i + 1
    r = c.post("/evaluate", json={"code": "def decide(b): return None"}, headers=H("t1"))
    assert r.status_code == 409 and len(calls) == service.PER_DAY


def test_simultaneous_calls_cannot_share_a_try(office):
    import concurrent.futures as cf
    c, calls = office
    with cf.ThreadPoolExecutor(8) as ex:
        rs = list(ex.map(lambda _: c.post("/evaluate", json={"code": "def decide(b): return None"}, headers=H("t1")),
                         range(service.PER_DAY + 3)))
    used = sorted(r.json()["evaluations_used_today"] for r in rs if r.status_code == 200)
    assert used == list(range(1, service.PER_DAY + 1)) and len(calls) == service.PER_DAY


def test_iterations_tie_evaluations_to_the_version_they_were_made_under(office):
    c, calls = office
    c.post("/report", json={"kind": "version", "payload": {"version": "v1", "objects": ["should_wake"]}}, headers=H("t1"))
    c.post("/evaluate", json={"code": "def decide(b): return None", "version": "v1"}, headers=H("t1"))
    c.post("/report", json={"kind": "version", "payload": {"version": "v2", "objects": ["should_wake", "decide"]}}, headers=H("t1"))
    c.post("/evaluate", json={"code": "def decide(b): return 1", "version": "v2"}, headers=H("t1"))
    t = c.get("/iterations").json()["trader-1"]
    assert [v["version"] for v in t["versions"]] == ["v1", "v2"]
    assert [len(v["evaluations"]) for v in t["versions"]] == [1, 1]
    assert t["versions"][0]["evaluations"][0]["candidate"] != t["versions"][1]["evaluations"][0]["candidate"]
    assert t["summary"] == {"versions": 2, "evaluations": 2, "best_net_bps_per_trade": -2.0,
                            "latest_net_bps_per_trade": -2.0, "any_interval_above_zero": False}


def test_only_traders_submit(office):
    c, calls = office
    assert c.post("/evaluate", json={"code": "x"}, headers=H("m")).status_code == 409 and not calls

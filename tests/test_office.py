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
    assert p["entry_px"] == 80_000.5                 # a market buy pays the ask
    m.prices["PF_XBTUSD"] = 80_020.0               # moved the right way, by less than the fee
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
        m.prices["PF_XBTUSD"] = 80_000.0
        p = c.post("/positions/open", json={"side": "long", "size": 0.005, "strategy_version": version}, headers=H("t1")).json()
        m.prices["PF_XBTUSD"] = exit_px
        c.post(f"/positions/{p['id']}/close", headers=H("t1"))
    b = c.get("/leaderboard").json()
    by_emp = {r["employee"]: r for r in b["by_employee"]}
    assert by_emp["trader-2"]["trades"] == 0                     # on the roster, not in the data: still listed
    assert by_emp["trader-1"]["trades"] == 2
    versions = {r["strategy_version"]: r for r in b["by_version"]}
    assert versions["v1"]["net_pnl"] < 0 < versions["v2"]["net_pnl"]



def test_the_manager_hands_a_trader_tasks_and_reads_the_result(office):
    c, _, _ = office
    t = c.post("/tasks", json={"to": "trader-1", "text": "backtest a 30m fade"}, headers=H("m"))
    assert t.status_code == 200
    assert c.post("/tasks", json={"to": "trader-1", "text": "x"}, headers=H("t1")).status_code == 403
    tid = t.json()["id"]
    assert c.get(f"/tasks/{tid}").json()["status"] == "pending"
    c.post("/report", json={"kind": "task_result", "payload": {"task": tid, "summary": "-6 bps"}}, headers=H("t1"))
    r = c.get(f"/tasks/{tid}").json()
    assert r["status"] == "done" and r["summary"] == "-6 bps" and r["by"] == "trader-1"


def test_only_the_boss_closes_a_seat(tmp_path):
    tokens = {k: dict(v) for k, v in TOKENS.items()}
    c = TestClient(create_app(Store(str(tmp_path / "o.db")), FakeMarket(), tokens, backstop_every_s=0))
    assert c.post("/employees/trader-2/fire", json={"reason": "x", "replace": False}, headers=H("m")).status_code == 409
    r = c.post("/employees/trader-2/fire", json={"reason": "one trader for now", "replace": False}, headers=H("b"))
    assert r.status_code == 200 and r.json()["successor"] is None and "t2" not in tokens
    assert c.get("/me", headers=H("t2")).status_code == 401


def test_the_objective_ladder_starts_at_the_bottom_and_climbs_on_the_record(office):
    c, _, store = office
    o = c.get("/objective").json()
    assert o["rung"] == 0 and o["next"].startswith("a candidate")
    for data, bps in (("train", 1.2), ("recent", 0.4)):
        store.emit("trader-1", "backtest", {"data": data, "days": 6, "trades": 40, "net_bps_per_trade": bps,
                                            "candidate": "abc", "error": None})
    o = c.get("/objective").json()
    assert o["rung"] == 1 and o["rungs"][0]["best"]["both_windows_min_bps"] == 0.4


def test_the_shared_repl_takes_code_from_the_manager_and_returns_output(office):
    c, _, _ = office
    assert c.post("/repl", json={"code": "print(1)"}, headers=H("t1")).status_code == 403
    r = c.post("/repl", json={"code": "x = 2\nprint(x)"}, headers=H("m")).json()
    assert r["kind"] == "repl" and r["payload"]["lines"] == 2
    assert c.get(f"/repl/{r['id']}").json()["status"] == "pending"
    c.post("/report", json={"kind": "repl_result", "payload": {"req": r["id"], "stdout": "2\n", "stderr": ""}}, headers=H("t1"))
    assert c.get(f"/repl/{r['id']}").json()["stdout"] == "2\n"


def test_lookback_reviews_run_at_office_times_once_each(office):
    from datetime import datetime, timezone
    from server import scheduler
    _, _, store = office
    t = datetime(2026, 10, 10, 10, 2, tzinfo=timezone.utc)          # 12:02 Budapest (CEST)
    assert scheduler.review_tick(store, t)["daily"] is False
    assert scheduler.review_tick(store, t.replace(minute=5)) is None              # once
    assert scheduler.review_tick(store, t.replace(hour=11)) is None               # not a review time
    d = scheduler.review_tick(store, datetime(2026, 10, 10, 21, 31, tzinfo=timezone.utc))   # 23:31
    assert d["daily"] is True and d["since"].startswith("2026-10-10T10:02")


def test_market_context_is_served(office):
    c, _, _ = office
    rows = c.get("/market/context?minutes=5").json()
    assert len(rows) == 5 and {"flow_imb", "taker_buy", "trades"} <= set(rows[0])

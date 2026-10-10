"""The held-out evaluator: what it lets a strategy see, what it charges, and what it reveals."""
import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.evaluator import service
from server.evaluator.sim import aggregate, simulate
from server.market import FakeMarket
from server.store import Store


def bars(prices):
    return [{"m": f"2026-08-{1 + i // 1440:02d} {(i // 60) % 24:02d}:{i % 60:02d}:00", "o": p, "h": p, "l": p, "c": p,
             "v": 1.0} for i, p in enumerate(prices)]


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
    from server.settlement import settle
    flat = bars([80_000.0] * 1500)
    r = simulate(flat, lambda w: {"side": "long", "hold_minutes": 30}, window=1440)
    # taker both ways at Kraken tier 1, buying at the ask and selling at the bid (1 USD spread)
    expected = settle("long", 1.0, 80_000.5, 79_999.5).pnl_bps
    assert r["pnl_bps"] and all(p == pytest.approx(expected) for p in r["pnl_bps"])
    assert -11.5 < expected < -10
    assert len(r["pnl_bps"]) == 2              # entered at 1440 and 1470: one at a time, never overlapping


def test_a_limit_entry_needs_the_price_traded_through_and_pays_maker():
    from server.settlement import settle
    prices = [80_000.0] * 1450 + [79_990.0] * 50          # dips 10 USD: a 1-bp-below limit (79,992) fills
    b = bars(prices)
    for i in range(1450, 1500):
        b[i]["l"] = 79_990.0
    r = simulate(b, lambda w: {"side": "long", "hold_minutes": 5, "entry": "limit", "offset_bps": 1, "ttl_minutes": 30},
                 window=1440)
    assert r["maker_entries"] >= 1
    assert r["pnl_bps"][0] == pytest.approx(settle("long", 1.0, 79_992.0, 79_989.5, "maker", "taker").pnl_bps)
    never = simulate(bars([80_000.0] * 1500), lambda w: {"side": "long", "hold_minutes": 5, "entry": "limit",
                                                          "offset_bps": 5, "ttl_minutes": 30}, window=1440)
    assert never["pnl_bps"] == [] and never["unfilled_limit_entries"] > 0


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

    def fake_runner(bars_path, code, detail=False):
        if "precheck" in str(bars_path):
            return {"error": "your code failed to load: SyntaxError"} if "syntax" in code else {"trades": 0}
        calls.append(code)
        return {"trades": 3, "net_bps_per_trade": -2.0, **({"trade_list": []} if detail else {})}
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


def test_broken_code_comes_back_without_spending_a_try(office):
    c, calls = office
    r = c.post("/evaluate", json={"code": "syntax error here"}, headers=H("t1"))
    assert r.status_code == 409 and "no try spent" in r.json()["detail"] and not calls
    r = c.post("/evaluate", json={"code": "def decide(b): return None"}, headers=H("t1"))
    assert r.json()["evaluations_used_today"] == 1


def test_backtests_are_the_research_tool_not_the_exam(office):
    c, calls = office
    for who in ("t1", "m"):
        r = c.post("/backtest", json={"code": "def decide(b): return None", "data": "recent", "days": 3}, headers=H(who))
        assert r.status_code == 200 and "trade_list" in r.json() and "hypothesis" in r.json()["note"]
    assert c.post("/backtest", json={"code": "x", "data": "heldout"}, headers=H("t1")).status_code == 409
    r = c.post("/evaluate", json={"code": "def decide(b): return None"}, headers=H("t1"))
    assert r.json()["evaluations_used_today"] == 1                      # backtests spent no evaluation


def test_take_profit_exits_as_maker_and_the_stop_comes_first():
    from server import fees
    up = bars([80_000.0] * 1440 + [80_000.0, 80_050.0, 80_100.0, 80_200.0] + [80_200.0] * 100)
    r = simulate(up, lambda w: {"side": "long", "hold_minutes": 60, "take_profit_bps": 10}, window=1440, step=10_000)
    assert r["trades"][0]["exit"] == "take_profit"
    entry, tp = 80_000.5, round(80_000.5 * 1.001)
    expect = ((tp - entry) - fees.TAKER * entry - fees.MAKER * tp) / entry * 1e4
    assert r["pnl_bps"][0] == pytest.approx(expect, abs=0.01)
    both = bars([80_000.0] * 1440 + [80_000.0] * 101)
    both[1441] = {**both[1441], "h": 80_500.0, "l": 79_500.0}
    r = simulate(both, lambda w: {"side": "long", "hold_minutes": 60, "take_profit_bps": 10, "stop_loss_bps": 10},
                 window=1440, step=10_000)
    assert r["trades"][0]["exit"] == "stop" and r["pnl_bps"][0] < -10

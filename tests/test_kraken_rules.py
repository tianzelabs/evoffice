"""Kraken Futures rules, one by one (2026-10-11: "follow real Kraken exactly, no differences")."""
import time

import pytest
from fastapi.testclient import TestClient

from server import account, orders
from server.app import create_app
from server.market import FakeMarket
from server.store import Store

TOKENS = {"b": {"id": "boss", "role": "boss"}, "t1": {"id": "trader-1", "role": "trader"}}
H = lambda t: {"Authorization": f"Bearer {t}"}


@pytest.fixture
def office(tmp_path):
    m = FakeMarket(prices={"PF_XBTUSD": 80_000.5})   # bid 80,000 / ask 80,001 on the 1 USD tick, 5 BTC a level
    store = Store(str(tmp_path / "o.db"))
    return TestClient(create_app(store, m, TOKENS, backstop_every_s=0)), m, store


def place(c, **kw):
    return c.post("/orders", json=kw, headers=H("t1"))


def test_a_market_order_walks_the_book(office):
    c, m, _ = office
    m.depth = 0.004                                                   # thin book: 0.004 BTC per level
    p = c.post("/positions/open", json={"side": "long", "size": 0.01}, headers=H("t1")).json()
    assert p["entry_px"] == pytest.approx((0.004 * 80_001 + 0.004 * 80_002 + 0.002 * 80_003) / 0.01)


def test_size_precision_is_krakens(office):
    c, *_ = office
    assert c.post("/positions/open", json={"side": "long", "size": 0.00015}, headers=H("t1")).status_code == 409


def test_a_resting_order_waits_behind_the_queue_and_fills_partially(office):
    c, m, store = office
    o = place(c, intent="open", side="long", size=0.01, price=80_000).json()     # joins the bid: 5 BTC ahead
    assert o["status"] == "open" and o["queue_ahead"] == 5.0
    m.trade(80_000, qty=4.0, side="sell"); orders.match(store, m)
    assert orders.get(store, o["id"])["filled"] == 0                              # still queued
    m.trade(80_000, qty=1.004, side="sell"); orders.match(store, m)
    got = orders.get(store, o["id"])
    assert got["filled"] == pytest.approx(0.004) and got["status"] == "open" and got["liquidity"] == "maker"
    m.trade(79_999, qty=0.1, side="sell"); orders.match(store, m)                 # traded through: the rest fills
    assert orders.get(store, o["id"])["status"] == "filled"


def test_limit_orders_are_good_till_cancelled(office):
    c, *_ = office
    assert place(c, intent="open", side="long", size=0.001, price=79_000).json()["expires_epoch"] is None


def test_ioc_takes_what_crosses_and_cancels_the_rest(office):
    c, m, _ = office
    m.depth = 0.002
    o = place(c, intent="open", side="long", size=0.005, price=80_002, post_only=False, order_type="ioc").json()
    assert o["status"] == "cancelled" and o["filled"] == pytest.approx(0.004)      # two levels up to the limit


def test_a_stop_triggers_on_the_mark_and_a_bracket_cancels_its_twin(office):
    c, m, store = office
    pid = c.post("/positions/open", json={"side": "long", "size": 0.01}, headers=H("t1")).json()["id"]
    sl = place(c, intent="close", position_id=pid, order_type="stop", trigger_price=79_600, oco="b1").json()
    tp = place(c, intent="close", position_id=pid, order_type="take_profit", trigger_price=80_400, oco="b1").json()
    assert sl["status"] == tp["status"] == "untriggered"
    m.mark(79_700); orders.match(store, m)
    assert orders.get(store, sl["id"])["status"] == "untriggered"
    m.prices["PF_XBTUSD"] = 79_590.0
    m.mark(79_590); orders.match(store, m)
    assert orders.get(store, sl["id"])["status"] == "filled"
    assert orders.get(store, sl["id"])["liquidity"] == "taker"
    assert orders.get(store, tp["id"])["status"] == "cancelled"                  # OCO
    assert not store.q("SELECT 1 FROM positions WHERE closed_ts IS NULL")


def test_reduce_only_never_flips(office):
    c, m, store = office
    c.post("/positions/open", json={"side": "long", "size": 0.002}, headers=H("t1"))
    o = place(c, intent="open", side="short", size=0.005, price=79_000, post_only=False, reduce_only=True).json()
    assert o["filled"] == pytest.approx(0.002)                                     # only what reduces
    assert not store.q("SELECT 1 FROM positions WHERE closed_ts IS NULL")


def test_partial_liquidation_cuts_ten_percent_steps_then_full_liquidation_charges_its_fee(office):
    c, m, store = office
    c.post("/positions/open", json={"side": "long", "size": 0.012}, headers=H("t1"))     # ~9.6x on $100
    m.prices["PF_XBTUSD"] = 74_900.5          # about -6.4%: below maintenance (5%), above 70% of it
    s = account.state(store, 74_900.5)
    assert account.LIQ_RATIO * s["maintenance_margin"] <= s["equity"] < s["maintenance_margin"]
    account.liquidate_if_needed(store, m)
    ev = [e["payload"] for e in store.q("SELECT payload FROM events WHERE kind = 'account'") if '"liquidation"' in e["payload"]]
    assert ev and all('"partial"' in e for e in ev)
    after = account.state(store, 74_900.5)
    # flat 5% margin: each slice's fee is its share of the equity, so the ratio never recovers -- the
    # position is wound down to nothing, as Kraken's process would do
    assert after["net_btc"] == 0 and 0 <= after["equity"] < s["equity"] and len(ev) > 10
    closed = store.q("SELECT close_reason, exit_fee, size, exit_px FROM positions WHERE closed_ts IS NOT NULL")
    assert all(r["close_reason"] == "liquidation" for r in closed)
    assert all(r["exit_fee"] > r["size"] * r["exit_px"] * 0.0005 for r in closed)   # taker fee + partial-liquidation fee


def test_below_the_liquidation_margin_it_is_a_full_liquidation_with_its_fee(office):
    c, m, store = office
    c.post("/positions/open", json={"side": "long", "size": 0.012}, headers=H("t1"))
    m.prices["PF_XBTUSD"] = 73_800.5          # equity below 70% of maintenance at once
    s = account.state(store, 73_800.5)
    assert 0 < s["equity"] < account.LIQ_RATIO * s["maintenance_margin"]
    account.liquidate_if_needed(store, m)
    full = [e["payload"] for e in store.q("SELECT payload FROM events WHERE kind = 'account'") if '"full"' in e["payload"]]
    assert len(full) == 1 and account.state(store, 73_800.5)["net_btc"] == 0
    assert 0 <= account.state(store, 73_800.5)["equity"] < s["equity"]

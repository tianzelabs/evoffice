"""Limit orders on the simulated Kraken book: maker fees, but only honest fills."""
import pytest
from fastapi.testclient import TestClient

from server import orders
from server.app import create_app
from server.market import FakeMarket
from server.store import Store

TOKENS = {"t1": {"id": "trader-1", "role": "trader"}, "t2": {"id": "trader-2", "role": "trader"}}
H = lambda t: {"Authorization": f"Bearer {t}"}


@pytest.fixture
def office(tmp_path):
    m = FakeMarket()                      # mid 80,000, bid 79,999.5, ask 80,000.5
    store = Store(str(tmp_path / "o.db"))
    return TestClient(create_app(store, m, TOKENS, backstop_every_s=0)), m, store


def place(c, **kw):
    return c.post("/orders", json=kw, headers=H("t1"))


def test_a_market_order_buys_at_the_ask_and_pays_taker(office):
    c, m, _ = office
    p = c.post("/positions/open", json={"side": "long", "size": 0.005}, headers=H("t1")).json()
    assert p["entry_px"] == 80_000.5 and p["entry_liq"] == "taker"
    assert p["entry_fee"] == pytest.approx(0.005 * 80_000.5 * 0.0005)


def test_post_only_that_would_cross_is_rejected(office):
    c, *_ = office
    o = place(c, intent="open", side="long", size=0.005, price=80_001).json()
    assert o["status"] == "rejected"


def test_a_plain_limit_that_crosses_fills_now_as_taker_at_the_best_price(office):
    c, _, store = office
    o = place(c, intent="open", side="long", size=0.005, price=80_010, post_only=False).json()
    assert o["status"] == "filled" and o["liquidity"] == "taker" and o["fill_price"] == 80_000.5


def test_resting_orders_fill_only_when_traded_through(office):
    c, m, store = office
    o = place(c, intent="open", side="long", size=0.005, price=79_990).json()
    assert o["status"] == "open"
    m.trade(79_990)                                              # touch: not enough
    orders.match(store, m)
    assert orders.get(store, o["id"])["status"] == "open"
    m.trade(79_989)                                              # through: filled, at the limit, as maker
    orders.match(store, m)
    got = orders.get(store, o["id"])
    assert (got["status"], got["fill_price"], got["liquidity"]) == ("filled", 79_990, "maker")
    pos = store.q("SELECT * FROM positions")[0]
    assert pos["entry_liq"] == "maker" and pos["entry_fee"] == pytest.approx(0.005 * 79_990 * 0.0002)


def test_a_maker_close_settles_with_both_legs_priced_right(office):
    c, m, store = office
    pos = c.post("/positions/open", json={"side": "long", "size": 0.005}, headers=H("t1")).json()
    o = place(c, intent="close", position_id=pos["id"], price=80_100).json()
    m.trade(80_101)
    orders.match(store, m)
    closed = store.q("SELECT * FROM positions WHERE id = ?", (pos["id"],))[0]
    assert closed["exit_liq"] == "maker" and closed["exit_px"] == 80_100
    expected_fees = 0.005 * 80_000.5 * 0.0005 + 0.005 * 80_100 * 0.0002
    assert closed["fees"] == pytest.approx(expected_fees)
    assert closed["pnl"] == pytest.approx(0.005 * (80_100 - 80_000.5) - expected_fees)


def test_cancel_and_expiry(office):
    c, m, store = office
    o = place(c, intent="open", side="short", size=0.005, price=80_050).json()
    assert c.post(f"/orders/{o['id']}/cancel", headers=H("t2")).status_code == 409    # not yours
    assert c.post(f"/orders/{o['id']}/cancel", headers=H("t1")).json()["status"] == "cancelled"
    o2 = place(c, intent="open", side="short", size=0.005, price=80_050, ttl_minutes=1).json()
    store.x("UPDATE orders SET expires_epoch = 0 WHERE id = ?", (o2["id"],))
    orders.match(store, m)
    assert orders.get(store, o2["id"])["status"] == "expired"


def test_tick_size_and_order_count_limits(office):
    c, *_ = office
    assert place(c, intent="open", side="long", size=0.005, price=79_990.5).status_code == 409
    for i in range(orders.MAX_OPEN_ORDERS):
        assert place(c, intent="open", side="long", size=0.005, price=79_900 - i).json()["status"] == "open"
    assert place(c, intent="open", side="long", size=0.005, price=79_800).status_code == 409


def test_closing_a_position_cancels_its_resting_close_order(office):
    c, m, store = office
    pos = c.post("/positions/open", json={"side": "long", "size": 0.005}, headers=H("t1")).json()
    o = place(c, intent="close", position_id=pos["id"], price=80_200).json()
    c.post(f"/positions/{pos['id']}/close", headers=H("t1"))
    assert orders.get(store, o["id"])["status"] == "cancelled"


def test_funding_is_charged_hourly_once(office):
    from datetime import datetime, timezone
    from server import funding
    c, m, store = office
    c.post("/positions/open", json={"side": "long", "size": 0.005}, headers=H("t1"))
    m.funding = 0.0001                                          # longs pay 1 bp an hour
    store.x("UPDATE positions SET opened_ts = '2020-01-01T00:00:00+00:00'")
    t = datetime(2026, 10, 10, 9, 1, tzinfo=timezone.utc)
    assert len(funding.apply(store, m, t)) == 1
    assert funding.apply(store, m, t) == []                     # once per hour
    assert store.q("SELECT funding FROM positions")[0]["funding"] == pytest.approx(-0.0001 * 0.005 * 80_000)


def test_best_joins_the_book_as_it_is_when_the_order_arrives(office):
    c, *_ = office
    o = place(c, intent="open", side="long", size=0.005, price="best").json()
    assert o["status"] == "open" and o["price"] == 79_999.5          # the bid at that moment: rests, never crosses
    assert place(c, intent="open", side="long", size=0.005, price="mid").status_code == 409

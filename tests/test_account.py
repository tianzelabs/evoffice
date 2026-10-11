"""The $100 account under Kraken EU retail margin: size by margin, liquidation, a blown account."""
import pytest
from fastapi.testclient import TestClient

from server import account
from server.app import create_app
from server.market import FakeMarket
from server.store import Store

TOKENS = {"b": {"id": "boss", "role": "boss"}, "t1": {"id": "trader-1", "role": "trader"}}
H = lambda t: {"Authorization": f"Bearer {t}"}


@pytest.fixture
def office(tmp_path):
    m = FakeMarket()
    store = Store(str(tmp_path / "o.db"))
    return TestClient(create_app(store, m, TOKENS, backstop_every_s=0)), m, store


def test_equity_marks_to_market_and_leverage_is_on_notional(office):
    c, m, _ = office
    c.post("/positions/open", json={"side": "long", "size": 0.01}, headers=H("t1"))      # $800 notional on $100
    m.prices["PF_XBTUSD"] = 80_800.0                                                   # +1%
    a = c.get("/account").json()
    assert a["equity"] == pytest.approx(100 + 0.01 * (80_800 - 80_000.5) - 0.01 * 80_000.5 * 0.0005, abs=0.01)
    assert a["leverage"] == pytest.approx(0.01 * 80_800 / a["equity"], rel=1e-3) and a["goal"] == 200


def test_below_maintenance_the_office_liquidates_and_an_empty_account_is_blown(office):
    c, m, store = office
    c.post("/positions/open", json={"side": "long", "size": 0.012}, headers=H("t1"))     # ~9.6x
    m.prices["PF_XBTUSD"] = 79_500.0                                                   # -0.6%: equity ~ $43 > 5% of $954
    assert account.liquidate_if_needed(store, m) == []
    m.prices["PF_XBTUSD"] = 70_000.0                                                   # -12.5% gap: below zero
    assert len(account.liquidate_if_needed(store, m)) == 1
    a = c.get("/account").json()
    assert a["blown"] and a["net_btc"] == 0 and a["equity"] == 0          # Kraken's insurance fund takes the rest
    assert c.post("/positions/open", json={"side": "long", "size": 0.001}, headers=H("t1")).status_code == 409
    assert c.post("/account/start", json={"equity": 100, "reason": "again"}, headers=H("t1")).status_code == 403
    assert c.post("/account/start", json={"equity": 100, "reason": "again"}, headers=H("b")).status_code == 200
    assert not c.get("/account").json()["blown"]
    assert c.post("/positions/open", json={"side": "long", "size": 0.001}, headers=H("t1")).status_code == 200

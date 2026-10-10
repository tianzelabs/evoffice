"""The live switch stays off until everything is earned -- and even then is not wired."""
import pytest

from server import broker
from server.store import Store


def test_a_new_trader_is_nowhere_near_live(tmp_path):
    s = Store(str(tmp_path / "o.db"))
    s.hire("trader-1", "trader")
    c = broker.checklist(s, "trader-1")
    assert not c["ready"] and not c["items"][0]["ok"]
    with pytest.raises(broker.LiveDisabled):
        broker.KrakenLive(s).submit("trader-1", "buy", 0.001)


def test_an_edge_under_the_old_fees_does_not_count(tmp_path):
    s = Store(str(tmp_path / "o.db"))
    s.hire("trader-1", "trader")
    s.emit("trader-1", "evaluation", {"net_bps_per_trade": 5.0, "ci95_net_bps_per_trade": [1.0, 9.0], "version": "v1"})
    assert not broker.checklist(s, "trader-1")["items"][0]["ok"]          # no regime: legacy spot-4bps

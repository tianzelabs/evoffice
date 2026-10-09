"""Seasons: scored on their own week, awarded once, and only to someone who earned it."""
from datetime import datetime, timezone

from server import seasons
from server.store import Store


def test_a_season_is_an_iso_week_and_awards_are_given_once(tmp_path):
    s = Store(str(tmp_path / "o.db"))
    s.hire("trader-1", "trader")
    s.hire("trader-2", "trader")
    season = seasons.season_of(datetime.now(timezone.utc))
    s.emit("trader-1", "evaluation", {"trades": 10, "net_bps_per_trade": -3.0, "ci95_net_bps_per_trade": [-6.0, 0.5]})
    s.emit("trader-1", "evaluation", {"trades": 10, "net_bps_per_trade": 2.0, "ci95_net_bps_per_trade": [-1.0, 5.0]})
    first = seasons.award(s, season)
    assert {a["payload"]["award"] for a in first} == {"iterator", "best_heldout", "experimenter"}   # no trades: no top_pnl
    assert all(a["actor"] == "trader-1" for a in first)
    assert seasons.award(s, season) == []                                                          # once
    assert len(seasons.summary(s)["trophies"]["trader-1"]) == 3


def test_an_empty_season_awards_nobody(tmp_path):
    s = Store(str(tmp_path / "o.db"))
    s.hire("trader-1", "trader")
    assert seasons.award(s, "2020-W01") == []
    assert "trader-1" not in seasons.summary(s)["trophies"]

"""The office clock: one stand-up a day with an end, and alerts on real moves with a cooldown."""
from datetime import datetime, timedelta, timezone

from server import scheduler
from server.market import FakeMarket
from server.store import Store

T0 = datetime(2026, 10, 10, 7, 30, 5, tzinfo=timezone.utc)


def kinds(store, kind):
    return [e["payload"] for e in store.events_since(0) if e["kind"] == kind]


def test_one_standup_a_day_and_it_ends(tmp_path):
    s = Store(str(tmp_path / "o.db"))
    assert scheduler.meeting_tick(s, T0 - timedelta(minutes=5)) is None
    assert scheduler.meeting_tick(s, T0) == "start"
    assert scheduler.meeting_tick(s, T0 + timedelta(minutes=1)) is None          # not twice
    assert scheduler.meeting_tick(s, T0 + timedelta(minutes=scheduler.MEETING_MINUTES)) == "end"
    assert scheduler.meeting_tick(s, T0 + timedelta(minutes=25)) is None          # not restarted the same day
    assert [p["phase"] for p in kinds(s, "meeting")] == ["start", "end"]


class Moving(FakeMarket):
    def __init__(self, closes):
        super().__init__()
        self.closes = closes

    def bars(self, pair, minutes):
        return [{"m": str(i), "o": c, "h": c, "l": c, "c": c, "v": 1.0} for i, c in enumerate(self.closes)]


def test_a_quiet_market_raises_nothing_and_a_jump_raises_one_alert(tmp_path):
    s = Store(str(tmp_path / "o.db"))
    assert scheduler.alert_tick(s, Moving([80_000.0] * 8), T0) is None
    jump = Moving([80_000.0] * 3 + [80_000.0, 80_100.0, 80_200.0, 80_300.0, 80_400.0])   # +50 bps in 5 min
    a = scheduler.alert_tick(s, jump, T0)
    assert a and a["move_5m_bps"] >= 40
    assert scheduler.alert_tick(s, jump, T0 + timedelta(minutes=10)) is None      # cooldown
    assert scheduler.alert_tick(s, jump, T0 + timedelta(minutes=50)) is not None

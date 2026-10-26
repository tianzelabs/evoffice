"""Longer-horizon briefing must be causal and honest about gaps and reversals."""
from datetime import datetime, timedelta, timezone

import pytest

from agents.manager.market_view import market_briefing, market_view

T0 = datetime(2026, 10, 12, 0, 0, tzinfo=timezone.utc)


def candles(prices):
    return [{"m": (T0 + timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M:%S"), "c": price}
            for i, price in enumerate(prices)]


def test_full_horizons_exclude_unclosed_and_future_candles():
    bars = candles([100.0 + i / 100 for i in range(1443)])
    now = T0 + timedelta(minutes=1441)
    view = market_view(bars, now)
    assert view["latest_close"] == 114.4
    assert view["latest_close_age_s"] == 0
    for hours in (1, 4, 8, 24):
        h = view["horizons"][str(hours)]
        assert h["actual_minutes"] == hours * 60
        assert h["observed_closes"] == hours * 60 + 1
        assert h["continuous"] and h["anchor_gap_minutes"] == 0
        assert h["change_bps"] == pytest.approx(round((114.4 / (100 + (1440-hours*60)/100)-1)*1e4, 2))


def test_missing_anchor_staleness_and_short_history_are_explicit():
    bars = candles([100.0] * 481)
    del bars[240]
    view = market_view(bars, T0 + timedelta(minutes=486))
    assert view["stale"] and view["latest_close_age_s"] == 300
    h = view["horizons"]["4"]
    assert h["actual_minutes"] == 241 and h["anchor_gap_minutes"] == 1
    assert not h["continuous"] and h["missing_minutes"] == 1
    assert not view["horizons"]["24"]["available"]


def test_a_falling_path_can_contain_a_large_countertrend_rebound():
    prices = [100.] * 200 + [90.] * 100 + [96.] * 180 + [92.]
    view = market_view(candles(prices), T0 + timedelta(minutes=481))
    h = view["horizons"]["8"]
    assert h["change_bps"] == -800
    assert h["largest_close_rebound_bps"] == pytest.approx(666.67)
    assert h["largest_close_drawdown_bps"] == 1000


def test_missing_feed_does_not_abort_the_briefing():
    class Unavailable:
        def bars(self, minutes):
            raise RuntimeError("feed unavailable")
    text = market_briefing(Unavailable())
    assert 'UNAVAILABLE' in text and "feed unavailable" in text


def test_reports_persist_cache_and_compare_without_model_calls(tmp_path):
    import json
    class ReadOnlyFeed:
        calls = 0
        data = candles([100.] * 1442)
        def bars(self, minutes):
            self.calls += 1
            return self.data
    feed = ReadOnlyFeed()
    now = T0 + timedelta(minutes=1441)
    text = market_briefing(feed, tmp_path, now)
    assert '| 8h |' in text and 'observed context, not a forecast' in text
    assert (tmp_path/'market-report.md').read_text().strip() == text
    assert json.loads((tmp_path/'market-report.json').read_text())['schema_version'] == 1
    assert 'Cached report' in market_briefing(feed, tmp_path, now+timedelta(seconds=20))
    assert feed.calls == 1
    feed.data[-1]['c'] = 101.
    market_briefing(feed, tmp_path, now+timedelta(minutes=1))
    saved = json.loads((tmp_path/'market-report.json').read_text())
    assert saved['since_previous_report']['price_change_bps'] == 100
    assert feed.calls == 2
    assert len((tmp_path/'market-report-history.jsonl').read_text().splitlines()) == 2


def test_corrupt_cache_and_feed_failure_never_reuse_stale_success(tmp_path):
    import json
    (tmp_path/'market-report.json').write_text('{broken')
    class Unavailable:
        def bars(self, minutes):raise RuntimeError('offline')
    text = market_briefing(Unavailable(),tmp_path,T0)
    assert 'UNAVAILABLE' in text and 'Report cache ignored' in text
    assert not json.loads((tmp_path/'market-report.json').read_text())['available']

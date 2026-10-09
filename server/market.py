"""Prices from agent-world's ClickHouse feed -- read-only, never fabricated.

Carried in spirit from agent-world `village/market.py`, rewritten because that
file's docstring promised `None` on a gap while the code raised, and its replay
fake had dead code. One rule here, enforced rather than documented:

**A price is the last trade, and only if it is fresh.** If the newest trade is
older than the tolerance, the feed has a gap, and a gap is not a price: the
answer is `Stale`, and the caller refuses to fill rather than fill at an old print.
"""
from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field

FRESH_S = 15.0   # BTC/USD trades continuously; older than this is a feed gap


class Stale(Exception):
    """No trade within the freshness tolerance. Refuse; do not guess."""


@dataclass(frozen=True)
class Quote:
    pair: str
    price: float
    age_s: float


PAIRS = ("BTC/USD", "ETH/USD", "SOL/USD")
MAX_BARS_MINUTES = 7 * 24 * 60


class ClickHouseMarket:
    """Shells out to clickhouse-client, as the rest of agent-world does, rather
    than taking a driver dependency for a few small reads."""

    def __init__(self, database: str = "traderme", timeout: int = 20):
        self.database, self.timeout = database, timeout

    def _query(self, sql: str) -> str:
        env = dict(os.environ)
        env.setdefault("CLICKHOUSE_PASSWORD", "clickhouse")
        r = subprocess.run(["clickhouse-client", "--query", sql], capture_output=True, text=True,
                           timeout=self.timeout, env=env)
        if r.returncode != 0:
            raise Stale(f"clickhouse-client failed: {(r.stderr or '').strip()[:200]}")
        return r.stdout.strip()

    def bars(self, pair: str, minutes: int) -> list[dict]:
        """Closed 1-minute bars, oldest first. Minutes with no trade are absent, not filled.
        Capped at 7 days: what lies further back is the held-out window (server/evaluator)."""
        return self.bars_between(pair, max(1, min(int(minutes), MAX_BARS_MINUTES)), 0)

    def bars_between(self, pair: str, from_minutes_ago: int, to_minutes_ago: int) -> list[dict]:
        """For the office's own use (the evaluator). Never exposed as a route."""
        if pair not in PAIRS:
            raise ValueError(f"unknown pair {pair!r}")
        a, b = int(from_minutes_ago), int(to_minutes_ago)
        sql = (f"SELECT toString(toStartOfMinute(ts)), argMin(price, ts), max(price), min(price), argMax(price, ts), "
               f"round(sum(qty), 6) FROM {self.database}.trades WHERE pair = '{pair}' "
               f"AND ts >= toStartOfMinute(now()) - INTERVAL {a} MINUTE AND ts < toStartOfMinute(now()) - INTERVAL {b} MINUTE "
               f"GROUP BY toStartOfMinute(ts) ORDER BY toStartOfMinute(ts) FORMAT TSV")
        out = self._query(sql)
        rows = []
        for line in out.splitlines():
            m, o, h, l, c, v = line.split("\t")
            rows.append({"m": m, "o": float(o), "h": float(h), "l": float(l), "c": float(c), "v": float(v)})
        return rows

    def quote(self, pair: str) -> Quote:
        if pair not in PAIRS:
            raise ValueError(f"unknown pair {pair!r}")   # pairs are ours; never interpolate input
        sql = (f"SELECT price, dateDiff('millisecond', ts, now64(6)) / 1000.0 "
               f"FROM {self.database}.trades WHERE pair = '{pair}' ORDER BY ts DESC LIMIT 1 FORMAT TSV")
        out = self._query(sql)
        if not out:
            raise Stale(f"no trades for {pair}")
        price_s, age_s = out.split("\t")
        q = Quote(pair, float(price_s), max(0.0, float(age_s)))
        if q.age_s > FRESH_S:
            raise Stale(f"{pair}: newest trade is {q.age_s:.1f}s old (tolerance {FRESH_S}s)")
        return q


@dataclass
class FakeMarket:
    """Deterministic market for tests: set the price, or make the feed stale."""
    prices: dict[str, float] = field(default_factory=lambda: {"BTC/USD": 80_000.0})
    stale: bool = False

    def quote(self, pair: str) -> Quote:
        if self.stale or pair not in self.prices:
            raise Stale(f"{pair}: feed stale (fake)")
        return Quote(pair, self.prices[pair], 0.0)

    def bars_between(self, pair: str, from_minutes_ago: int, to_minutes_ago: int) -> list[dict]:
        return self.bars(pair, from_minutes_ago - to_minutes_ago)

    def bars(self, pair: str, minutes: int) -> list[dict]:
        p = self.prices.get(pair, 0.0)
        return [{"m": f"2026-01-01 00:{i % 60:02d}:00", "o": p, "h": p, "l": p, "c": p, "v": 1.0} for i in range(minutes)]

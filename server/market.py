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


class ClickHouseMarket:
    """Shells out to clickhouse-client, as the rest of agent-world does, rather
    than taking a driver dependency for one scalar read."""

    def __init__(self, database: str = "traderme", timeout: int = 10):
        self.database, self.timeout = database, timeout

    def quote(self, pair: str) -> Quote:
        if pair not in ("BTC/USD", "ETH/USD", "SOL/USD"):
            raise ValueError(f"unknown pair {pair!r}")   # pairs are ours; never interpolate input
        sql = (f"SELECT price, dateDiff('millisecond', ts, now64(6)) / 1000.0 "
               f"FROM {self.database}.trades WHERE pair = '{pair}' ORDER BY ts DESC LIMIT 1 FORMAT TSV")
        env = dict(os.environ)
        env.setdefault("CLICKHOUSE_PASSWORD", "clickhouse")
        r = subprocess.run(["clickhouse-client", "--query", sql], capture_output=True, text=True,
                           timeout=self.timeout, env=env)
        if r.returncode != 0:
            raise Stale(f"clickhouse-client failed: {(r.stderr or '').strip()[:200]}")
        out = r.stdout.strip()
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

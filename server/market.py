"""Market data for the office: Kraken Futures PF_XBTUSD, read-only, never fabricated.

The user develops the agents on what a new Kraken futures account would really
get, so prices are the perpetual's own (agent-world/ingestion/futures_capture.py
and futures_backfill.py fill these tables): best bid/ask for fills, the trade
stream for limit-order fills, Kraken's own 1-minute candles for history, its
published hourly funding.

One rule, enforced rather than documented: **a quote is only a quote if it is
fresh.** Older than FRESH_S, the feed has a gap; the answer is `Stale` and the
caller refuses to fill rather than fill at an old print.
"""
from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field

FRESH_S = 15.0
PRODUCT = "PF_XBTUSD"
PAIRS = (PRODUCT,)
MAX_BARS_MINUTES = 7 * 24 * 60


class Stale(Exception):
    """No fresh quote. Refuse; do not guess."""


@dataclass(frozen=True)
class Quote:
    pair: str
    price: float          # last trade
    age_s: float
    bid: float = 0.0
    ask: float = 0.0
    mark: float = 0.0
    funding_per_hour: float = 0.0   # relative funding rate: fraction of notional, longs pay when positive


def _check(pair: str):
    if pair not in PAIRS:
        raise ValueError(f"unknown pair {pair!r}; the office trades {PRODUCT} (Kraken BTC perpetual)")


class FuturesMarket:
    """Shells out to clickhouse-client, as agent-world's ingestion does."""

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

    def quote(self, pair: str = PRODUCT) -> Quote:
        _check(pair)
        out = self._query(
            f"SELECT bid, ask, last, mark, relative_funding_rate, dateDiff('millisecond', ts, now64(3)) / 1000.0 "
            f"FROM {self.database}.futures_ticker WHERE product = '{pair}' ORDER BY ts DESC LIMIT 1 FORMAT TSV")
        if not out:
            raise Stale(f"no ticker for {pair}")
        bid, ask, last, mark, funding, age = map(float, out.split("\t"))
        if age > FRESH_S or bid <= 0 or ask <= 0:
            raise Stale(f"{pair}: newest bid/ask is {age:.1f}s old (tolerance {FRESH_S}s)")
        return Quote(pair, last, max(0.0, age), bid, ask, mark, funding)

    def bars(self, pair: str, minutes: int) -> list[dict]:
        """Closed 1-minute bars, oldest first. Capped at 7 days: what lies further back is the
        held-out window (server/evaluator)."""
        return self.bars_between(pair, max(1, min(int(minutes), MAX_BARS_MINUTES)), 0)

    def bars_between(self, pair: str, from_minutes_ago: int, to_minutes_ago: int) -> list[dict]:
        """Kraken's own candles, and for the minutes after the newest candle, bars built from
        the captured trade stream. Minutes with no trade are absent, not filled."""
        _check(pair)
        a, b = int(from_minutes_ago), int(to_minutes_ago)
        lo = f"toStartOfMinute(now()) - INTERVAL {a} MINUTE"
        hi = f"toStartOfMinute(now()) - INTERVAL {b} MINUTE"
        sql = (
            f"SELECT toString(ts), open, high, low, close, volume FROM {self.database}.futures_candles_1m FINAL "
            f"WHERE product = '{pair}' AND ts >= {lo} AND ts < {hi} AND volume > 0 "
            f"UNION ALL "
            f"SELECT toString(toStartOfMinute(ts)) AS m, argMin(price, ts), max(price), min(price), argMax(price, ts), "
            f"round(sum(qty), 6) FROM {self.database}.futures_trades "
            f"WHERE product = '{pair}' AND ts >= {lo} AND ts < {hi} AND ts >= "
            f"(SELECT max(ts) + INTERVAL 1 MINUTE FROM {self.database}.futures_candles_1m WHERE product = '{pair}') "
            f"GROUP BY m FORMAT TSV")
        rows = {}
        for line in self._query(sql).splitlines():
            m, o, h, l, c, v = line.split("\t")
            rows[m[:19]] = {"m": m[:19], "o": float(o), "h": float(h), "l": float(l), "c": float(c), "v": float(v)}
        return [rows[k] for k in sorted(rows)]

    def context(self, pair: str, minutes: int) -> list[dict]:
        """The market's state minute by minute, for studying what came BEFORE a move (2026-10-10):
        the bar, plus -- from the captured streams, so only since capture began (2026-10-10 09:00 UTC)
        -- taker buy/sell volume (Kraken's trade `side` is the taker's), trade count and largest
        trade, mean spread and top-of-book size imbalance, basis (mark vs index), the funding rate
        and open interest (from 18:00 UTC). Capped at 7 days like /bars: older is held-out."""
        _check(pair)
        n = max(1, min(int(minutes), MAX_BARS_MINUTES))
        rows = {b["m"]: dict(b) for b in self.bars_between(pair, n, 0)}
        lo = f"toStartOfMinute(now()) - INTERVAL {n} MINUTE"
        hi = "toStartOfMinute(now())"
        tr = self._query(
            f"SELECT toString(toStartOfMinute(ts)) AS m, round(sumIf(qty, side = 'buy'), 6), "
            f"round(sumIf(qty, side = 'sell'), 6), count(), max(qty) FROM {self.database}.futures_trades "
            f"WHERE product = '{pair}' AND ts >= {lo} AND ts < {hi} GROUP BY m FORMAT TSV")
        for line in tr.splitlines():
            m, b, s, c, mx = line.split("\t")
            if m[:19] in rows:
                b, s = float(b), float(s)
                rows[m[:19]].update({"taker_buy": b, "taker_sell": s, "flow_imb": round((b - s) / (b + s), 3) if b + s else 0.0,
                                     "trades": int(c), "max_trade": float(mx)})
        tk = self._query(
            f"SELECT toString(toStartOfMinute(ts)) AS m, round(avg(ask - bid), 3), "
            f"round(avg((bid_size - ask_size) / nullIf(bid_size + ask_size, 0)), 3), "
            f"round(avg((mark - index_price) / nullIf(index_price, 0) * 10000), 3), argMax(relative_funding_rate, ts), "
            f"argMax(open_interest, ts) FROM {self.database}.futures_ticker "
            f"WHERE product = '{pair}' AND ts >= {lo} AND ts < {hi} GROUP BY m FORMAT TSV")
        for line in tk.splitlines():
            m, spr, imb, basis, fr, oi = line.split("\t")
            if m[:19] in rows:
                num = lambda x: None if x in ("\\N", "nan", "") else float(x)
                rows[m[:19]].update({"spread": num(spr), "book_imb": num(imb), "basis_bps": num(basis),
                                     "funding_per_hour": num(fr), "open_interest": (num(oi) or None)})
        return [rows[k] for k in sorted(rows)]

    def trades_since(self, pair: str, since_epoch: float) -> list[tuple[float, float]]:
        """(epoch seconds, price) of every trade after `since_epoch`, oldest first -- for limit fills."""
        _check(pair)
        out = self._query(
            f"SELECT toUnixTimestamp64Milli(ts) / 1000.0, price FROM {self.database}.futures_trades "
            f"WHERE product = '{pair}' AND ts > fromUnixTimestamp64Milli(toInt64({since_epoch * 1000:.0f})) "
            f"ORDER BY ts LIMIT 100000 FORMAT TSV")
        return [tuple(map(float, l.split("\t"))) for l in out.splitlines()]

    def funding_history(self, pair: str, from_epoch: float, to_epoch: float) -> dict[int, float]:
        """{hour start epoch: relative funding rate} as Kraken published it."""
        _check(pair)
        out = self._query(
            f"SELECT toUnixTimestamp(ts), relative_funding_rate FROM {self.database}.futures_funding FINAL "
            f"WHERE product = '{pair}' AND ts >= toDateTime({int(from_epoch)}) AND ts < toDateTime({int(to_epoch)}) FORMAT TSV")
        return {int(t): float(r) for t, r in (l.split("\t") for l in out.splitlines())}


@dataclass
class FakeMarket:
    """Deterministic market for tests: a mid price, a spread, a trade tape you append to."""
    prices: dict[str, float] = field(default_factory=lambda: {PRODUCT: 80_000.0})
    spread: float = 1.0
    stale: bool = False
    funding: float = 0.0
    tape: list[tuple[float, float]] = field(default_factory=list)

    def quote(self, pair: str = PRODUCT) -> Quote:
        if self.stale or pair not in self.prices:
            raise Stale(f"{pair}: feed stale (fake)")
        p = self.prices[pair]
        return Quote(pair, p, 0.0, p - self.spread / 2, p + self.spread / 2, p, self.funding)

    def trade(self, price: float, at: float | None = None):
        self.tape.append((at if at is not None else time.time(), price))

    def trades_since(self, pair: str, since_epoch: float) -> list[tuple[float, float]]:
        return [t for t in self.tape if t[0] > since_epoch]

    def bars_between(self, pair: str, from_minutes_ago: int, to_minutes_ago: int) -> list[dict]:
        return self.bars(pair, from_minutes_ago - to_minutes_ago)

    def context(self, pair: str, minutes: int) -> list[dict]:
        return [{**b, "taker_buy": 0.0, "taker_sell": 0.0, "flow_imb": 0.0, "trades": 0} for b in self.bars(pair, minutes)]

    def bars(self, pair: str, minutes: int) -> list[dict]:
        p = self.prices.get(pair, 0.0)
        return [{"m": f"2026-01-01 00:{i % 60:02d}:00", "o": p, "h": p, "l": p, "c": p, "v": 1.0} for i in range(minutes)]

    def funding_history(self, pair: str, from_epoch: float, to_epoch: float) -> dict[int, float]:
        return {}

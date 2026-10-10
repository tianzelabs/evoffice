"""What a position was worth -- pure arithmetic, no I/O.

Each leg pays its own fee: a TAKER rate when it took liquidity (a market order,
or a limit order that crossed), a MAKER rate when it rested in the book and was
filled (server/fees.py: Kraken Futures tier 1 is 0.05% taker, 0.02% maker).
Funding paid or received while the position was open is added. So a round trip
costs 10 bps taker/taker, 7 bps maker/taker, 4 bps maker/maker -- and

**a position that moved the right way can still lose.** If
`test_a_favourable_move_can_still_LOSE` ever reports a win, this file is broken
and every number on the leaderboard is meaningless.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import fees


@dataclass(frozen=True)
class Result:
    gross: float
    fees: float
    funding: float
    pnl: float            # net: gross - fees + funding
    pnl_bps: float        # net, in bps of entry notional


def leg_fee(size: float, price: float, liquidity: str) -> float:
    return size * price * fees.rate(liquidity)


def settle(side: str, size: float, entry_px: float, exit_px: float, entry_liq: str = "taker",
           exit_liq: str = "taker", funding: float = 0.0) -> Result:
    if side not in ("long", "short"):
        raise ValueError(f"side must be long or short, got {side!r}")
    if size <= 0 or entry_px <= 0 or exit_px <= 0:
        raise ValueError("size and prices must be positive")
    sign = 1.0 if side == "long" else -1.0
    gross = sign * (exit_px - entry_px) * size
    paid = leg_fee(size, entry_px, entry_liq) + leg_fee(size, exit_px, exit_liq)
    pnl = gross - paid + funding
    return Result(gross, paid, funding, pnl, pnl / (size * entry_px) * 10_000.0)


def breakeven_move(entry_px: float, entry_liq: str = "taker", exit_liq: str = "taker") -> float:
    """Points the price must move in your favour to pay both fees (no funding). Size cancels.
    Solves m = r_in * p + r_out * (p + m) exactly."""
    r_in, r_out = fees.rate(entry_liq), fees.rate(exit_liq)
    return (r_in + r_out) * entry_px / (1 - r_out)

"""The fee model -- pure arithmetic, no I/O.

Carried from agent-world `village/settlement.py`, adapted from fixed-horizon
contracts to positions the trader closes itself. The three-state terminal
(won / breakeven / lost) and the 4:33 horizon are gone: the 2026-09-24
redirection named both as artifacts of the failed era. What stays is the one
fact this project kept rediscovering:

Both legs pay a 4 bps taker fee, so a round trip costs ~8 bps against a BTC
spread of ~0.01 bps. **A position that moved the right way can still lose.**
If `test_a_favourable_move_can_still_LOSE` ever reports a win, this file is
broken and every number on the leaderboard is meaningless.
"""
from __future__ import annotations

from dataclasses import dataclass

TAKER_FEE_RATE = 0.0004   # 4 bps per side, charged on both sides


@dataclass(frozen=True)
class Result:
    gross: float
    fees: float
    pnl: float            # net: gross - fees
    pnl_bps: float        # net, in bps of entry notional


def round_trip_fees(size: float, entry_px: float, exit_px: float) -> float:
    """Fee on the entry notional plus fee on the exit notional."""
    return TAKER_FEE_RATE * size * (entry_px + exit_px)


def settle(side: str, size: float, entry_px: float, exit_px: float) -> Result:
    if side not in ("long", "short"):
        raise ValueError(f"side must be long or short, got {side!r}")
    if size <= 0 or entry_px <= 0 or exit_px <= 0:
        raise ValueError("size and prices must be positive")
    sign = 1.0 if side == "long" else -1.0
    gross = sign * (exit_px - entry_px) * size
    fees = round_trip_fees(size, entry_px, exit_px)
    pnl = gross - fees
    return Result(gross, fees, pnl, pnl / (size * entry_px) * 10_000.0)


def breakeven_move(entry_px: float) -> float:
    """Points the price must move in your favour just to pay both fees.

    Size cancels: fees and P&L scale together, so trading smaller or larger
    does not change it. ~0.0008 x price.
    """
    # exit fee is charged on the exit price, so solve m = r*(2p + m) exactly
    return TAKER_FEE_RATE * 2 * entry_px / (1 - TAKER_FEE_RATE)

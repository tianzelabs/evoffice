"""Kraken Futures fees -- what a real account pays, by tier.

From kraken.com/features/fee-schedule (checked 2026-10-10). The user develops the
agents on what their NEW account would really get, so the office uses tier 1:
0.05% taker, 0.02% maker, per side. A tier is chosen by 30-day futures volume (or
spot volume / assets on platform, whichever is most favourable); OFFICE_FEE_TIER
switches it when the account moves up.

Everything priced before 2026-10-10 used a flat 4 bps a side on spot prices
(regime "spot-4bps"); it stays in the record, labelled, and is never compared
with this regime.
"""
from __future__ import annotations

import os

TIERS = {   # tier: (30-day futures volume threshold USD, maker, taker)
    "1": (0, 0.0002, 0.0005), "2": (5e6, 0.000175, 0.00045), "3": (10e6, 0.00015, 0.0004),
    "4": (15e6, 0.000125, 0.00035), "5": (25e6, 0.0001, 0.0003), "6": (40e6, 0.000075, 0.000275),
    "7": (50e6, 0.00005, 0.00025), "8": (75e6, 0.00005, 0.000225), "9": (100e6, 0.0, 0.0002),
}
TIER = os.environ.get("OFFICE_FEE_TIER", "1")
MAKER, TAKER = TIERS[TIER][1], TIERS[TIER][2]
REGIME = f"kraken-futures-tier{TIER}"
LEGACY_REGIME = "spot-4bps"


def rate(liquidity: str) -> float:
    if liquidity not in ("maker", "taker"):
        raise ValueError(f"liquidity must be maker or taker, got {liquidity!r}")
    return MAKER if liquidity == "maker" else TAKER

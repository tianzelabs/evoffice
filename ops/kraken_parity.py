"""Cross-check the office's simulated fills against Kraken's own paper engine (kraken-cli).

    python ops/kraken_parity.py [ROUNDS]

Each round reads the office's PF_XBTUSD quote, sends a market buy then a market
sell to `kraken futures paper` (Kraken's simulator, live prices, no money), and
reads the quote again. A market fill should equal the office's ask (buy) or bid
(sell) within one tick -- the two read the book a moment apart -- and the fee
must equal size x price x 0.05% (tier 1 taker) exactly. Market orders only:
kraken-cli charges the taker rate on limit fills too, so it cannot check maker
fills -- the reason the office simulates limits itself (see server/orders.py).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import fees                     # noqa: E402
from server.market import FuturesMarket      # noqa: E402

KRAKEN = os.path.expanduser("~/.cargo/bin/kraken")
SIZE, TICK = 0.005, 1.0


def k(*args) -> dict:
    r = subprocess.run([KRAKEN, "futures", "paper", *args, "-o", "json"], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"kraken {' '.join(args)}: {(r.stderr or r.stdout)[-300:]}")
    return json.loads(r.stdout)


def fill_of(resp: dict) -> tuple[float, float]:
    fills = resp.get("fills") or resp.get("result", {}).get("fills") or []
    f = fills[0]
    return float(f["price"]), float(f["fee"])


def main(rounds: int) -> int:
    try:
        k("reset", "--balance", "100000", "--fee-rate", str(fees.TAKER))
    except RuntimeError:
        k("init", "--balance", "100000", "--fee-rate", str(fees.TAKER))
    k("set-leverage", "PF_XBTUSD", "1")       # the office trades fully funded virtual cash: 1x
    m, bad = FuturesMarket(), 0
    for i in range(rounds):
        for side, cmd in (("buy", "buy"), ("sell", "sell")):
            q1 = m.quote()
            px, fee = fill_of(k(cmd, "PF_XBTUSD", str(SIZE), "--type", "market"))
            q2 = m.quote()
            ours = (q1.ask, q2.ask) if side == "buy" else (q1.bid, q2.bid)
            ok_px = min(ours) - TICK <= px <= max(ours) + TICK
            ok_fee = abs(fee - SIZE * px * fees.TAKER) < 1e-6
            bad += not (ok_px and ok_fee)
            print(json.dumps({"round": i + 1, "side": side, "kraken_fill": px, "office_quote": ours,
                              "kraken_fee": round(fee, 6), "office_fee": round(SIZE * px * fees.TAKER, 6),
                              "price_ok": ok_px, "fee_ok": ok_fee}))
    print(f"PARITY {'OK' if not bad else 'MISMATCH'}: {2 * rounds - bad}/{2 * rounds} fills agree")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 3))

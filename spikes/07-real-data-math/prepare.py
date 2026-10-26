"""Freeze one snapshot and chronological partitions before model inference."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"


def main():
    target = DATA / "manifest.json"
    if target.exists():
        raise RuntimeError("Snapshot is already frozen")
    raw = json.loads((DATA / "raw_context.json").read_text())
    epochs = [int(datetime.fromisoformat(b["m"]).replace(tzinfo=timezone.utc).timestamp()) for b in raw]
    assert len(set(epochs)) == len(epochs) and all(b > a for a, b in zip(epochs, epochs[1:]))
    assert all(b["c"] > 0 and b["l"] <= min(b["o"], b["c"]) <= max(b["o"], b["c"]) <= b["h"] for b in raw)
    n = len(raw)
    cut1, cut2 = int(n * .6), int(n * .8)
    segment = 0
    rows = []
    for i, bar in enumerate(raw):
        gap = i == 0 or epochs[i] - epochs[i-1] != 60
        if gap:
            segment += 1
        part = "train" if i < cut1 else "validation" if i < cut2 else "holdout"
        rows.append({**bar, "epoch": epochs[i], "segment": segment, "partition": part,
                     "r_bps": None if gap else 1e4 * (bar["c"] / raw[i-1]["c"] - 1)})
    pairs = []
    for i in range(len(rows)-1):
        a, b = rows[i], rows[i+1]
        if a["r_bps"] is not None and b["r_bps"] is not None and a["segment"] == b["segment"] and a["partition"] == b["partition"]:
            pairs.append({"m": a["m"], "target_m": b["m"], "epoch": a["epoch"],
                          "target_epoch": b["epoch"], "segment": a["segment"],
                          "partition": a["partition"], "x_bps": a["r_bps"], "y_bps": b["r_bps"]})
    train = [r for r in rows if r["partition"] == "train"]
    spreads = [1e4*r["spread"]/r["c"] for r in train if r.get("spread") is not None and r["spread"] >= 0]
    funding = [1e4*abs(r["funding_per_hour"])/60 for r in train if r.get("funding_per_hour") is not None]
    fees = json.loads((DATA / "price_snapshot.json").read_text())["fees"]
    # The oldest training partition predates microstructure collection. Do NOT
    # substitute validation/holdout spreads or treat missing values as zeros.
    one_way = 1e4 * fees["taker"]
    round_trip = 2*one_way
    manifest = {"frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "http://100.86.90.65:8710/market/context?minutes=10080",
        "instrument": "Kraken Futures PF_XBTUSD", "timestamps_timezone": "UTC",
        "raw_sha256": hashlib.sha256((DATA/"raw_context.json").read_bytes()).hexdigest(),
        "rows": n, "first": raw[0]["m"], "last": raw[-1]["m"],
        "missing_minutes": (epochs[-1]-epochs[0])//60+1-n,
        "contiguous_segments": segment,
        "split_rule": "First 60% / next 20% / final 20% of rows, by time, before any model calls",
        "partitions": {p: {"bars": sum(r["partition"]==p for r in rows),
                              "one_minute_returns": sum(r["partition"]==p and r["r_bps"] is not None for r in rows),
                              "pairs": sum(r["partition"]==p for r in pairs),
                              "first": next(r["m"] for r in rows if r["partition"]==p),
                              "last": next(r["m"] for r in reversed(rows) if r["partition"]==p)}
                       for p in ["train", "validation", "holdout"]},
        "nonmissing_fields": {k: sum(r.get(k) is not None for r in raw) for k in sorted({k for r in raw for k in r})},
        "fees": fees,
        "fixed_cost_proxies_bps": {"one_way_fee_only": one_way,
            "round_trip_fee_only": round_trip,
            "train_median_full_spread": float(np.median(spreads)) if spreads else None,
            "train_median_abs_one_minute_funding": float(np.median(funding)) if funding else None,
            "microstructure_train_observations": len(spreads)},
        "cost_limitations": "Fee-only toy costs. Training partition predates microstructure capture: spread and funding estimates are unavailable, not zero. Do not borrow later observations to fit costs. Spread, funding, impact, latency, queue effects are omitted; no proxy net PnL is an executable result or a guaranteed total-cost bound. Never infer maker execution from a touched bar.",
        "scope": "Only recent public research data; the office's separate 60-day evaluation window is not accessed."}
    visible = {"manifest": manifest, "rows": [r for r in rows if r["partition"] != "holdout"],
               "pairs": [r for r in pairs if r["partition"] != "holdout"]}
    sealed = {"rows": [r for r in rows if r["partition"] == "holdout"],
              "pairs": [r for r in pairs if r["partition"] == "holdout"]}
    (DATA / "visible.json").write_text(json.dumps(visible, allow_nan=False))
    (DATA / "holdout.json").write_text(json.dumps(sealed, allow_nan=False))
    target.write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()

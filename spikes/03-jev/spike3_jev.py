"""Spike 3: Jev 1.13 as the trader's fast "System One" -- format, latency, cost,
and whether its labels carry information about the next 30 minutes.

~200 origins, 30 minutes apart, over the last 5 days of real BTC/USD 1m bars.
For each origin Jev sees ONLY the 30 bars before it and answers two typed
questions; the 30 bars after it are the truth. Each answer is compared with a
naive baseline, because "Jev produced a probability" means nothing on its own:

  will_clear_fee (noul): |move over next 30m| > 8bps?  baseline: trailing 30m range
  direction (choice):    up / down / flat (within +-8bps)  baseline: always the base-rate class

Plain HTTP, no model writes or runs code here.
"""
import concurrent.futures as cf
import csv
import json
import math
import os
import statistics
import sys
import time
import urllib.request

KEY = os.environ["OPENROUTER_API_KEY"]
URL = os.environ.get("JEV_URL", "https://openrouter.ai/api/alpha/decisions")
FEE_BPS = 8.0
LOOKBACK, HORIZON, STEP = 30, 30, 30

with open(sys.argv[1]) as f:
    bars = [{"m": r["m"], "o": float(r["o"]), "h": float(r["h"]), "l": float(r["l"]),
             "c": float(r["c"]), "v": float(r["v"])} for r in csv.DictReader(f)]

QUESTIONS = {
    "will_clear_fee": {
        "type": "noul",
        "instructions": "Over the NEXT 30 minutes, will BTC/USD's close move by more than 8 basis points "
                        "(0.08%) in either direction from the last close shown?",
        "criteria": {"true": "The absolute move over the next 30 minutes exceeds 8 bps.",
                     "false": "The price stays within 8 bps of the last close over the next 30 minutes."},
    },
    "direction": {
        "type": "choice",
        "instructions": "Where will BTC/USD's close be 30 minutes after the last bar shown, relative to the last close?",
        "criteria": {"up": "More than 8 bps higher.",
                     "down": "More than 8 bps lower.",
                     "flat": "Within 8 bps of the last close."},
    },
}


def state_for(window):
    last = window[-1]["c"]
    # compact: per-minute close in bps relative to the last close, plus range and volume
    return {
        "pair": "BTC/USD", "bar": "1 minute", "last_close": last,
        "minutes": [{"t": -(len(window) - 1 - i),
                     "close_bps_vs_last": round((b["c"] / last - 1) * 1e4, 1),
                     "range_bps": round((b["h"] - b["l"]) / last * 1e4, 1),
                     "volume_btc": round(b["v"], 3)} for i, b in enumerate(window)],
    }


def ask(state):
    body = json.dumps({"model": "typesafe/jev-1.13", "state": state, "questions": QUESTIONS}).encode()
    req = urllib.request.Request(URL, data=body, method="POST", headers={
        "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    t0 = time.perf_counter()
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r), time.perf_counter() - t0
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}: {e.read()[:300]!r}"
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
        time.sleep(2 * (attempt + 1))
    return {"error": err}, time.perf_counter() - t0


def auc(scores, labels):
    pos = [s for s, y in zip(scores, labels) if y]
    neg = [s for s, y in zip(scores, labels) if not y]
    if not pos or not neg:
        return float("nan")
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


origins = list(range(LOOKBACK, len(bars) - HORIZON, STEP))
cases = []
for i in origins:
    w = bars[i - LOOKBACK + 1:i + 1]
    last, fut = w[-1]["c"], bars[i + HORIZON]["c"]
    move = (fut / last - 1) * 1e4
    cases.append({"m": w[-1]["m"], "state": state_for(w), "move_bps": move,
                  "trail_range_bps": (max(b["h"] for b in w) - min(b["l"] for b in w)) / last * 1e4})

if "--one" in sys.argv:          # format check: one call, print everything
    resp, secs = ask(cases[-1]["state"])
    print(json.dumps(resp, indent=1)[:2000], f"\n{secs:.2f}s")
    sys.exit()

t0 = time.perf_counter()
with cf.ThreadPoolExecutor(8) as ex:
    results = list(ex.map(lambda c: ask(c["state"]), cases))
wall = time.perf_counter() - t0

rows, errors, cost, lat, toks = [], [], 0.0, [], []
for c, (resp, secs) in zip(cases, results):
    if "answers" not in resp:
        errors.append(resp.get("error"))
        continue
    a = resp["answers"]
    cost += resp.get("usage", {}).get("cost") or 0.0
    toks.append(resp.get("usage", {}).get("input_tokens"))
    lat.append(secs)
    rows.append({**{k: c[k] for k in ("m", "move_bps", "trail_range_bps")},
                 "p_clear": a["will_clear_fee"]["noul"], "dir": a["direction"]["choice"],
                 "dir_probs": a["direction"].get("probabilities"), "dir_conf": a["direction"].get("confidence")})

n = len(rows)
clear = [abs(r["move_bps"]) > FEE_BPS for r in rows]
truth_dir = ["up" if r["move_bps"] > FEE_BPS else "down" if r["move_bps"] < -FEE_BPS else "flat" for r in rows]
base_class = max(set(truth_dir), key=truth_dir.count)
jev_acc = sum(r["dir"] == t for r, t in zip(rows, truth_dir)) / n
# directional only where Jev committed to up/down
committed = [(r["dir"], t) for r, t in zip(rows, truth_dir) if r["dir"] in ("up", "down")]
logloss_jev = -statistics.mean(math.log(max(1e-6, (r["dir_probs"] or {}).get(t, 0.0))) for r, t in zip(rows, truth_dir))
rates = {k: truth_dir.count(k) / n for k in ("up", "down", "flat")}
logloss_base = -statistics.mean(math.log(max(1e-6, rates[t])) for t in truth_dir)

summary = {
    "n_ok": n, "n_errors": len(errors), "first_errors": errors[:3],
    "cost_usd_total": round(cost, 6), "cost_per_call": round(cost / max(n, 1), 8),
    "input_tokens_median": statistics.median(toks) if toks else None,
    "latency_s_median": round(statistics.median(lat), 2) if lat else None,
    "latency_s_p90": round(sorted(lat)[int(0.9 * len(lat))], 2) if lat else None,
    "wall_s_8_parallel": round(wall, 1),
    "clear_fee": {"base_rate": round(sum(clear) / n, 3),
                  "auc_jev": round(auc([r["p_clear"] for r in rows], clear), 3),
                  "auc_trailing_range": round(auc([r["trail_range_bps"] for r in rows], clear), 3),
                  "p_clear_mean": round(statistics.mean(r["p_clear"] for r in rows), 3)},
    "direction": {"truth_rates": {k: round(v, 3) for k, v in rates.items()},
                  "jev_pick_rates": {k: round(sum(r["dir"] == k for r in rows) / n, 3) for k in ("up", "down", "flat")},
                  "acc_jev": round(jev_acc, 3), "acc_always_" + base_class: round(truth_dir.count(base_class) / n, 3),
                  "logloss_jev": round(logloss_jev, 3), "logloss_base_rates": round(logloss_base, 3),
                  "committed_n": len(committed),
                  "committed_hit_rate": round(sum(p == t for p, t in committed) / len(committed), 3) if committed else None},
}
print("SUMMARY " + json.dumps(summary, ensure_ascii=False))
with open("spike3_rows.jsonl", "w") as f:
    for r in rows:
        f.write(json.dumps(r) + "\n")

"""Spike 3b: Jev as the trader's 风口 (opportunity-window) radar.

Spike 3 used Jev wrong: two big questions predicting the future, read as if
answers had to agree. TypeSafe's docs say the opposite -- decompose into small
judgments, every answer is independent, combine them in code with weights. So
here Jev answers 8 small questions, 7 DESCRIBING the present multi-scale state
and 1 gestalt about the next 2 hours, and the combination is tested.

PRE-REGISTERED before any result was seen:
  primary truth  : |BTC net move over the next 120 min| > 30 bps  (~4x the round-trip fee)
  secondary truth: BTC high-low range over the next 120 min, in bps (Spearman)
  (a) Jev's gestalt `opportunity` vs baselines: trailing 2h range, UTC-hour base rate
  (b) logistic regression, 5-fold CV: Jev's 8 answers vs baseline features vs both
  (c) does Jev read the present correctly: volume surge, trend strength, cross-asset

Origins every 2h over the last 30 days, needing 4h of history and 2h of future.
"""
import concurrent.futures as cf
import csv
import json
import os
import random
import statistics
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler

KEY = os.environ["OPENROUTER_API_KEY"]
URL = "https://openrouter.ai/api/alpha/decisions"
LOOK_MIN, FWD_MIN, STEP_MIN, PRIMARY_BPS = 240, 120, 120, 30.0

# ---------- data ----------
mins = defaultdict(dict)  # pair -> minute -> (o,h,l,c,v)
with open(sys.argv[1]) as f:
    for r in csv.DictReader(f):
        mins[r["pair"]][r["m"]] = tuple(float(r[k]) for k in ("o", "h", "l", "c", "v"))
btc_keys = sorted(mins["BTC/USD"])
idx = {m: i for i, m in enumerate(btc_keys)}


def minute_series(pair, end_i, n):
    """last n minutes ending at btc_keys[end_i] by timestamp; None where missing."""
    end = datetime.fromisoformat(btc_keys[end_i])
    out = []
    for k in range(n - 1, -1, -1):
        t = datetime.fromtimestamp(end.timestamp() - 60 * k).strftime("%Y-%m-%d %H:%M:%S")
        out.append(mins[pair].get(t))
    return out


def five_min(series):
    bars = []
    for j in range(0, len(series), 5):
        chunk = [x for x in series[j:j + 5] if x]
        if not chunk:
            bars.append(None)
            continue
        bars.append((max(x[1] for x in chunk), min(x[2] for x in chunk), chunk[-1][3], sum(x[4] for x in chunk)))
    return bars


def build(i):
    s = {p: minute_series(p, i, LOOK_MIN) for p in ("BTC/USD", "ETH/USD", "SOL/USD")}
    if any(sum(x is None for x in v) > 0.1 * LOOK_MIN for v in s.values()):
        return None
    end = datetime.fromisoformat(btc_keys[i])
    fut_t = datetime.fromtimestamp(end.timestamp() + 60 * FWD_MIN).strftime("%Y-%m-%d %H:%M:%S")
    fut = [mins["BTC/USD"].get(datetime.fromtimestamp(end.timestamp() + 60 * k).strftime("%Y-%m-%d %H:%M:%S"))
           for k in range(1, FWD_MIN + 1)]
    if mins["BTC/USD"].get(fut_t) is None or sum(x is None for x in fut) > 0.1 * FWD_MIN:
        return None
    last = s["BTC/USD"][-1][3] if s["BTC/USD"][-1] else None
    if last is None:
        return None
    state = {"utc_time": end.strftime("%A %H:%M UTC")}
    for p, key in (("BTC/USD", "btc"), ("ETH/USD", "eth"), ("SOL/USD", "sol")):
        b5 = five_min(s[p])
        ref = next(x[2] for x in reversed(b5) if x)
        d = {"note": "48 five-minute bars, oldest first; close and range in bps relative to the latest close",
             "close_bps": [round((x[2] / ref - 1) * 1e4) if x else None for x in b5],
             "range_bps": [round((x[0] - x[1]) / ref * 1e4) if x else None for x in b5]}
        if key == "btc":
            d["volume_btc"] = [round(x[3], 1) if x else None for x in b5]
            d["last_30_one_minute_close_bps"] = [round((x[3] / last - 1) * 1e4) if x else None for x in s[p][-30:]]
        state[key] = d
    # truths and baseline features, all computed in code
    fc = mins["BTC/USD"][fut_t][3]
    fut_ok = [x for x in fut if x]
    b5 = five_min(s["BTC/USD"])
    closes = [x[2] for x in b5 if x]
    last24 = closes[-24:]
    eff = abs(last24[-1] - last24[0]) / max(1e-9, sum(abs(a - b) for a, b in zip(last24[1:], last24)))
    vols = [x[3] for x in b5 if x]
    return {
        "m": btc_keys[i], "state": state,
        "net_bps": (fc / last - 1) * 1e4,
        "fwd_range_bps": (max(x[1] for x in fut_ok) - min(x[2] for x in fut_ok)) / last * 1e4,
        "trail_range_2h": (max(x[0] for x in b5[-24:] if x) - min(x[1] for x in b5[-24:] if x)) / last * 1e4,
        "trail_range_4h": (max(x[0] for x in b5 if x) - min(x[1] for x in b5 if x)) / last * 1e4,
        "utc_hour": end.hour,
        "vol_ratio_30m": (statistics.mean(vols[-6:]) / max(1e-9, statistics.mean(vols))),
        "efficiency_2h": eff,
    }


QUESTIONS = {
    "trend_2h": {"type": "score",
                 "instructions": "Using the last 24 values of `btc.close_bps` (the last 2 hours), how directional has BTC's movement been?",
                 "criteria": ["Choppy: back and forth with no net direction",
                              "Mild drift in one direction with frequent reversals",
                              "Clear trend with shallow pullbacks",
                              "Strong one-way move"]},
    "vol_regime": {"type": "score",
                   "instructions": "Compare `btc.range_bps` in the last 2 hours with the 2 hours before. How is volatility changing?",
                   "criteria": ["Compressing: ranges clearly shrinking", "Stable", "Expanding", "Surging: ranges far larger than before"]},
    "volume_surge": {"type": "noul",
                     "instructions": "Is BTC volume in the last 30 minutes (last 6 values of `btc.volume_btc`) clearly above its typical level over the whole 4 hours?"},
    "breakout": {"type": "choice",
                 "instructions": "Where is BTC now relative to its 4-hour range in `btc.close_bps`?",
                 "criteria": {"inside": "Trading inside the range, away from its edges",
                              "breaking_up": "Pushing through the top of the range",
                              "breaking_down": "Pushing through the bottom of the range",
                              "failed_break": "Broke out recently and has fallen back inside",
                              "other": None}},
    "cross_asset": {"type": "choice",
                    "instructions": "Over the last hour, how do `btc.close_bps`, `eth.close_bps` and `sol.close_bps` move relative to each other?",
                    "criteria": {"together": "All three move clearly in the same direction",
                                 "btc_alone": "BTC moves while ETH and SOL are flat or opposite",
                                 "alts_lead": "ETH and/or SOL move clearly while BTC lags",
                                 "diverging": "They move in different directions",
                                 "all_quiet": "None of them moves much"}},
    "coiling": {"type": "noul",
                "instructions": "After a larger move earlier in the 4 hours, has BTC been compressing into a tight range in the most recent hour (a coil before a possible move)?"},
    "exhaustion": {"type": "noul",
                   "instructions": "Does the most recent BTC move in `btc.last_30_one_minute_close_bps` look exhausted: a sharp spike that is already retracing?"},
    "opportunity": {"type": "score",
                    "instructions": "Considering the whole state, including the time of day in `utc_time`, how likely is it that BTC makes a tradable move (well beyond a 0.08% round-trip fee) within the next 2 hours?",
                    "criteria": ["Dead market: little chance of a tradable move",
                                 "Low", "Moderate", "High: a tradable move is likely"]},
}


def ask(state):
    body = json.dumps({"model": "typesafe/jev-1.13", "state": state, "questions": QUESTIONS}).encode()
    req = urllib.request.Request(URL, data=body, method="POST",
                                 headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    t0, err = time.perf_counter(), None
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


# origins every STEP_MIN minutes by clock
first = datetime.fromisoformat(btc_keys[0]).timestamp() + 60 * LOOK_MIN
last_t = datetime.fromisoformat(btc_keys[-1]).timestamp() - 60 * FWD_MIN
cases, skipped = [], 0
t = first - first % (60 * STEP_MIN) + 60 * STEP_MIN
while t <= last_t:
    key = datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")
    c = build(idx[key]) if key in idx else None
    if c:
        cases.append(c)
    else:
        skipped += 1
    t += 60 * STEP_MIN
print(f"origins: {len(cases)} usable, {skipped} skipped for missing data", flush=True)

if "--one" in sys.argv:
    resp, secs = ask(cases[-1]["state"])
    print(json.dumps(resp, indent=1)[:3000], f"\n{secs:.2f}s, state chars {len(json.dumps(cases[-1]['state']))}")
    sys.exit()

with cf.ThreadPoolExecutor(8) as ex:
    results = list(ex.map(lambda c: ask(c["state"]), cases))

rows, errors, cost, lat = [], [], 0.0, []
for c, (resp, secs) in zip(cases, results):
    if "answers" not in resp:
        errors.append(resp.get("error"))
        continue
    cost += resp.get("usage", {}).get("cost") or 0.0
    lat.append(secs)
    a = resp["answers"]
    feat = {"trend_2h": a["trend_2h"]["score"], "vol_regime": a["vol_regime"]["score"],
            "volume_surge": a["volume_surge"]["noul"], "coiling": a["coiling"]["noul"],
            "exhaustion": a["exhaustion"]["noul"], "opportunity": a["opportunity"]["score"]}
    for k in ("inside", "breaking_up", "breaking_down", "failed_break"):
        feat["breakout_" + k] = a["breakout"]["probabilities"].get(k, 0.0)
    for k in ("together", "btc_alone", "alts_lead", "diverging", "all_quiet"):
        feat["cross_" + k] = a["cross_asset"]["probabilities"].get(k, 0.0)
    rows.append({**{k: v for k, v in c.items() if k != "state"}, "jev": feat,
                 "cross_choice": a["cross_asset"]["choice"], "breakout_choice": a["breakout"]["choice"]})

n = len(rows)
y = np.array([abs(r["net_bps"]) > PRIMARY_BPS for r in rows], dtype=int)


def spearman(a, b):
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1])


# UTC-hour base rate, leave-one-out so a case never sees its own label
hour_rate = []
for i, r in enumerate(rows):
    same = [y[j] for j, q in enumerate(rows) if q["utc_hour"] == r["utc_hour"] and j != i]
    hour_rate.append(statistics.mean(same) if same else y.mean())

jev_keys = sorted(rows[0]["jev"])
X_jev = np.array([[r["jev"][k] for k in jev_keys] for r in rows])
X_base = np.array([[r["trail_range_2h"], r["trail_range_4h"], r["vol_ratio_30m"], hr] for r, hr in zip(rows, hour_rate)])


def cv_auc(X, reps=5):
    aucs = []
    for seed in range(reps):
        p = np.zeros(n)
        for tr, te in StratifiedKFold(5, shuffle=True, random_state=seed).split(X, y):
            sc = StandardScaler().fit(X[tr])
            m = LogisticRegression(C=0.5, max_iter=2000).fit(sc.transform(X[tr]), y[tr])
            p[te] = m.predict_proba(sc.transform(X[te]))[:, 1]
        aucs.append(roc_auc_score(y, p))
    return round(statistics.mean(aucs), 3), round(statistics.pstdev(aucs), 3)


def boot_ci(score):
    rng = random.Random(0)
    vals = []
    for _ in range(1000):
        ii = [rng.randrange(n) for _ in range(n)]
        yy = y[ii]
        if yy.min() == yy.max():
            continue
        vals.append(roc_auc_score(yy, np.array(score)[ii]))
    vals.sort()
    return round(vals[25], 3), round(vals[975], 3)


opp = [r["jev"]["opportunity"] for r in rows]
summary = {
    "n_ok": n, "n_errors": len(errors), "first_errors": errors[:2],
    "cost_usd_total": round(cost, 5), "cost_per_call": round(cost / max(n, 1), 7),
    "latency_s_median": round(statistics.median(lat), 2) if lat else None,
    "primary_base_rate": round(float(y.mean()), 3),
    "a_single_scores_auc": {
        "jev_opportunity": round(roc_auc_score(y, opp), 3), "jev_opportunity_ci95": boot_ci(opp),
        "trailing_range_2h": round(roc_auc_score(y, [r["trail_range_2h"] for r in rows]), 3),
        "trailing_range_2h_ci95": boot_ci([r["trail_range_2h"] for r in rows]),
        "utc_hour_rate_loo": round(roc_auc_score(y, hour_rate), 3),
    },
    "a_secondary_spearman_vs_fwd_range": {
        "jev_opportunity": round(spearman(opp, [r["fwd_range_bps"] for r in rows]), 3),
        "trailing_range_2h": round(spearman([r["trail_range_2h"] for r in rows], [r["fwd_range_bps"] for r in rows]), 3),
    },
    "b_combined_cv_auc_mean_sd": {"jev_8_answers": cv_auc(X_jev), "baseline_features": cv_auc(X_base),
                                  "both": cv_auc(np.hstack([X_jev, X_base]))},
    "c_perception": {
        "volume_surge_vs_true_ratio_spearman": round(spearman([r["jev"]["volume_surge"] for r in rows], [r["vol_ratio_30m"] for r in rows]), 3),
        "trend_2h_vs_true_efficiency_spearman": round(spearman([r["jev"]["trend_2h"] for r in rows], [r["efficiency_2h"] for r in rows]), 3),
        "vol_regime_vs_true_range_ratio_spearman": round(spearman([r["jev"]["vol_regime"] for r in rows],
                                                                   [r["trail_range_2h"] / max(1e-9, r["trail_range_4h"]) for r in rows]), 3),
        "cross_asset_choices": {k: sum(r["cross_choice"] == k for r in rows) for k in ("together", "btc_alone", "alts_lead", "diverging", "all_quiet")},
        "breakout_choices": {k: sum(r["breakout_choice"] == k for r in rows) for k in ("inside", "breaking_up", "breaking_down", "failed_break", "other")},
        "opportunity_distinct_values": len(set(round(v, 2) for v in opp)),
    },
}
print("SUMMARY " + json.dumps(summary, ensure_ascii=False))
with open("spike3b_rows.jsonl", "w") as f:
    for r in rows:
        f.write(json.dumps(r) + "\n")

"""Spike 3c: what FORM of the data is best for Jev -- and does Jev add anything
to a real, data-trained model?

Same information, five forms, one question (Jev's 2h 风口 `opportunity`):
  R0 raw       multi-scale bps sequences (spike 3b's state)
  R1 features  ~18 engineered features as raw numbers with units
  R2 pctile    the same features as percentiles vs the past 30 days (causal)
  R3 narrative English sentences generated from R2
  R4 model     a gradient-boosting model's probability + its top drivers + R3

PRE-REGISTERED:
  truth   |BTC net move over the next 120 min| > 30 bps
  split   train = origins before TEST_DAYS ago minus a 1-day embargo; test = last TEST_DAYS
  report  test AUC per form; data model AUC; paired bootstrap of the best Jev form
          vs the model, and of rank-average(model, Jev) vs the model alone
"""
import concurrent.futures as cf
import json
import math
import os
import random
import statistics
import sys
import time
import urllib.request
from datetime import datetime, timezone

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import roc_auc_score

KEY = os.environ.get("OPENROUTER_API_KEY")
URL = "https://openrouter.ai/api/alpha/decisions"
STEP, LOOK, FWD, PRIMARY_BPS, TEST_DAYS = 120, 240, 120, 30.0, 45
PAIRS = ("BTC/USD", "ETH/USD", "SOL/USD")

# ---------- load 1m bars into dense arrays (NaN = missing minute) ----------
raw = {p: {} for p in PAIRS}
with open(sys.argv[1]) as f:
    next(f)
    for line in f:
        p, m, h, l, c, v = line.rstrip("\n").replace('"', "").split(",")
        raw[p][m] = (float(h), float(l), float(c), float(v))
t0 = min(datetime.fromisoformat(m).replace(tzinfo=timezone.utc).timestamp() for m in raw["BTC/USD"])
t1 = max(datetime.fromisoformat(m).replace(tzinfo=timezone.utc).timestamp() for m in raw["BTC/USD"])
N = int((t1 - t0) // 60) + 1
A = {}
for p in PAIRS:
    arr = np.full((N, 4), np.nan)
    for m, row in raw[p].items():
        k = int((datetime.fromisoformat(m).replace(tzinfo=timezone.utc).timestamp() - t0) // 60)
        if 0 <= k < N:
            arr[k] = row
    A[p] = arr
del raw
ts_of = lambda k: datetime.fromtimestamp(t0 + 60 * k, tz=timezone.utc)


def ffill_close(x):
    c = x[:, 2].copy()
    for i in range(1, len(c)):
        if np.isnan(c[i]):
            c[i] = c[i - 1]
    return c


def features(k):
    """Everything computed from minutes <= k only."""
    w = {p: A[p][k - LOOK + 1:k + 1] for p in PAIRS}
    if any(np.isnan(w[p][:, 2]).mean() > 0.1 for p in PAIRS) or np.isnan(w["BTC/USD"][-1, 2]):
        return None
    b = w["BTC/USD"]
    c = ffill_close(b)
    last = c[-1]
    r = np.diff(np.log(c)) * 1e4
    hi, lo, vol = b[:, 0], b[:, 1], np.nan_to_num(b[:, 3])

    def rng(n):
        return (np.nanmax(hi[-n:]) - np.nanmin(lo[-n:])) / last * 1e4

    eff = abs(c[-1] - c[-121]) / max(1e-9, np.sum(np.abs(np.diff(c[-121:]))))
    pos = (last - np.nanmin(lo)) / max(1e-9, np.nanmax(hi) - np.nanmin(lo))
    e, s = ffill_close(w["ETH/USD"]), ffill_close(w["SOL/USD"])
    r5 = lambda x: np.diff(np.log(x[::5])) * 1e4
    t = ts_of(k)
    return {
        "range_30m_bps": rng(30), "range_2h_bps": rng(120), "range_4h_bps": rng(240),
        "rv_30m_bps": float(np.std(r[-30:]) * math.sqrt(30)), "rv_4h_bps": float(np.std(r) * math.sqrt(240)),
        "range_2h_vs_prev_2h": rng(120) / max(1e-9, (np.nanmax(hi[:120]) - np.nanmin(lo[:120])) / last * 1e4),
        "volume_30m_vs_4h": float(vol[-30:].mean() / max(1e-9, vol.mean())),
        "volume_4h_btc": float(vol.sum()),
        "net_move_30m_bps": float((c[-1] / c[-31] - 1) * 1e4), "net_move_2h_bps": float((c[-1] / c[-121] - 1) * 1e4),
        "trend_efficiency_2h": float(eff), "position_in_4h_range": float(pos),
        "max_1m_move_30m_bps": float(np.max(np.abs(r[-30:]))),
        "eth_net_move_2h_bps": float((e[-1] / e[-121] - 1) * 1e4), "sol_net_move_2h_bps": float((s[-1] / s[-121] - 1) * 1e4),
        "btc_eth_corr_4h": float(np.corrcoef(r5(c), r5(e))[0, 1]),
        "hour_utc": t.hour, "weekday": t.weekday(),
    }


def truth(k):
    b = A["BTC/USD"]
    if k + FWD >= N or np.isnan(b[k + FWD, 2]) or np.isnan(b[k + 1:k + FWD + 1, 2]).mean() > 0.1:
        return None
    return (b[k + FWD, 2] / b[k, 2] - 1) * 1e4


def raw_state(k):
    st = {"utc_time": ts_of(k).strftime("%A %H:%M UTC")}
    for p, key in zip(PAIRS, ("btc", "eth", "sol")):
        x = A[p][k - LOOK + 1:k + 1]
        c = ffill_close(x)
        ref = c[-1]
        b5 = [(np.nanmax(x[j:j + 5, 0]), np.nanmin(x[j:j + 5, 1]), c[j + 4], np.nansum(x[j:j + 5, 3])) for j in range(0, LOOK, 5)]
        d = {"close_bps": [round((q[2] / ref - 1) * 1e4) for q in b5],
             "range_bps": [None if np.isnan(q[0]) else round((q[0] - q[1]) / ref * 1e4) for q in b5]}
        if key == "btc":
            d["volume_btc"] = [round(float(q[3]), 1) for q in b5]
        st[key] = d
    return st


# ---------- origins ----------
first = LOOK + (-(int(t0 // 60) + LOOK)) % STEP
origins = []
for k in range(first, N - FWD - 1, STEP):
    f, y = features(k), truth(k)
    if f and y is not None:
        origins.append({"k": k, "t": ts_of(k), "f": f, "net": y})
print(f"usable origins: {len(origins)}", flush=True)
test_start = ts_of(N - 1).timestamp() - TEST_DAYS * 86400
train = [o for o in origins if o["t"].timestamp() < test_start - 86400]
test = [o for o in origins if o["t"].timestamp() >= test_start]
FEATS = list(origins[0]["f"])
Xtr = np.array([[o["f"][q] for q in FEATS] for o in train]); ytr = np.array([abs(o["net"]) > PRIMARY_BPS for o in train], int)
Xte = np.array([[o["f"][q] for q in FEATS] for o in test]); yte = np.array([abs(o["net"]) > PRIMARY_BPS for o in test], int)
print(f"train {len(train)} (base {ytr.mean():.3f}), test {len(test)} (base {yte.mean():.3f})", flush=True)

model = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=300, l2_regularization=1.0,
                                       min_samples_leaf=40, random_state=0).fit(Xtr, ytr)
p_model = model.predict_proba(Xte)[:, 1]
imp = permutation_importance(model, Xtr, ytr, scoring="roc_auc", n_repeats=5, random_state=0).importances_mean
importance = dict(sorted(zip(FEATS, imp), key=lambda kv: -kv[1]))
print("model test AUC", round(roc_auc_score(yte, p_model), 3), "| top features", list(importance)[:6], flush=True)

# ---------- causal percentiles vs the previous 30 days of origins ----------
by_t = sorted(origins, key=lambda o: o["t"])
pos_of = {id(o): i for i, o in enumerate(by_t)}


def pctiles(o):
    i = pos_of[id(o)]
    past = [q for q in by_t[max(0, i - 360):i] if (o["t"] - q["t"]).total_seconds() <= 30 * 86400]
    out = {}
    for q in FEATS:
        if q in ("hour_utc", "weekday"):
            continue
        vals = [z["f"][q] for z in past]
        out[q] = round(100 * sum(v < o["f"][q] for v in vals) / max(1, len(vals)))
    return out


def level(p):
    return ("extremely low" if p < 5 else "very low" if p < 15 else "low" if p < 35 else "typical" if p < 65
            else "high" if p < 85 else "very high" if p < 95 else "extremely high")


def narrative(o, pc):
    f = o["f"]
    d = "up" if f["net_move_2h_bps"] > 0 else "down"
    sent = [
        f"It is {o['t'].strftime('%A %H:%M')} UTC.",
        f"BTC volatility over the last 2 hours is {level(pc['range_2h_bps'])} for the past month "
        f"({pc['range_2h_bps']}th percentile), and the last 30 minutes are {level(pc['range_30m_bps'])} ({pc['range_30m_bps']}th).",
        f"Compared with the 2 hours before, the 2-hour range is {'expanding' if f['range_2h_vs_prev_2h'] > 1.15 else 'contracting' if f['range_2h_vs_prev_2h'] < 0.85 else 'about the same'} "
        f"(ratio {f['range_2h_vs_prev_2h']:.2f}, {pc['range_2h_vs_prev_2h']}th percentile).",
        f"Volume in the last 30 minutes is {f['volume_30m_vs_4h']:.1f}x the 4-hour average ({level(pc['volume_30m_vs_4h'])}); "
        f"4-hour volume overall is {level(pc['volume_4h_btc'])} for the month.",
        f"BTC has moved {abs(f['net_move_2h_bps']):.0f} bps {d} over 2 hours with trend efficiency {f['trend_efficiency_2h']:.2f} "
        f"({level(pc['trend_efficiency_2h'])}: {'a clean one-way move' if f['trend_efficiency_2h'] > 0.5 else 'mostly back and forth'}).",
        f"Price sits at {100 * f['position_in_4h_range']:.0f}% of its 4-hour range.",
        f"ETH moved {f['eth_net_move_2h_bps']:+.0f} bps and SOL {f['sol_net_move_2h_bps']:+.0f} bps over the same 2 hours; "
        f"BTC-ETH correlation is {f['btc_eth_corr_4h']:.2f}.",
        f"The largest single-minute BTC move in the last 30 minutes was {f['max_1m_move_30m_bps']:.0f} bps ({level(pc['max_1m_move_30m_bps'])}).",
    ]
    return " ".join(sent)


TOP = list(importance)[:4]


def state_for(form, o, j):
    if form == "R0":
        return raw_state(o["k"])
    if form == "R1":
        return {"utc_time": o["t"].strftime("%A %H:%M UTC"),
                "features": {q: round(v, 3) for q, v in o["f"].items() if q not in ("hour_utc", "weekday")}}
    pc = pctiles(o)
    if form == "R2":
        return {"utc_time": o["t"].strftime("%A %H:%M UTC"),
                "note": "each value is a percentile versus the past 30 days: 90 means higher than 90% of that month",
                "feature_percentiles": pc}
    if form == "R3":
        return {"market_summary": narrative(o, pc)}
    p = float(p_model[j])
    return {"statistical_model": {
                "description": "a gradient-boosting model trained on 7 months of BTC/ETH/SOL data to estimate "
                               "the chance of a move larger than 30 bps within 2 hours",
                "probability_now": round(p, 2), "typical_probability": round(float(ytr.mean()), 2),
                "most_influential_inputs_now": {q: f"{pc.get(q, 'n/a')}th percentile" for q in TOP if q in pc}},
            "market_summary": narrative(o, pc)}


QUESTION = {"opportunity": {
    "type": "score",
    "instructions": "Considering everything in the state, how likely is it that BTC makes a tradable move "
                    "(well beyond a 0.08% round-trip fee, i.e. more than 0.30%) within the next 2 hours?",
    "criteria": ["Dead market: little chance of a tradable move", "Low", "Moderate", "High: a tradable move is likely"]}}


def ask(state):
    body = json.dumps({"model": "typesafe/jev-1.13", "state": state, "questions": QUESTION}).encode()
    req = urllib.request.Request(URL, data=body, method="POST",
                                 headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    err = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}: {e.read()[:200]!r}"
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
        time.sleep(2 * (attempt + 1))
    return {"error": err}


FORMS = ("R0", "R1", "R2", "R3", "R4")
if "--one" in sys.argv:
    for form in FORMS:
        st = state_for(form, test[-1], len(test) - 1)
        resp = ask(st)
        print(form, json.dumps(st)[:400], "\n  ->", json.dumps(resp.get("answers", resp))[:200],
              resp.get("usage", {}).get("input_tokens"), "tok\n")
    sys.exit()

scores, cost, errs = {}, 0.0, {}
for form in FORMS:
    states = [state_for(form, o, j) for j, o in enumerate(test)]
    with cf.ThreadPoolExecutor(8) as ex:
        resps = list(ex.map(ask, states))
    s = []
    for r in resps:
        if "answers" in r:
            s.append(r["answers"]["opportunity"]["score"]); cost += r.get("usage", {}).get("cost") or 0
        else:
            s.append(np.nan); errs[form] = errs.get(form, 0) + 1
    scores[form] = np.array(s)
    print(f"{form} done, errors {errs.get(form, 0)}, cost so far ${cost:.4f}", flush=True)

ok = ~np.any([np.isnan(scores[f]) for f in FORMS], axis=0)
y = yte[ok]
rk = lambda a: np.argsort(np.argsort(a)) / (len(a) - 1)
cand = {"model": p_model[ok], "trailing_range_2h": Xte[ok][:, FEATS.index("range_2h_bps")]}
for f in FORMS:
    cand["jev_" + f] = scores[f][ok]
best = max(FORMS, key=lambda f: roc_auc_score(y, scores[f][ok]))
cand["rankavg_model_jev_" + best] = (rk(p_model[ok]) + rk(scores[best][ok])) / 2


def paired(a, b, reps=2000):
    rng, d = random.Random(0), []
    n = len(y)
    for _ in range(reps):
        i = [rng.randrange(n) for _ in range(n)]
        if y[i].min() == y[i].max():
            continue
        d.append(roc_auc_score(y[i], a[i]) - roc_auc_score(y[i], b[i]))
    d.sort()
    return {"mean": round(float(np.mean(d)), 3), "ci95": [round(d[int(.025 * len(d))], 3), round(d[int(.975 * len(d))], 3)],
            "p_le_0": round(float(np.mean(np.array(d) <= 0)), 3)}


def top30(s):
    w = s >= np.quantile(s, 0.7)
    return {"precision": round(float(y[w].mean()), 3), "recall": round(float(y[w].sum() / y.sum()), 3)}


summary = {
    "n_test": int(ok.sum()), "test_base_rate": round(float(y.mean()), 3), "train_n": len(train),
    "cost_usd": round(cost, 4), "errors": errs,
    "auc": {k: round(float(roc_auc_score(y, v)), 3) for k, v in cand.items()},
    "top30_wake": {k: top30(v) for k, v in cand.items()},
    "distinct_jev_values": {f: int(len(set(np.round(scores[f][ok], 2)))) for f in FORMS},
    "spearman_jev_vs_model": {f: round(float(np.corrcoef(rk(scores[f][ok]), rk(p_model[ok]))[0, 1]), 3) for f in FORMS},
    "best_form": best,
    "paired_best_jev_minus_model": paired(scores[best][ok], p_model[ok]),
    "paired_rankavg_minus_model": paired(cand["rankavg_model_jev_" + best], p_model[ok]),
    "model_top_features": {k: round(float(v), 4) for k, v in list(importance.items())[:8]},
}
print("SUMMARY " + json.dumps(summary, ensure_ascii=False))
with open("spike3c_scores.json", "w") as fh:
    json.dump({"t": [o["t"].isoformat() for o in test], "net": [o["net"] for o in test], "model": p_model.tolist(),
               **{f: scores[f].tolist() for f in FORMS}}, fh)

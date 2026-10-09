"""Spike 4: playing the trader -- how should a data model and Jev cooperate?

The objective is the trader's, not a statistician's: NET bps per trade after
the 8 bps round trip. Every pattern below trades only where the data model says
a 风口 is likely (it predicts THAT a big move comes, not which way), holds 2 h,
and differs only in how the direction is chosen.

Discipline, fixed before any result:
  train  2026-01-01 .. 2026-07-15   fit the 风口 model and any direction model
  val    2026-07-16 .. TEST_START-1d   iterate on patterns, prompts, thresholds HERE
  test   last 45 days               run ONCE, with --final, after val is closed
Jev responses are cached in jev_cache.jsonl so iterating costs nothing twice.
"""
import concurrent.futures as cf
import hashlib
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

KEY = os.environ.get("OPENROUTER_API_KEY")
URL = "https://openrouter.ai/api/alpha/decisions"
STEP, LOOK, FWD, FEE = 120, 240, 120, 8.0
PAIRS = ("BTC/USD", "ETH/USD", "SOL/USD")
GATE_Q = float(os.environ.get("GATE_Q", "0.65"))   # trade the top 35% by 风口 probability
FINAL = "--final" in sys.argv

# ---------------- data ----------------
raw = {p: {} for p in PAIRS}
with open(sys.argv[1]) as f:
    next(f)
    for line in f:
        p, m, h, l, c, v = line.rstrip("\n").replace('"', "").split(",")
        raw[p][m] = (float(h), float(l), float(c), float(v))
ts = lambda m: datetime.fromisoformat(m).replace(tzinfo=timezone.utc).timestamp()
t0 = min(ts(m) for m in raw["BTC/USD"]); t1 = max(ts(m) for m in raw["BTC/USD"])
N = int((t1 - t0) // 60) + 1
A = {}
for p in PAIRS:
    arr = np.full((N, 4), np.nan)
    for m, row in raw[p].items():
        arr[int((ts(m) - t0) // 60)] = row
    A[p] = arr
del raw
when = lambda k: datetime.fromtimestamp(t0 + 60 * k, tz=timezone.utc)


def ffill(x):
    c = x[:, 2].copy()
    for i in range(1, len(c)):
        if np.isnan(c[i]):
            c[i] = c[i - 1]
    return c


def features(k):
    w = {p: A[p][k - LOOK + 1:k + 1] for p in PAIRS}
    if any(np.isnan(w[p][:, 2]).mean() > 0.1 for p in PAIRS) or np.isnan(w["BTC/USD"][-1, 2]):
        return None
    b = w["BTC/USD"]; c = ffill(b); last = c[-1]
    r = np.diff(np.log(c)) * 1e4
    hi, lo, vol = b[:, 0], b[:, 1], np.nan_to_num(b[:, 3])
    rng = lambda n: (np.nanmax(hi[-n:]) - np.nanmin(lo[-n:])) / last * 1e4
    e, s = ffill(w["ETH/USD"]), ffill(w["SOL/USD"])
    r5 = lambda x: np.diff(np.log(x[::5])) * 1e4
    t = when(k)
    return {
        "range_30m_bps": rng(30), "range_2h_bps": rng(120), "range_4h_bps": rng(240),
        "rv_30m_bps": float(np.std(r[-30:]) * math.sqrt(30)), "rv_4h_bps": float(np.std(r) * math.sqrt(240)),
        "range_2h_vs_prev_2h": rng(120) / max(1e-9, (np.nanmax(hi[:120]) - np.nanmin(lo[:120])) / last * 1e4),
        "volume_30m_vs_4h": float(vol[-30:].mean() / max(1e-9, vol.mean())), "volume_4h_btc": float(vol.sum()),
        "net_move_30m_bps": float((c[-1] / c[-31] - 1) * 1e4), "net_move_2h_bps": float((c[-1] / c[-121] - 1) * 1e4),
        "net_move_4h_bps": float((c[-1] / c[0] - 1) * 1e4),
        "trend_efficiency_2h": float(abs(c[-1] - c[-121]) / max(1e-9, np.sum(np.abs(np.diff(c[-121:]))))),
        "position_in_4h_range": float((last - np.nanmin(lo)) / max(1e-9, np.nanmax(hi) - np.nanmin(lo))),
        "max_1m_move_30m_bps": float(np.max(np.abs(r[-30:]))),
        "eth_net_move_2h_bps": float((e[-1] / e[-121] - 1) * 1e4), "sol_net_move_2h_bps": float((s[-1] / s[-121] - 1) * 1e4),
        "eth_net_move_30m_bps": float((e[-1] / e[-31] - 1) * 1e4), "sol_net_move_30m_bps": float((s[-1] / s[-31] - 1) * 1e4),
        "btc_eth_corr_4h": float(np.corrcoef(r5(c), r5(e))[0, 1]),
        "hour_utc": t.hour, "weekday": t.weekday(),
    }


def fwd(k):
    b = A["BTC/USD"]
    if k + FWD >= N or np.isnan(b[k + FWD, 2]) or np.isnan(b[k + 1:k + FWD + 1, 2]).mean() > 0.1:
        return None
    return (b[k + FWD, 2] / b[k, 2] - 1) * 1e4


first = LOOK + (-(int(t0 // 60) + LOOK)) % STEP
origins = []
for k in range(first, N - FWD - 1, STEP):
    f, y = features(k), fwd(k)
    if f and y is not None:
        origins.append({"k": k, "t": when(k), "f": f, "net": y})
TEST_START = when(N - 1).timestamp() - 45 * 86400
VAL_START = datetime(2026, 7, 16, tzinfo=timezone.utc).timestamp()
train = [o for o in origins if o["t"].timestamp() < VAL_START - 86400]
val = [o for o in origins if VAL_START <= o["t"].timestamp() < TEST_START - 86400]
test = [o for o in origins if o["t"].timestamp() >= TEST_START]
FEATS = list(origins[0]["f"])
X = lambda os_: np.array([[o["f"][q] for q in FEATS] for o in os_])
big = lambda os_: np.array([abs(o["net"]) > 30 for o in os_], int)

WF_MONTHS = [datetime(2026, m, 1, tzinfo=timezone.utc).timestamp() for m in (3, 4, 5, 6, 7, 8)]
WF_END = TEST_START - 86400


def fit_wind(hist):
    return HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=300, l2_regularization=1.0,
                                          min_samples_leaf=40, random_state=0).fit(X(hist), big(hist))


def periods():
    """(history, evaluation) pairs: each month traded with models fit only on what came before it."""
    edges = WF_MONTHS + [WF_END]
    out = []
    for a, b in zip(edges, edges[1:]):
        out.append(([o for o in origins if o["t"].timestamp() < a - 86400],
                    [o for o in origins if a <= o["t"].timestamp() < b]))
    if FINAL:
        out.append(([o for o in origins if o["t"].timestamp() < TEST_START - 86400], test))
    return out


G = {"val": [], "test": []}
for hist, ev in periods():
    wm = fit_wind(hist)
    gate = float(np.quantile(wm.predict_proba(X(hist))[:, 1], GATE_Q))
    for o in hist:
        o.setdefault("hist_p", None)
    ph = wm.predict_proba(X(hist))[:, 1]
    pe = wm.predict_proba(X(ev))[:, 1]
    gated_hist = [o for o, p in zip(hist, ph) if p >= gate and o["t"] >= datetime(2026, 2, 1, tzinfo=timezone.utc)]
    gated_ev = [o for o, p in zip(ev, pe) if p >= gate]
    G["test" if ev is test else "val"].append((gated_hist, gated_ev))
need = {id(o): o for pairs in G.values() for h, e in pairs for o in h + e}
print(f"walk-forward periods: {len(G['val'])} val{' + test' if FINAL else ''}; "
      f"val gated trades {sum(len(e) for h, e in G['val'])}; distinct origins needing Jev {len(need)}", flush=True)

# ---------------- percentiles + narrative (Jev's best form, spike 3c) ----------------
by_t = sorted(origins, key=lambda o: o["t"])
pos = {id(o): i for i, o in enumerate(by_t)}


def pct(o):
    i = pos[id(o)]
    past = [q for q in by_t[max(0, i - 360):i] if (o["t"] - q["t"]).total_seconds() <= 30 * 86400]
    return {q: round(100 * sum(z["f"][q] < o["f"][q] for z in past) / max(1, len(past)))
            for q in FEATS if q not in ("hour_utc", "weekday")}


def lvl(p):
    return ("extremely low" if p < 5 else "very low" if p < 15 else "low" if p < 35 else "typical" if p < 65
            else "high" if p < 85 else "very high" if p < 95 else "extremely high")


def mv(x):
    return f"{'up' if x > 0 else 'down'} {abs(x):.0f} bps"


def narrative(o):
    f, pc = o["f"], pct(o)
    pull = ("continuing in the same direction" if f["net_move_30m_bps"] * f["net_move_2h_bps"] > 0
            and abs(f["net_move_30m_bps"]) > 0.3 * abs(f["net_move_2h_bps"]) else
            "pulling back against it" if f["net_move_30m_bps"] * f["net_move_2h_bps"] < 0 else "stalling")
    return " ".join([
        f"It is {o['t'].strftime('%A %H:%M')} UTC.",
        f"BTC volatility is {lvl(pc['rv_4h_bps'])} for the month over 4 hours ({pc['rv_4h_bps']} percentile) "
        f"and {lvl(pc['rv_30m_bps'])} over the last 30 minutes ({pc['rv_30m_bps']} percentile).",
        f"The 2-hour range is {'expanding' if f['range_2h_vs_prev_2h'] > 1.15 else 'contracting' if f['range_2h_vs_prev_2h'] < 0.85 else 'steady'} versus the 2 hours before.",
        f"BTC is {mv(f['net_move_4h_bps'])} over 4 hours and {mv(f['net_move_2h_bps'])} over 2 hours; "
        f"the last 30 minutes are {mv(f['net_move_30m_bps'])}, {pull}.",
        f"The 2-hour move was {'a clean one-way move' if f['trend_efficiency_2h'] > 0.5 else 'choppy, mostly back and forth'} "
        f"(efficiency {f['trend_efficiency_2h']:.2f}, {lvl(pc['trend_efficiency_2h'])} for the month).",
        f"Price sits at {100 * f['position_in_4h_range']:.0f}% of its 4-hour range.",
        f"Volume in the last 30 minutes is {f['volume_30m_vs_4h']:.1f}x the 4-hour average ({lvl(pc['volume_30m_vs_4h'])}).",
        f"Over 2 hours ETH is {mv(f['eth_net_move_2h_bps'])} and SOL {mv(f['sol_net_move_2h_bps'])}; over 30 minutes ETH is "
        f"{mv(f['eth_net_move_30m_bps'])} and SOL {mv(f['sol_net_move_30m_bps'])}.",
        f"The largest single-minute BTC move in the last 30 minutes was {f['max_1m_move_30m_bps']:.0f} bps ({lvl(pc['max_1m_move_30m_bps'])}).",
    ])


QUESTIONS = {
    "direction": {"type": "choice",
                  "instructions": "If BTC makes a move larger than 0.30% in the next 2 hours, which direction is it more likely to be?",
                  "criteria": {"up": "Higher", "down": "Lower", "unclear": "No meaningful edge either way"}},
    "regime": {"type": "choice",
               "instructions": "What kind of market is BTC in right now?",
               "criteria": {"continuation": "A trend that is likely to keep going",
                            "reversion": "An overextended move that is likely to snap back",
                            "breakout_pending": "Compressed and waiting for a break, direction undecided",
                            "unclear": None}},
    "exhausted": {"type": "noul",
                  "instructions": "Does BTC's most recent move look exhausted -- a sharp push that is already stalling or reversing?"},
    "trend_quality": {"type": "score", "instructions": "How clean and persistent is BTC's current trend?",
                      "criteria": ["No trend: choppy", "Weak", "Moderate", "Strong and clean"]},
    "leadership": {"type": "choice", "instructions": "Who is leading the crypto market's current move?",
                   "criteria": {"btc": "BTC leads, ETH and SOL follow or lag", "alts": "ETH and/or SOL lead",
                                "together": "All move together", "mixed": "No clear leader or they disagree"}},
}
QHASH = hashlib.sha256(json.dumps(QUESTIONS, sort_keys=True).encode()).hexdigest()[:8]
CACHE = "jev_cache.jsonl"
cache = {}
if os.path.exists(CACHE):
    for line in open(CACHE):
        d = json.loads(line); cache[d["key"]] = d["resp"]


def jev_state(o):
    # v2: narrative only. 3c showed Jev echoes a model it is shown, and keeping the model out
    # makes each origin's answers independent of whichever walk-forward model is current.
    return {"market_summary": narrative(o)}


def ask(o):
    st = jev_state(o)
    key = QHASH + ":" + hashlib.sha256(json.dumps(st, sort_keys=True).encode()).hexdigest()[:16]
    if key in cache:
        return cache[key], 0.0
    body = json.dumps({"model": "typesafe/jev-1.13", "state": st, "questions": QUESTIONS}).encode()
    req = urllib.request.Request(URL, data=body, method="POST",
                                 headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                resp = json.load(r)
            with open(CACHE, "a") as fh:
                fh.write(json.dumps({"key": key, "resp": resp}) + "\n")
            cache[key] = resp
            return resp, resp.get("usage", {}).get("cost") or 0.0
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:150]}"
            time.sleep(2 * (attempt + 1))
    return {"error": err}, 0.0


todo = list(need.values())
cost = 0.0
with cf.ThreadPoolExecutor(8) as ex:
    res = list(ex.map(ask, todo))
for o, (resp, c) in zip(todo, res):
    cost += c
    o["jev"] = resp.get("answers")
print(f"jev: {sum(o['jev'] is not None for o in todo)}/{len(todo)} answered, new cost ${cost:.4f}", flush=True)


def jfeat(o):
    a = o["jev"]
    d, rg, ld = a["direction"]["probabilities"], a["regime"]["probabilities"], a["leadership"]["probabilities"]
    return [d.get("up", 0) - d.get("down", 0), d.get("unclear", 0), rg.get("continuation", 0), rg.get("reversion", 0),
            rg.get("breakout_pending", 0), a["exhausted"]["noul"], a["trend_quality"]["score"],
            ld.get("btc", 0), ld.get("alts", 0), ld.get("together", 0)]


sgn = lambda x: 1 if x > 0 else -1 if x < 0 else 0

def hgb():
    return HistGradientBoostingClassifier(max_depth=2, learning_rate=0.05, max_iter=200, min_samples_leaf=30,
                                          l2_regularization=1.0, random_state=0)


def strategies(hist, os_):
    """side per origin: +1 long, -1 short, 0 stand aside."""
    tr = [o for o in hist if o["jev"]]
    os_ = [o for o in os_ if o["jev"]]
    if not os_:
        return os_, {}
    ytr = np.array([o["net"] > 0 for o in tr], int)
    jx = lambda z: np.array([jfeat(o) for o in z])
    dn = hgb().fit(X(tr), ytr); dj = hgb().fit(np.hstack([X(tr), jx(tr)]), ytr); djo = hgb().fit(jx(tr), ytr)
    xn, xj = X(os_), jx(os_)
    p_num, p_jev, p_jo = dn.predict_proba(xn)[:, 1], dj.predict_proba(np.hstack([xn, xj]))[:, 1], djo.predict_proba(xj)[:, 1]
    jd = [{"up": 1, "down": -1}.get(o["jev"]["direction"]["choice"], 0) for o in os_]
    S = {
        "momentum_2h": [sgn(o["f"]["net_move_2h_bps"]) for o in os_],
        "momentum_30m": [sgn(o["f"]["net_move_30m_bps"]) for o in os_],
        "reversion_30m": [-sgn(o["f"]["net_move_30m_bps"]) for o in os_],
        "jev_direction": jd,
        "fade_jev_direction [added after val run 1]": [-x for x in jd],
        "jev_router": [sgn(o["f"]["net_move_2h_bps"]) if o["jev"]["regime"]["choice"] == "continuation"
                       else -sgn(o["f"]["net_move_30m_bps"]) if o["jev"]["regime"]["choice"] == "reversion" else 0 for o in os_],
        "reversion_30m_only_if_jev_says_reversion": [-sgn(o["f"]["net_move_30m_bps"]) if o["jev"]["regime"]["choice"] == "reversion" else 0 for o in os_],
        "dirmodel_numeric": [sgn(p - 0.5) for p in p_num],
        "dirmodel_numeric+jev": [sgn(p - 0.5) for p in p_jev],
        "dirmodel_jev_only": [sgn(p - 0.5) for p in p_jo],
    }
    return os_, S


def evaluate(os_, S):
    out = {}
    for name, sides in S.items():
        pnl = [s * o["net"] - FEE for s, o in zip(sides, os_) if s != 0]
        if len(pnl) < 5:
            out[name] = {"trades": len(pnl)}
            continue
        rng, bs = random.Random(0), []
        for _ in range(2000):
            bs.append(statistics.mean(rng.choice(pnl) for _ in pnl))
        bs.sort()
        out[name] = {"trades": len(pnl), "net_bps_per_trade": round(statistics.mean(pnl), 1),
                     "ci95": [round(bs[50], 1), round(bs[1950], 1)], "hit": round(sum(p > 0 for p in pnl) / len(pnl), 2),
                     "total_bps": round(sum(pnl))}
    return out


report = {"jev_new_cost_usd": round(cost, 4)}
for name in ("val", "test") if FINAL else ("val",):
    pooled_os, pooled_S, per_month = [], {}, []
    for hist, ev in G[name]:
        os_, S = strategies(hist, ev)
        if not os_:
            continue
        pooled_os += os_
        for k, v in S.items():
            pooled_S.setdefault(k, []).extend(v)
        per_month.append((os_[0]["t"].strftime("%Y-%m"), {k: round(sum(s_ * o["net"] - FEE for s_, o in zip(v, os_) if s_)) for k, v in S.items()}))
    # pre-registered before --final: does the Jev filter itself separate reversion trades?
    rev = [(-sgn(o["f"]["net_move_30m_bps"]) * o["net"] - FEE, o["jev"]["regime"]["choice"] == "reversion")
           for o in pooled_os if sgn(o["f"]["net_move_30m_bps"]) != 0]
    yes = [p_ for p_, f_ in rev if f_]; no = [p_ for p_, f_ in rev if not f_]
    rng_, diffs = random.Random(1), []
    for _ in range(2000):
        diffs.append(statistics.mean(rng_.choice(yes) for _ in yes) - statistics.mean(rng_.choice(no) for _ in no))
    diffs.sort()
    filter_test = {"jev_says_reversion_n": len(yes), "mean": round(statistics.mean(yes), 1),
                   "rest_n": len(no), "rest_mean": round(statistics.mean(no), 1),
                   "diff_ci95": [round(diffs[50], 1), round(diffs[1950], 1)],
                   "p_diff_le_0": round(sum(d <= 0 for d in diffs) / len(diffs), 3)}
    report[name] = {"filter_test": filter_test, "gated_trades": len(pooled_os), "abs_move_mean_bps": round(statistics.mean(abs(o["net"]) for o in pooled_os), 1),
                    "strategies": evaluate(pooled_os, pooled_S), "total_bps_by_month": per_month}
print("REPORT " + json.dumps(report, ensure_ascii=False))

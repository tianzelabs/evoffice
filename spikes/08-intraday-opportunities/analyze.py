"""Reproduce a retrospective map of observed minute-close swings. No orders/LLMs."""
import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DAY = "2026-10-12"
TZ = ZoneInfo("Europe/Budapest")
REVERSAL_LOG_BPS = 30.0  # Fixed descriptive scale, not fitted to profit.


def pivots(bars, threshold):
    low = high = 0
    direction = 0
    result = []
    for i, bar in enumerate(bars):
        price = bar["c"]
        if direction == 0:
            if price < bars[low]["c"]:
                low = i
            if price > bars[high]["c"]:
                high = i
            if 1e4 * math.log(price / bars[low]["c"]) >= threshold:
                result.append((low, i, "low"))
                direction, high = 1, i
            elif 1e4 * math.log(bars[high]["c"] / price) >= threshold:
                result.append((high, i, "high"))
                direction, low = -1, i
        elif direction == 1:
            if price > bars[high]["c"]:
                high = i
            if 1e4 * math.log(bars[high]["c"] / price) >= threshold:
                result.append((high, i, "high"))
                direction, low = -1, i
        else:
            if price < bars[low]["c"]:
                low = i
            if 1e4 * math.log(price / bars[low]["c"]) >= threshold:
                result.append((low, i, "low"))
                direction, high = 1, i
    return result, direction, high if direction == 1 else low


def fee_net(entry, exit_price, sign, fee):
    # Fee on entry and exit notionals, normalized by entry notional.
    gross = sign * (exit_price / entry - 1) * 1e4
    fees = fee * (1 + exit_price / entry) * 1e4
    return gross, fees, gross - fees


def main():
    raw_path = ROOT / "data/raw_context.json"
    raw = json.loads(raw_path.read_text())
    quote = json.loads((ROOT / "data/price_snapshot.json").read_text())
    fee = quote["fees"]["taker"]
    bars = []
    for original in raw:
        dt = datetime.fromisoformat(original["m"]).replace(tzinfo=timezone.utc).astimezone(TZ)
        if dt.date().isoformat() == DAY:
            bars.append({**original, "local": dt.isoformat(), "epoch": int(dt.timestamp())})
    assert bars and all(b["epoch"] > a["epoch"] for a, b in zip(bars, bars[1:]))
    assert all(0 < b["l"] <= min(b["o"], b["c"]) <= max(b["o"], b["c"]) <= b["h"] for b in bars)
    missing = []
    for a, b in zip(bars, bars[1:]):
        for epoch in range(a["epoch"] + 60, b["epoch"], 60):
            missing.append(datetime.fromtimestamp(epoch, TZ).isoformat())
    ps, direction, pending = pivots(bars, REVERSAL_LOG_BPS)
    legs = []
    for (start, confirm_start, kind), (end, confirm_end, _) in zip(ps, ps[1:]):
        sign = 1 if kind == "low" else -1
        a, b = bars[start], bars[end]
        gross, fees, net = fee_net(a["c"], b["c"], sign, fee)
        leg = {"side": "long" if sign == 1 else "short", "entry_index": start, "exit_index": end,
               "entry": a["local"], "exit": b["local"], "entry_price": a["c"], "exit_price": b["c"],
               "gross_bps": gross, "fee_bps": fees, "fee_only_net_bps": net,
               "minutes": (b["epoch"] - a["epoch"]) // 60,
               "day_boundary_entry": start == 0,
               "missing_minutes_within_leg": (b["epoch"] - a["epoch"]) // 60 - (end - start),
               "entry_extreme_confirmed_after_bar": bars[confirm_start]["local"],
               "exit_extreme_confirmed_after_bar": bars[confirm_end]["local"]}
        # Descriptive causal-delay counterfactual, NOT a validated trading rule:
        # after a confirmation candle closes, reference the next available
        # minute open only if it is immediately adjacent; never bridge a gap.
        if all(i + 1 < len(bars) and bars[i+1]["epoch"] - bars[i]["epoch"] == 60
               for i in [confirm_start, confirm_end]):
            ca, cb = bars[confirm_start+1], bars[confirm_end+1]
            cg, cf, cn = fee_net(ca["o"], cb["o"], sign, fee)
            leg["confirmation_proxy"] = {"entry": ca["local"], "exit": cb["local"],
                "entry_price": ca["o"], "exit_price": cb["o"],
                "gross_bps": cg, "fee_bps": cf, "fee_only_net_bps": cn}
        legs.append(leg)
    selected = sorted(sorted([x for x in legs if not x["day_boundary_entry"]],
                             key=lambda x: x["gross_bps"], reverse=True)[:10], key=lambda x:x["entry"])
    for i, x in enumerate(selected, 1):
        x["id"] = i
    output = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "day": DAY,
        "timezone": str(TZ), "instrument": "Kraken Futures PF_XBTUSD", "rows": len(bars),
        "first_bar": bars[0]["local"], "last_bar": bars[-1]["local"],
        "source": "http://100.86.90.65:8710/market/context?minutes=2880",
        "raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        "taker_fee_per_side": fee, "missing_minutes": missing,
        "reversal_log_bps": REVERSAL_LOG_BPS,
        "selection": "Largest 10 observed-close confirmed legs, excluding day-boundary entry; sorted by time",
        "timing": "Times label the start of the minute candle; its close is available one minute later",
        "limitations": "Hindsight endpoints, not forecast signals or verified fills. Missing candles retained as gaps. Fee-only net omits spread, funding, impact and latency. No maker fills assumed. No long-term holdout accessed.",
        "legs": legs, "selected": selected,
        "pending_tail": {"side": "long" if direction == 1 else "short",
                         "start": bars[ps[-1][0]]["local"], "observed_extreme": bars[pending]["local"],
                         "observed_extreme_price": bars[pending]["c"], "exit_confirmed": False},
        "scale_counts_not_profit_tuning": {str(k): len(pivots(bars,k)[0])-1 for k in [20,30,50]}}
    (ROOT / "opportunities.json").write_text(json.dumps(output, ensure_ascii=False, indent=2))
    fields = ["id", "side", "entry", "entry_price", "exit", "exit_price", "gross_bps", "fee_only_net_bps", "minutes", "missing_minutes_within_leg"]
    with (ROOT / "opportunities.csv").open("w",newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(selected)
    plot(bars, selected, missing)
    print(json.dumps({k:output[k] for k in ["rows","first_bar","last_bar","missing_minutes","scale_counts_not_profit_tuning","selected"]},ensure_ascii=False,indent=2))


def plot(bars, selected, missing):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import numpy as np
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    fig, (ax, bx) = plt.subplots(2,1,figsize=(15,8),gridspec_kw={"height_ratios":[2.7,1]},layout="constrained")
    timestamps, prices = [], []
    for i, b in enumerate(bars):
        if i and b["epoch"] - bars[i-1]["epoch"] != 60:
            timestamps.append(datetime.fromisoformat(b["local"])); prices.append(float("nan"))
        timestamps.append(datetime.fromisoformat(b["local"])); prices.append(b["c"])
    ax.plot(timestamps,prices,color="#94a3b8",lw=1,label="Observed minute close")
    for leg in selected:
        part = bars[leg["entry_index"]:leg["exit_index"]+1]
        t, y = [], []
        for i, b in enumerate(part):
            if i and b["epoch"]-part[i-1]["epoch"] != 60:
                t.append(datetime.fromisoformat(b["local"])); y.append(float("nan"))
            t.append(datetime.fromisoformat(b["local"])); y.append(b["c"])
        color = "#059669" if leg["side"] == "long" else "#dc2626"
        ax.plot(t,y,color=color,lw=2)
        mid = part[len(part)//2]
        ax.annotate(str(leg["id"]),(datetime.fromisoformat(mid["local"]),mid["c"]),
                    xytext=(0,18 if leg["side"]=="long" else -24),textcoords="offset points",
                    ha="center",fontweight="bold",color=color,bbox={"facecolor":"white","edgecolor":color,"boxstyle":"round,pad=.25"})
    ax.set_title("BTC perpetual: largest 10 retrospective swings | 12 Oct 2026 | Europe/Budapest (UTC+2)",loc="left",fontweight="bold")
    ax.set_ylabel("PF_XBTUSD close (USD)")
    ax.set_xlim(datetime.fromisoformat(bars[0]["local"]),datetime.fromisoformat(bars[-1]["local"]))
    ax.xaxis.set_major_locator(mdates.HourLocator(byhour=range(0,24,2),tz=TZ))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M",tz=TZ))
    ax.grid(alpha=.15)
    indexes = np.arange(len(selected))
    bx.bar(indexes-.2,[x["fee_only_net_bps"] for x in selected],.4,color="#64748b",label="Perfect hindsight endpoints, fees deducted")
    bx.bar(indexes+.2,[x.get("confirmation_proxy",{}).get("fee_only_net_bps",float("nan")) for x in selected],.4,color="#d97706",label="After 30 bps reversal confirmation, next-open proxy")
    bx.axhline(0,color="#475569",lw=.8)
    bx.set_xticks(indexes,[str(x["id"]) for x in selected]); bx.set_xlabel("Swing ID (see report)"); bx.set_ylabel("Fee-only net (bps)")
    bx.set_ylim(top=max(x["fee_only_net_bps"] for x in selected)*1.3)
    bx.legend(fontsize=9,loc="upper left",ncol=2); bx.grid(axis="y",alpha=.15)
    fig.suptitle("Green: upward leg / Red: downward leg. Endpoints are hindsight; neither bars nor delay proxies verify executable fills.",fontsize=10,color="#475569")
    fig.savefig(ROOT/"intraday-swings.png",dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    main()

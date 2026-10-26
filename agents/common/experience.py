"""Historical market episodes for shared retrieval, never a fitted trading policy.

Matching uses pre-decision features only. All outcomes, including losses, remain.
This module performs no I/O, model calls, voting, order placement or policy search.
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import datetime, timezone
import math
import statistics

FEATURES = ("return_1h_bps", "return_4h_bps", "return_8h_bps", "rv_4h_bps")
HORIZONS = (4, 8)
VERSION = 1


def epoch(value: str) -> int:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return int((dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt).timestamp())


def iso(value: int) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def ordered(bars: list[dict]) -> tuple[list[dict], list[int]]:
    rows = sorted(bars, key=lambda b: b["m"])
    ts = [epoch(b["m"]) for b in rows]
    if len(set(ts)) != len(ts):
        raise ValueError("duplicate candles")
    if any(not math.isfinite(float(b["c"])) or b["c"] <= 0 for b in rows):
        raise ValueError("invalid close")
    return rows, ts


def state_features(bars: list[dict], as_of: int) -> dict:
    rows, ts = ordered([b for b in bars if epoch(b["m"]) + 60 <= as_of])
    if not rows:
        return {"available": False, "reason": "no completed candles"}
    end = ts[-1]
    start = bisect_right(ts, end - 8*3600) - 1
    if start < 0:
        return {"available": False, "reason": "less than 8h history"}
    features, lags = {}, {}
    for h in (1,4,8):
        target = end - h*3600
        i = bisect_right(ts, target)-1
        if i < 0:
            return {"available": False, "reason": f"no {h}h anchor"}
        lags[str(h)] = (target-ts[i])//60
        features[f"return_{h}h_bps"] = (rows[-1]["c"]/rows[i]["c"]-1)*1e4
    rv = sum((math.log(rows[i]["c"]/rows[i-1]["c"])*1e4)**2 for i in range(1,len(rows))
             if ts[i]>end-4*3600 and ts[i]-ts[i-1]==60)
    features["rv_4h_bps"] = math.sqrt(rv)
    return {"available": True, "features": features, "information_cutoff": iso(end+60),
            "age_s": max(0,as_of-end-60), "anchor_lag_minutes": lags,
            "missing_minutes_8h": (end-ts[start])//60+1-(len(rows)-start)}


def build_atlas(data: dict, allowed_before: int, taker_fee: float) -> dict:
    rows, ts = ordered(data["bars"])
    if ts and ts[-1]+60 > allowed_before:
        raise ValueError("training data reaches beyond the development boundary")
    pos = {t:i for i,t in enumerate(ts)}
    gaps = [0]
    for i in range(1,len(ts)):
        gaps.append(gaps[-1]+int(ts[i]-ts[i-1]!=60))
    funding = {int(k):float(v) for k,v in data.get("funding",{}).items()}
    episodes, eligible = [], 0
    for i, t in enumerate(ts):
        # Four-hour UTC grid, fixed before inspecting returns. Adjacent 8h labels overlap.
        if t % (4*3600) or t-8*3600 < ts[0] or t+8*3600 > ts[-1]:
            continue
        eligible += 1
        lo, hi = pos.get(t-8*3600), pos.get(t+8*3600)
        if lo is None or hi is None or gaps[hi]!=gaps[lo]:
            continue
        current = state_features(rows[lo:i+1],t+60)
        outcomes = {}
        for h in HORIZONS:
            j = pos[t+h*3600]
            entry, exit_ = rows[i]["c"], rows[j]["c"]
            path = rows[i+1:j+1]
            gross = (exit_/entry-1)*1e4
            fees = taker_fee*(1+exit_/entry)*1e4
            hours = list(range((t//3600+1)*3600,ts[j]+1,3600))
            complete = all(hour in funding for hour in hours)
            fund = sum(funding[hour] for hour in hours)*1e4 if complete else None
            low = min([entry]+[b["l"] for b in path])
            high = max([entry]+[b["h"] for b in path])
            outcomes[str(h)] = {
                "observed_until": iso(ts[j]+60), "gross_long_bps": gross,
                "taker_fee_only_long_bps": gross-fees,
                "taker_fee_only_short_bps": -gross-fees,
                "funding_complete": complete, "long_funding_cost_proxy_bps": fund,
                "net_long_proxy_bps": gross-fees-fund if complete else None,
                "net_short_proxy_bps": -gross-fees+fund if complete else None,
                "long_mae_bps": (1-low/entry)*1e4, "long_mfe_bps": (high/entry-1)*1e4,
                "short_mae_bps": (high/entry-1)*1e4, "short_mfe_bps": (1-low/entry)*1e4,
            }
        episodes.append({"id":"train:"+str(t), "decision_time":iso(t+60),
                         "features":current["features"], "outcomes":outcomes})
    return {"schema_version": VERSION, "source_kind":"development_train", "bars":len(rows),
            "first_bar":rows[0]["m"] if rows else None, "last_bar":rows[-1]["m"] if rows else None,
            "allowed_before":iso(allowed_before), "eligible_grid_points":eligible,
            "excluded_for_gaps":eligible-len(episodes), "episode_count":len(episodes),
            "features":list(FEATURES), "grid_hours":4, "horizons_hours":list(HORIZONS),
            "episodes":episodes,
            "limitations":["Development analogues, not an estimated probability of future success",
                "Strictly contiguous 16h windows create selection toward complete-data periods",
                "8h outcomes overlap on a 4h grid; counts are not independent sample sizes",
                "Close-price proxies omit spread, impact, latency, queue and maker execution",
                "Funding uses entry-notional hourly-rate proxy; missing hours never zero-filled",
                "OHLC excursions are gross price excursions, not executable stops or net risk bounds"]}


def retrieve(atlas: dict, state: dict, limit: int = 20) -> dict:
    summary = {k:v for k,v in atlas.items() if k!='episodes'}
    summary.update({"current_state":state, "analogues":[], "outcome_summary":{}})
    if not state.get("available") or not atlas["episodes"]:
        return summary
    query_time = epoch(state["information_cutoff"])
    # A retrospective query may not retrieve a case whose label is not yet known.
    episodes = [e for e in atlas["episodes"] if epoch(e["outcomes"]["8"]["observed_until"])<=query_time]
    if not episodes:
        return summary
    scales = {}
    for name in FEATURES:
        values = [e["features"][name] for e in episodes]
        scales[name] = statistics.pstdev(values) or 1.0
    def distance(e):
        return math.sqrt(sum(((e['features'][k]-state['features'][k])/scales[k])**2 for k in FEATURES))
    selected = sorted(episodes,key=lambda e:(distance(e),e["decision_time"]))[:max(1,min(limit,20))]
    summary['analogues'] = [{**e,"distance":round(distance(e),4)} for e in selected]
    summary['matching'] = {"method":"Euclidean distance over 4 prespecified features; historical scale only",
                           "scales":scales,"selected":len(selected),"pool":len(episodes)}
    for h in ('4','8'):
        result = {}
        for side in ('long','short'):
            values = [e['outcomes'][h]['net_'+side+'_proxy_bps'] for e in selected
                      if e['outcomes'][h]['net_'+side+'_proxy_bps'] is not None]
            result[side] = {"complete_cost_cases":len(values),
                "mean_net_proxy_bps":round(statistics.mean(values),2) if values else None,
                "median_net_proxy_bps":round(statistics.median(values),2) if values else None,
                "positive_cases":sum(v>0 for v in values),
                "worst_net_proxy_bps":round(min(values),2) if values else None,
                "largest_gross_mae_bps":round(max(e['outcomes'][h][side+'_mae_bps'] for e in selected),2)}
        summary['outcome_summary'][h] = result
    return summary


def render_experience(result: dict) -> str:
    lines = [f"SHARED HISTORICAL EXPERIENCE: {result['bars']} development candles; "
             f"{result['episode_count']} complete episodes ({result['first_bar']} to {result['last_bar']})."]
    state = result['current_state']
    if not state.get('available'):
        return '\n'.join(lines+["Current matching unavailable: "+state['reason']])
    lines.append(f"Current cutoff {state['information_cutoff']}; age {state['age_s']}s; "
                 f"missing minutes in 8h {state['missing_minutes_8h']}. Features="+
                 json_numbers(state['features']))
    lines += ['| Horizon | Side | Cost-complete cases | Mean net proxy bps | Positive cases | Worst net proxy bps | Largest gross MAE bps |',
              '|---|---|---:|---:|---:|---:|---:|']
    for h,r in result['outcome_summary'].items():
        for side,v in r.items():
            lines.append(f"| {h}h | {side} | {v['complete_cost_cases']} | {v['mean_net_proxy_bps']} | "
                         f"{v['positive_cases']} | {v['worst_net_proxy_bps']} | {v['largest_gross_mae_bps']} |")
    lines.append('Historical analogues are development references, not independent votes, future win probabilities or an entry rule. ' 
                 '8h labels overlap. Funding-incomplete cases excluded from net summaries. Spread/impact/latency omitted. '
                 'Inspect /research/experience for case IDs, losing cases, source dates and matching distances.')
    return '\n'.join(lines)


def compact_experience(result: dict) -> dict:
    """Keep raw case detail out of a routine model tool response."""
    return {**{k:v for k,v in result.items() if k!='analogues'},
            'case_index':[{'id':e['id'],'decision_time':e['decision_time'],'distance':e['distance']}
                          for e in result['analogues']],
            'detail_note':'Request detail=True only to inspect specific case outcomes; store data in the REPL, print summaries.'}


def json_numbers(values):
    import json
    return json.dumps({k:round(v,2) for k,v in values.items()})

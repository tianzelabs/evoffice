"""Entry point inside the evaluator sandbox: a container with no network.

    python -m server.evaluator.run /in/bars.json /in/strategy.py [--detail]

--detail (research backtests on data the trader may see) adds every trade and
splits by side and entry type; a held-out run never gets it.

Prints one JSON line of aggregates. The strategy code runs here, not in the
office server, so a strategy that misbehaves can harm only this throwaway
container -- and with no network it cannot send the held-out bars anywhere.
"""
import json
import sys

from server import fees
from server.evaluator.sim import aggregate, simulate


def _split(trades: list[dict], key: str) -> dict:
    out = {}
    for k in sorted({t[key] for t in trades}):
        out[k] = aggregate([t["pnl_bps"] for t in trades if t[key] == k])
    return out


def main(bars_path: str, code_path: str, detail: bool = False) -> dict:
    data = json.load(open(bars_path))
    bars = data["bars"] if isinstance(data, dict) else data
    funding = {int(k): v for k, v in (data.get("funding", {}) if isinstance(data, dict) else {}).items()}
    ns: dict = {}
    try:
        exec(compile(open(code_path).read(), "strategy.py", "exec"), ns)
    except Exception as e:
        return {"error": f"your code failed to load: {type(e).__name__}: {str(e)[:300]}"}
    decide = ns.get("decide")
    if not callable(decide):
        return {"error": "your code must define decide(bars) -> {'side': 'long'|'short'|None, 'hold_minutes': int}"}
    sim = simulate(bars, decide, funding)
    out = {**aggregate(sim["pnl_bps"]), "decide_errors": sim["decide_errors"], "first_error": sim["first_error"],
           "maker_entries": sim["maker_entries"], "unfilled_limit_entries": sim["unfilled_limit_entries"],
           "regime": fees.REGIME, "window": {"from": bars[0]["m"], "to": bars[-1]["m"], "bars": len(bars)}}
    if detail:
        out["by_side"] = _split(sim["trades"], "side")
        out["by_entry"] = _split(sim["trades"], "entry")
        out["by_exit"] = _split(sim["trades"], "exit")
        out["trade_list"] = sim["trades"][-400:]
    return out


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1], sys.argv[2], "--detail" in sys.argv[3:])))

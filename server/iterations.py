"""Did the change help? -- each trader's strategy versions as a timeline.

The mission is a trader that changes how it trades AND can show whether the
change helped. Live trades are too few to answer that (most versions trade
little or not at all), so each version is shown with:

- when it was measured, and which of the trader's objects make it up;
- the held-out evaluations submitted while it was current -- the comparable
  number, same unseen window, net of fees, with an interval;
- its live paper trades, if any.

Derived entirely from events and positions; nothing new is stored.
"""
from __future__ import annotations

from .store import Store


def _all(store: Store, kind: str) -> list[dict]:
    import json
    rows = store.q("SELECT id, ts, actor, payload FROM events WHERE kind = ? ORDER BY id", (kind,))
    for r in rows:
        r["payload"] = json.loads(r["payload"])
    return rows


def timeline(store: Store) -> dict:
    versions, evals = _all(store, "version"), _all(store, "evaluation")
    traders = [r["id"] for r in store.q("SELECT id FROM employees WHERE role = 'trader' ORDER BY hired_ts")]
    out = {}
    for t in traders:
        vs = [v for v in versions if v["actor"] == t]
        es = [e for e in evals if e["actor"] == t]
        rows = []
        for i, v in enumerate(vs):
            until = vs[i + 1]["ts"] if i + 1 < len(vs) else None
            mine = [e for e in es if e["ts"] >= v["ts"] and (until is None or e["ts"] < until)]
            live = store.q("SELECT COUNT(*) AS trades, ROUND(SUM(pnl), 4) AS net_pnl, "
                           "ROUND(AVG(pnl / (size * entry_px) * 10000.0), 2) AS avg_net_bps "
                           "FROM positions WHERE employee_id = ? AND strategy_version = ? AND closed_ts IS NOT NULL",
                           (t, v["payload"].get("version")))[0]
            rows.append({"version": v["payload"].get("version"), "since": v["ts"], "until": until,
                         "objects": v["payload"].get("objects", []), "live": live,
                         "evaluations": [_eval(e) for e in mine]})
        early = [e for e in es if not vs or e["ts"] < vs[0]["ts"]]
        if early:
            rows.insert(0, {"version": None, "since": None, "until": vs[0]["ts"] if vs else None, "objects": [],
                            "live": {"trades": 0}, "evaluations": [_eval(e) for e in early]})
        series = [_eval(e) for e in es if e["payload"].get("net_bps_per_trade") is not None]
        out[t] = {"versions": rows, "evaluations": series,
                  "summary": {"versions": len(vs), "evaluations": len(es),
                              "best_net_bps_per_trade": max((s["net_bps_per_trade"] for s in series), default=None),
                              "latest_net_bps_per_trade": series[-1]["net_bps_per_trade"] if series else None,
                              "any_interval_above_zero": any((s.get("ci95") or [0])[0] > 0 for s in series)}}
    return out


def _eval(e: dict) -> dict:
    p = e["payload"]
    return {"ts": e["ts"], "candidate": p.get("candidate"), "version": p.get("version"), "trades": p.get("trades"),
            "net_bps_per_trade": p.get("net_bps_per_trade"), "ci95": p.get("ci95_net_bps_per_trade"),
            "try": p.get("evaluations_used_today"), "error": p.get("error")}

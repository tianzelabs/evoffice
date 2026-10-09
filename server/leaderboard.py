"""Standings, derived from closed positions -- per employee AND per strategy version.

Scoring per version is the fix for the defect recorded on 2026-09-24: averaging
a trader's record across strategy changes mixes two different agents and
rewards the one that never changes. Here a new version starts its own row, so
"did the change help?" is a comparison of rows.

Rows come from the ROSTER, not from the data: a trader with no trades still
appears (agent-world learned this the hard way -- an idle resident that never
showed up in the table could never be noticed).
"""
from __future__ import annotations

from .store import Store

_AGG = """
    COUNT(*)                                               AS trades,
    ROUND(SUM(pnl), 4)                                     AS net_pnl,
    ROUND(AVG(pnl / (size * entry_px) * 10000.0), 2)       AS avg_net_bps,
    ROUND(AVG(CASE WHEN pnl > 0 THEN 1.0 ELSE 0.0 END), 3) AS win_rate,
    ROUND(SUM(fees), 4)                                    AS fees_paid,
    MAX(closed_ts)                                         AS last_close
"""


def standings(store: Store) -> dict:
    agg = {r["employee_id"]: r for r in store.q(
        f"SELECT employee_id, {_AGG} FROM positions WHERE closed_ts IS NOT NULL GROUP BY employee_id")}
    open_n = {r["employee_id"]: r["n"] for r in store.q(
        "SELECT employee_id, COUNT(*) AS n FROM positions WHERE closed_ts IS NULL GROUP BY employee_id")}
    by_employee = []
    for e in store.q("SELECT id, fired_ts FROM employees WHERE role = 'trader'"):
        a = agg.get(e["id"], {})
        by_employee.append({"employee": e["id"], "fired": e["fired_ts"] is not None,
                            "open_positions": open_n.get(e["id"], 0), "trades": a.get("trades", 0),
                            "net_pnl": a.get("net_pnl", 0.0), "avg_net_bps": a.get("avg_net_bps"),
                            "win_rate": a.get("win_rate"), "fees_paid": a.get("fees_paid", 0.0),
                            "last_close": a.get("last_close")})
    by_employee.sort(key=lambda r: -(r["net_pnl"] or 0.0))
    by_version = store.q(f"""
        SELECT employee_id AS employee, COALESCE(strategy_version, 'unversioned') AS strategy_version,
               MIN(opened_ts) AS first_open, {_AGG}
        FROM positions WHERE closed_ts IS NOT NULL
        GROUP BY employee_id, strategy_version ORDER BY employee_id, first_open""")
    return {"by_employee": by_employee, "by_version": by_version}

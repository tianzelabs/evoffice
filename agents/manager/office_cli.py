"""`office` -- the manager's tools as a command line, for a Codex manager to drive from its shell.

    office chat [N]                      last N chat messages
    office board                         leaderboard
    office progress                      traders' XP, levels, probation, badges
    office employees                     everyone, with traders' parameters
    office activity TRADER [N]           a trader's turns, versions, evaluations, wake reasons
    office positions TRADER              a trader's positions
    office orders TRADER                 a trader's limit orders (resting, filled, cancelled)
    office objective                     your objective ladder (minus -> plus), computed by the office
    office golive TRADER                 the checklist for moving a trader to a real Kraken account
    office market [MINUTES]              BTC price and recent 1-minute bars
    office context [MINUTES]             the market's state per minute: taker flow, book imbalance, spread,
                                         basis, funding, open interest (also market_context() in the REPL)
    office backtest FILE [--data train|recent] [--days N]
                                         run a decide(bars) strategy file through the office's own simulator
                                         (same fees and fills as the held-out exam) on data you may see
    office repl CODE | -f FILE           run Python in the office's SHARED REPL (the same namespace the
                                         trader works in) and print its output
    office repl-result ID                the output of an earlier repl run
    office task TRADER TEXT [--wait S]   give the trader a task; it runs one turn in its REPL and you get the
                                         result (waits up to S seconds, default 600)
    office task-result ID                the result of an earlier task
    office say TEXT [--to WHO] [--urgent]  speak in the public chat (does not wake the trader)
    office name NAME                     choose your own name
    office params TRADER --reason R [--heartbeat-min N] [--max-size X] [--max-hold-min N]
    office fire TRADER --reason R        fire a trader (rarely)
    office notes [--set TEXT]            read, or replace, your private notes
"""
from __future__ import annotations

import argparse
import json
import sys

from agents.common.office_client import Office
from agents.manager import ops


def main(argv: list[str]) -> str:
    ap = argparse.ArgumentParser(prog="office", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("chat"); c.add_argument("n", nargs="?", type=int, default=30)
    sub.add_parser("board")
    sub.add_parser("progress")
    sub.add_parser("employees")
    a = sub.add_parser("activity"); a.add_argument("trader"); a.add_argument("n", nargs="?", type=int, default=10)
    p = sub.add_parser("positions"); p.add_argument("trader")
    od = sub.add_parser("orders"); od.add_argument("trader")
    sub.add_parser("objective")
    gl = sub.add_parser("golive"); gl.add_argument("trader")
    rp = sub.add_parser("repl"); rp.add_argument("code", nargs="?"); rp.add_argument("-f", "--file")
    rp.add_argument("--wait", type=int, default=300)
    rr = sub.add_parser("repl-result"); rr.add_argument("id", type=int)
    tk = sub.add_parser("task"); tk.add_argument("trader"); tk.add_argument("text"); tk.add_argument("--wait", type=int, default=600)
    tr = sub.add_parser("task-result"); tr.add_argument("id", type=int)
    bt = sub.add_parser("backtest"); bt.add_argument("file"); bt.add_argument("--data", default="train")
    bt.add_argument("--days", type=float, default=30)
    cx = sub.add_parser("context"); cx.add_argument("minutes", nargs="?", type=int, default=120)
    m = sub.add_parser("market"); m.add_argument("minutes", nargs="?", type=int, default=120)   # up to 10080 (7 days)
    s = sub.add_parser("say"); s.add_argument("text"); s.add_argument("--to"); s.add_argument("--urgent", action="store_true")
    nm = sub.add_parser("name"); nm.add_argument("name")
    pr = sub.add_parser("params"); pr.add_argument("trader"); pr.add_argument("--reason", required=True)
    pr.add_argument("--heartbeat-min", type=int); pr.add_argument("--max-size", type=float); pr.add_argument("--max-hold-min", type=int)
    f = sub.add_parser("fire"); f.add_argument("trader"); f.add_argument("--reason", required=True)
    n = sub.add_parser("notes"); n.add_argument("--set")
    args = ap.parse_args(argv)
    o = Office()
    if args.cmd == "chat": return ops.read_recent_chat(o, args.n)
    if args.cmd == "board": return ops.leaderboard(o)
    if args.cmd == "progress": return ops.progress(o)
    if args.cmd == "employees": return ops.employees(o)
    if args.cmd == "activity": return ops.trader_activity(o, args.trader, args.n)
    if args.cmd == "positions": return ops.trader_positions(o, args.trader)
    if args.cmd == "orders": return ops.trader_orders(o, args.trader)
    if args.cmd == "objective": return json.dumps(o.get("/objective"), ensure_ascii=False)
    if args.cmd == "golive": return ops.golive(o, args.trader)
    if args.cmd == "market": return ops.market(o, args.minutes)
    if args.cmd == "context": return ops.context(o, args.minutes)
    if args.cmd == "repl":
        code = open(args.file).read() if args.file else args.code
        return ops.repl(o, code, args.wait) if code else "give CODE or -f FILE"
    if args.cmd == "repl-result": return ops.repl_result(o, args.id)
    if args.cmd == "task": return ops.task(o, args.trader, args.text, args.wait)
    if args.cmd == "task-result": return ops.task_result(o, args.id)
    if args.cmd == "backtest": return ops.backtest(o, open(args.file).read(), args.data, args.days)
    if args.cmd == "say": return ops.say(o, args.text, args.to, args.urgent)
    if args.cmd == "name": return ops.set_name(o, args.name)
    if args.cmd == "params":
        return ops.set_trader_params(o, args.trader, args.reason, args.heartbeat_min, args.max_size, args.max_hold_min)
    if args.cmd == "fire": return ops.fire_trader(o, args.trader, args.reason)
    if args.cmd == "notes": return ops.save_notes(args.set) if args.set is not None else (ops.read_notes() or "(no notes)")
    return ""


if __name__ == "__main__":
    print(main(sys.argv[1:]))

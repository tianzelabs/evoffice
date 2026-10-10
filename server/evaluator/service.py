"""The held-out evaluation, as the office runs it (P1.5, kept deliberately simple).

The held-out window is the 60 days ending 7 days ago. The trader's own data
(`/bars`) never reaches back more than 7 days, so it structurally cannot read
this window -- no access rule, just no route. A strategy submitted as code runs
in a throwaway container with no network; only aggregates come back, and each
employee gets a few evaluations a day, because every extra try is another
chance for a lucky-looking result (spike 4's p = 0.044 that lost 22.5 bps a trade).

Iterating on five tries a day was too slow: in its first two days the office tested
about one idea per trader per day, and three of eight tries died on a SyntaxError
or a missing import. So (2026-10-10):

- `backtest()` runs the SAME simulator, unlimited in practice, on data the trader
  may see -- "train", the history before the held-out window, or "recent", the
  last 7 days -- and returns every trade. It is the research tool; held-out is
  the exam.
- `evaluate()` first runs the code on a short training slice; code that fails to
  load or raises in decide() is sent back without spending a try.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from ..store import Store

HELDOUT_DAYS, GAP_DAYS = 60, 7
TRAIN_FROM_DAYS = 400          # as far back as the candles go (120 days backfilled on 2026-10-10)
PER_DAY = 5
BACKTESTS_PER_DAY = 200
WARMUP = 1440                  # bars decide() sees before the first decision
MAX_CODE = 20_000
TIMEOUT_S = 180
REPO = Path(__file__).resolve().parents[2]
IMAGE = os.environ.get("OFFICE_EVAL_IMAGE", "pixel-office-trader")
CACHE = Path(os.path.expanduser(os.environ.get("OFFICE_HELDOUT_DIR", "~/pixel-office/heldout")))


# Check the quota, run, and record as ONE step. Found live: two calls arriving together both
# read "0 used today", both ran, and both were recorded as try 1. Evaluations now run one at a time.
_LOCK = threading.Lock()
_BACKTESTS = threading.BoundedSemaphore(2)       # a backtest is one CPU for up to a minute


class EvalRefused(Exception):
    pass


def used_today(store: Store, employee: str) -> int:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return store.q("SELECT COUNT(*) AS n FROM events WHERE kind = 'evaluation' AND actor = ? AND ts >= ?",
                   (employee, day))[0]["n"]


def heldout_file(market) -> Path:
    """One file per UTC day: Kraken PF_XBTUSD candles and the hourly funding for the window."""
    from ..market import PRODUCT
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"{PRODUCT}_{datetime.now(timezone.utc):%Y-%m-%d}.json"
    if not p.exists():
        bars = market.bars_between(PRODUCT, (HELDOUT_DAYS + GAP_DAYS) * 1440, GAP_DAYS * 1440)
        t0 = datetime.fromisoformat(bars[0]["m"]).replace(tzinfo=timezone.utc).timestamp() if bars else 0
        t1 = datetime.fromisoformat(bars[-1]["m"]).replace(tzinfo=timezone.utc).timestamp() + 3600 if bars else 0
        p.write_text(json.dumps({"bars": bars, "funding": market.funding_history(PRODUCT, t0, t1)}))
    return p


def _cached(name: str, build) -> Path:
    from ..market import PRODUCT
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"{PRODUCT}_{name}.json"
    if not p.exists():
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(build()))
        tmp.replace(p)
    return p


def _with_funding(market, bars: list[dict]) -> dict:
    from ..market import PRODUCT
    t0 = datetime.fromisoformat(bars[0]["m"]).replace(tzinfo=timezone.utc).timestamp() if bars else 0
    t1 = datetime.fromisoformat(bars[-1]["m"]).replace(tzinfo=timezone.utc).timestamp() + 3600 if bars else 0
    return {"bars": bars, "funding": market.funding_history(PRODUCT, t0, t1) if bars else {}}


def train_file(market) -> Path:
    """Everything before the held-out window: the trader may look at it as much as it likes."""
    from ..market import PRODUCT
    return _cached(f"train_{datetime.now(timezone.utc):%Y-%m-%d}", lambda: _with_funding(
        market, market.bars_between(PRODUCT, TRAIN_FROM_DAYS * 1440, (HELDOUT_DAYS + GAP_DAYS) * 1440)))


def recent_file(market) -> Path:
    """The last 7 days -- what the trader already sees through /bars. Rebuilt hourly."""
    from ..market import PRODUCT
    return _cached(f"recent_{datetime.now(timezone.utc):%Y-%m-%d_%H}", lambda: _with_funding(
        market, market.bars_between(PRODUCT, GAP_DAYS * 1440, 0)))


def _slice(src: Path, days: float, tag: str) -> Path:
    """The last `days` of a data file, plus the warm-up decide() needs, as its own file."""
    data = json.loads(src.read_text())
    n = int(days * 1440) + WARMUP
    out = Path(tempfile.mkstemp(prefix=f"{tag}_", suffix=".json", dir=CACHE)[1])
    out.write_text(json.dumps({"bars": data["bars"][-n:], "funding": data.get("funding", {})}))
    return out


def docker_runner(bars: Path, code: str, detail: bool = False) -> dict:
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "strategy.py").write_text(code)
        (Path(d) / "bars.json").write_bytes(bars.read_bytes())
        os.chmod(d, 0o755)
        cmd = ["docker", "run", "--rm", "--network", "none", "--memory", "1g", "--cpus", "1",
               "-v", f"{REPO}:/app:ro", "-v", f"{d}:/in:ro", "-w", "/app", IMAGE,
               "python", "-m", "server.evaluator.run", "/in/bars.json", "/in/strategy.py"] + (["--detail"] if detail else [])
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return {"error": f"evaluation took longer than {TIMEOUT_S}s; make decide() faster"}
        lines = [l for l in r.stdout.strip().splitlines() if l.startswith("{")]
        if r.returncode != 0 or not lines:
            return {"error": f"evaluator failed: {(r.stderr or r.stdout)[-400:]}"}
        return json.loads(lines[-1])


def evaluate(store: Store, market, who: dict, code: str, runner=docker_runner, version: str | None = None) -> dict:
    if who["role"] != "trader":
        raise EvalRefused("only traders submit strategies for evaluation")
    if not code or len(code) > MAX_CODE:
        raise EvalRefused(f"code must be 1..{MAX_CODE} characters")
    with _LOCK:
        n = used_today(store, who["id"])
        if n >= PER_DAY:
            raise EvalRefused(f"you have used all {PER_DAY} evaluations today")
        broken = precheck(market, code, runner)
        if broken:
            raise EvalRefused(f"not evaluated, and no try spent: on 2 days of training data your code {broken}. "
                              "Fix it (backtest() shows the same error) and submit again.")
        result = runner(heldout_file(market), code)
        result["evaluations_used_today"] = n + 1
        # which candidate, and which strategy version the trader was on: what makes results comparable over time
        result["candidate"] = hashlib.sha256(code.encode()).hexdigest()[:10]
        result["version"] = version
        store.emit(who["id"], "evaluation", {k: v for k, v in result.items() if k != "reminder"})
        from .. import progress
        progress.announce(store, who["id"])
    result["reminder"] = ("Aggregates only, over the 60 days ending 7 days ago -- data you cannot fetch. "
                          f"This is try {n + 1} today; the more tries, the more likely one looks good by chance.")
    return result


def precheck(market, code: str, runner) -> str | None:
    """Run the code on a short training slice. Returns what is broken, or None."""
    p = _slice(train_file(market), 2, "precheck")
    try:
        r = runner(p, code)
    finally:
        p.unlink(missing_ok=True)
    if r.get("error"):
        return r["error"].removeprefix("your code ")
    if r.get("decide_errors"):
        return f"raised in decide() {r['decide_errors']} times, first: {r.get('first_error')}"
    return None


def backtests_today(store: Store, employee: str) -> int:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return store.q("SELECT COUNT(*) AS n FROM events WHERE kind = 'backtest' AND actor = ? AND ts >= ?",
                   (employee, day))[0]["n"]


def backtest(store: Store, market, who: dict, code: str, data: str = "train", days: float = 30,
             runner=docker_runner) -> dict:
    """The research tool: same simulator as the held-out exam, on data the caller may see,
    with every trade. Recorded as a quiet `backtest` event (counts only, no XP)."""
    if who["role"] not in ("trader", "manager"):
        raise EvalRefused("only traders and the manager run backtests")
    if not code or len(code) > MAX_CODE:
        raise EvalRefused(f"code must be 1..{MAX_CODE} characters")
    if data not in ("train", "recent"):
        raise EvalRefused("data must be 'train' (before the held-out window) or 'recent' (the last 7 days)")
    days = max(1.0, min(float(days), 60.0 if data == "train" else 6.0))
    if backtests_today(store, who["id"]) >= BACKTESTS_PER_DAY:
        raise EvalRefused(f"you have run {BACKTESTS_PER_DAY} backtests today")
    if not _BACKTESTS.acquire(timeout=240):
        raise EvalRefused("the backtest machines are busy; try again in a minute")
    try:
        p = _slice(train_file(market) if data == "train" else recent_file(market), days, "backtest")
        try:
            r = runner(p, code, True)
        finally:
            p.unlink(missing_ok=True)
    finally:
        _BACKTESTS.release()
    store.emit(who["id"], "backtest", {"data": data, "days": days, "trades": r.get("trades"),
                                       "net_bps_per_trade": r.get("net_bps_per_trade"), "error": r.get("error"),
                                       "candidate": hashlib.sha256(code.encode()).hexdigest()[:10]})
    r["note"] = (f"Research backtest on {data} data ({days:g} days) -- data you can see, so a good number here is a "
                 "hypothesis, not evidence. Held-out evaluate() is the test.")
    return r

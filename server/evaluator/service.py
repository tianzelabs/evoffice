"""The held-out evaluation, as the office runs it (P1.5, kept deliberately simple).

The held-out window is the 60 days ending 7 days ago. The trader's own data
(`/bars`) never reaches back more than 7 days, so it structurally cannot read
this window -- no access rule, just no route. A strategy submitted as code runs
in a throwaway container with no network; only aggregates come back, and each
employee gets a few evaluations a day, because every extra try is another
chance for a lucky-looking result (spike 4's p = 0.044 that lost 22.5 bps a trade).
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
PER_DAY = 5
MAX_CODE = 20_000
TIMEOUT_S = 180
REPO = Path(__file__).resolve().parents[2]
IMAGE = os.environ.get("OFFICE_EVAL_IMAGE", "pixel-office-trader")
CACHE = Path(os.path.expanduser(os.environ.get("OFFICE_HELDOUT_DIR", "~/pixel-office/heldout")))


# Check the quota, run, and record as ONE step. Found live: two calls arriving together both
# read "0 used today", both ran, and both were recorded as try 1. Evaluations now run one at a time.
_LOCK = threading.Lock()


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


def docker_runner(bars: Path, code: str) -> dict:
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "strategy.py").write_text(code)
        (Path(d) / "bars.json").write_bytes(bars.read_bytes())
        os.chmod(d, 0o755)
        cmd = ["docker", "run", "--rm", "--network", "none", "--memory", "1g", "--cpus", "1",
               "-v", f"{REPO}:/app:ro", "-v", f"{d}:/in:ro", "-w", "/app", IMAGE,
               "python", "-m", "server.evaluator.run", "/in/bars.json", "/in/strategy.py"]
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

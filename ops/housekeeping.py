"""Daily housekeeping: back up the ledger, compress old logs, prune caches.

    python ops/housekeeping.py            # what office-housekeeping.timer runs

- office.db is the only truth the office has (positions, events). It is backed
  up with SQLite's online backup API -- consistent while the server writes --
  to ~/pixel-office/backups/, keeping 14 days.
- Agents' trajectory logs grow ~3 MB per trader turn. Any log not written for an
  hour is gzipped; gzipped logs older than 14 days are deleted. The log an agent
  is writing right now is never touched.
- Held-out evaluation caches older than 3 days are deleted (one is built per day).

Prints one line per action, so the journal says what it did.
"""
from __future__ import annotations

import gzip
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home() / "pixel-office"
KEEP_DAYS, CACHE_DAYS, IDLE_S = 14, 3, 3600


def backup_db() -> None:
    src, dst_dir = HOME / "office.db", HOME / "backups"
    dst_dir.mkdir(exist_ok=True)
    dst = dst_dir / f"office-{datetime.now(timezone.utc):%Y-%m-%d}.db"
    with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
        s.backup(d)
    with sqlite3.connect(dst) as d:
        n = d.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    print(f"backup {dst.name}: {dst.stat().st_size // 1024} KB, {n} events")
    for old in sorted(dst_dir.glob("office-*.db"))[:-KEEP_DAYS]:
        old.unlink()
        print(f"deleted old backup {old.name}")


def rotate_logs() -> None:
    now = time.time()
    for log in HOME.glob("*-state/**/*.jsonl"):
        if now - log.stat().st_mtime < IDLE_S or log.name == "turns.jsonl":
            continue                       # being written, or the manager's eval record (kept whole)
        with open(log, "rb") as f, gzip.open(f"{log}.gz", "wb") as g:
            shutil.copyfileobj(f, g)
        log.unlink()
        print(f"compressed {log.relative_to(HOME)}")
    for gz in HOME.glob("*-state/**/*.jsonl.gz"):
        if now - gz.stat().st_mtime > KEEP_DAYS * 86400:
            gz.unlink()
            print(f"deleted old log {gz.relative_to(HOME)}")


def backup_repl() -> None:
    """The shared REPL is the office's memory (research, experience log, opportunity journal) and
    lives in one snapshot file: keep a daily copy, 14 days."""
    dst_dir = HOME / "backups"
    dst_dir.mkdir(exist_ok=True)
    for state in HOME.glob("trader-*-state"):
        src = state / "objects.dill"
        if not src.exists():
            continue
        dst = dst_dir / f"repl-{state.name}-{datetime.now(timezone.utc):%Y-%m-%d}.dill"
        shutil.copy2(src, dst)
        print(f"backup {dst.name}: {dst.stat().st_size // 1024} KB")
        for old in sorted(dst_dir.glob(f"repl-{state.name}-*.dill"))[:-KEEP_DAYS]:
            old.unlink()


def prune_heldout() -> None:
    """Caches per kind -- the daily held-out file, the daily train file, the hourly recent file.
    (Found 2026-10-10: one alphabetical "keep the last 3" across kinds would delete today's held-out
    file and let the hourly recent files pile up.)"""
    d = HOME / "heldout"
    kinds = {"heldout": [], "train": [], "recent": []}
    for f in d.glob("*.json"):
        kinds["train" if "_train_" in f.name else "recent" if "_recent_" in f.name else "heldout"].append(f)
    keep = {"heldout": CACHE_DAYS, "train": 2, "recent": 3}
    for kind, files in kinds.items():
        for f in sorted(files)[:-keep[kind]]:
            f.unlink()
            print(f"deleted {kind} cache {f.name}")
    for f in d.glob("*.json.tmp"):
        f.unlink()


if __name__ == "__main__":
    failed = False
    for step in (backup_db, backup_repl, rotate_logs, prune_heldout):
        try:
            step()
        except Exception as e:             # one failing step must not hide the others
            failed = True
            print(f"{step.__name__} FAILED: {type(e).__name__}: {e}")
    sys.exit(1 if failed else 0)

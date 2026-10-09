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


def prune_heldout() -> None:
    for f in sorted((HOME / "heldout").glob("*.json"))[:-CACHE_DAYS]:
        f.unlink()
        print(f"deleted held-out cache {f.name}")


if __name__ == "__main__":
    failed = False
    for step in (backup_db, rotate_logs, prune_heldout):
        try:
            step()
        except Exception as e:             # one failing step must not hide the others
            failed = True
            print(f"{step.__name__} FAILED: {type(e).__name__}: {e}")
    sys.exit(1 if failed else 0)

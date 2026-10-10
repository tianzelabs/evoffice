"""Office hours: the agents work 08:00-24:00 Budapest time (user, 2026-10-10); DST follows the zone.

Outside hours nobody starts a turn on their own -- only the boss can still get an answer.
Open positions are not closed at the end of the day; the max_hold backstop still runs.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo(os.environ.get("OFFICE_TZ", "Europe/Budapest"))
START, END = (int(x) for x in os.environ.get("OFFICE_HOURS", "8-24").split("-"))


def on_duty(now: datetime | None = None) -> bool:
    h = (now or datetime.now(timezone.utc)).astimezone(TZ).hour
    return START <= h < END


def describe() -> str:
    return f"{START:02d}:00-{END % 24:02d}:00 {TZ.key}"

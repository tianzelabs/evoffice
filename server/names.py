"""Names the agents choose for themselves.

The user asked that nobody be "trader-1": each agent picks its own name, which
fits the office's point -- an agent that shapes itself. The employee id stays
the key everywhere (tokens, ledger, versions); the name is what people see.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from .store import Store, now

NAME = re.compile(r"^[\w][\w .'-]{0,23}$", re.UNICODE)     # letters (any script), digits, space . ' -
RESERVED = {"boss", "office", "manager", "trader", "everyone", "all"}


class NameRefused(Exception):
    pass


def set_name(store: Store, who: dict, name: str) -> dict:
    name = " ".join(str(name).split())
    if who["role"] == "boss":
        raise NameRefused("the boss is the boss")
    if not NAME.match(name) or name.lower() in RESERVED or name.lower().startswith("trader-"):
        raise NameRefused("a name is 1-24 letters, digits, spaces or . ' - and not a role or an id")
    taken = store.q("SELECT id FROM employees WHERE lower(name) = lower(?) AND id != ?", (name, who["id"]))
    if taken:
        raise NameRefused(f"{name!r} is taken by {taken[0]['id']}")
    me = store.employee(who["id"])
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if me.get("name") and store.q("SELECT 1 FROM events WHERE kind = 'name' AND actor = ? AND ts >= ?", (who["id"], day)):
        raise NameRefused("you can rename once a day")
    store.x("UPDATE employees SET name = ? WHERE id = ?", (name, who["id"]))
    store.emit(who["id"], "name", {"employee": who["id"], "name": name, "previous": me.get("name"), "at": now()})
    from . import progress
    progress.announce(store, who["id"])
    return store.employee(who["id"])

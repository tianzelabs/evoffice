"""How an agent talks to the office: HTTP with its own token, nothing else.

An agent holds an office token, never a model key; model calls go to the
office's /llm gateway with this same token (see server/llm.py).
"""
from __future__ import annotations

import os

import httpx


class Refused(Exception):
    """The office said no. The message is for the agent to read and act on."""


class Office:
    def __init__(self, url: str | None = None, token: str | None = None, timeout: float = 30.0):
        self.url = (url or os.environ["OFFICE_URL"]).rstrip("/")
        self.token = token or os.environ["OFFICE_TOKEN"]
        self.http = httpx.Client(base_url=self.url, timeout=timeout,
                                 headers={"Authorization": f"Bearer {self.token}"})

    def _ok(self, r: httpx.Response):
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except Exception:
                detail = r.text
            raise Refused(f"{r.status_code}: {detail}")
        return r.json()

    def get(self, path: str, **params):
        return self._ok(self.http.get(path, params=params))

    def post(self, path: str, body: dict | None = None):
        return self._ok(self.http.post(path, json=body or {}))

    # the acts
    def me(self) -> dict: return self.get("/me")
    def say(self, text: str, to: str | None = None) -> dict: return self.post("/say", {"text": text, "to": to})
    def report(self, kind: str, payload: dict) -> dict: return self.post("/report", {"kind": kind, "payload": payload})
    def price(self) -> dict: return self.get("/price")
    def bars(self, minutes: int) -> list[dict]: return self.get("/bars", minutes=minutes)
    def events(self, since: int) -> list[dict]: return self.get("/events", since=since)
    def positions(self, employee: str, open_only: bool = False) -> list[dict]:
        return self.get("/positions", employee=employee, open=str(open_only).lower())
    def budget(self) -> dict: return self.get("/budget/me")

    def open_position(self, side: str, size: float, strategy_version: str | None = None,
                      max_hold_s: int | None = None) -> dict:
        return self.post("/positions/open", {"side": side, "size": size, "strategy_version": strategy_version,
                                             "max_hold_s": max_hold_s})

    def close_position(self, position_id: int) -> dict:
        return self.post(f"/positions/{int(position_id)}/close")

    def evaluate(self, code: str) -> dict:
        return self.post("/evaluate", {"code": code})

    def jev(self, state, questions: dict) -> dict:
        r = self.post("/llm/api/alpha/decisions", {"model": "typesafe/jev-1.13", "state": state, "questions": questions})
        return r.get("answers", r)

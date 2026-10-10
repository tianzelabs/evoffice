"""The office server: HTTP for every act, SSE for everything that happened.

Everyone -- trader, manager, the web page, the boss -- is a client with the same
standing, and can do exactly what these routes offer. There is deliberately no
route that edits fees, settlement, prices, budgets or the ledger: that absence
is what makes "the manager cannot demolish the office" structural.

Run:  OFFICE_DB=~/pixel-office/office.db OFFICE_TOKENS=~/pixel-office/tokens.json \
      uvicorn server.app:app --host 0.0.0.0 --port 8710
tokens.json: {"<token>": {"id": "boss", "role": "boss"}, ...}  -- kept outside the repo.
"""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import broker, fees, objective, iterations, leaderboard, names, orders, positions, progress, scheduler, seasons, staff
from .evaluator import service as evaluation
from .llm import Gateway, GatewayRefused, budget
from .market import PRODUCT, FuturesMarket, Stale
from .store import Store

STATIC = Path(__file__).with_name("static")
WEB = Path(__file__).resolve().parents[1] / "web" / "dist"     # the pixel office (P3), built by `npm run build`
MAX_SAY = 2000


class Say(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_SAY)
    to: str | None = None


REPORTABLE = {"wake", "version", "agent_state", "turn", "task_result", "trigger", "repl_result"}   # what an agent may say about itself


class Report(BaseModel):
    kind: str
    payload: dict


class Params(BaseModel):
    heartbeat_min: int | None = None
    max_size: float | None = None
    max_hold_min: int | None = None
    reason: str = ""


class Fire(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    replace: bool = True


class Repl(BaseModel):
    code: str = Field(min_length=1, max_length=20_000)


class Task(BaseModel):
    to: str
    text: str = Field(min_length=1, max_length=6000)


class Name(BaseModel):
    name: str


class Evaluate(BaseModel):
    code: str
    version: str | None = None


class Backtest(BaseModel):
    code: str
    data: str = "train"
    days: float = 30


class Order(BaseModel):
    intent: str                       # "open" | "close"
    price: float
    size: float | None = None         # for intent = open
    side: str | None = None           # "long" | "short", for intent = open
    position_id: int | None = None    # for intent = close
    post_only: bool = True
    ttl_minutes: int | None = None
    strategy_version: str | None = None


class Open(BaseModel):
    side: str
    size: float
    pair: str = PRODUCT
    strategy_version: str | None = None
    max_hold_s: int | None = Field(default=None, gt=0)


def create_app(store: Store, market, tokens: dict[str, dict], backstop_every_s: float = 10.0,
               gateway: Gateway | None = None, eval_runner=None, tokens_path: Path | None = None) -> FastAPI:
    eval_runner = eval_runner or evaluation.docker_runner
    gateway = gateway or Gateway(store)
    for who in tokens.values():
        store.hire(who["id"], who["role"])

    @asynccontextmanager
    async def lifespan(_app):
        async def backstop():
            while True:
                await asyncio.sleep(backstop_every_s)
                await run_in_threadpool(positions.enforce_max_hold, store, market)
                await run_in_threadpool(scheduler.tick, store, market)      # stand-up and market alerts
        async def matcher():
            while True:                    # resting limit orders: filled when the market trades through them
                await asyncio.sleep(2)
                await run_in_threadpool(orders.match, store, market)
        tasks = [asyncio.create_task(backstop()), asyncio.create_task(matcher())] if backstop_every_s > 0 else []
        yield
        for t in tasks:
            t.cancel()

    app = FastAPI(title="pixel-office", lifespan=lifespan)

    def who(authorization: str | None = Header(default=None)) -> dict:
        token = (authorization or "").removeprefix("Bearer ").strip()
        if token not in tokens:
            raise HTTPException(401, "unknown token")
        return tokens[token]

    def refused(e: Exception) -> HTTPException:
        return HTTPException(409, str(e))

    @app.get("/")
    def index():
        page = WEB / "index.html"
        # revalidate the page every time; its assets are content-hashed, so a new build is picked up at once
        return FileResponse(page if page.exists() else STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/text")
    def text_view():
        return FileResponse(STATIC / "index.html")

    app.mount("/assets", StaticFiles(directory=WEB / "assets", check_dir=False), name="assets")
    app.mount("/kenney", StaticFiles(directory=WEB / "kenney", check_dir=False), name="kenney")   # CC0 art, see its README

    @app.get("/me")
    def me(w: dict = Depends(who)):
        return w

    @app.get("/events")
    def events(since: int = 0):
        return store.events_since(since)

    @app.get("/stream")
    async def stream(request: Request, since: int = 0):
        """SSE. Polls the events table: a few clients, one writer, no fan-out machinery."""
        async def gen():
            last, idle = since, 0
            while not await request.is_disconnected():
                rows = await run_in_threadpool(store.events_since, last)
                for r in rows:
                    last = r["id"]
                    yield f"id: {r['id']}\ndata: {json.dumps(r, ensure_ascii=False)}\n\n"
                idle = 0 if rows else idle + 1
                if idle and idle % 30 == 0:
                    yield ": keepalive\n\n"
                await asyncio.sleep(0.5)
        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/say")
    def say(body: Say, w: dict = Depends(who)):
        return store.emit(w["id"], "say", {"text": body.text, "to": body.to, "role": w["role"]})

    @app.get("/price")
    async def price(pair: str = PRODUCT):
        try:
            q = await run_in_threadpool(market.quote, pair)
        except (Stale, ValueError) as e:
            raise HTTPException(503, str(e))
        return {"pair": q.pair, "price": q.price, "bid": q.bid, "ask": q.ask, "mark": q.mark,
                "funding_per_hour": q.funding_per_hour, "age_s": round(q.age_s, 2),
                "fees": {"regime": fees.REGIME, "maker": fees.MAKER, "taker": fees.TAKER}}

    @app.post("/orders")
    async def place_order(body: Order, w: dict = Depends(who)):
        try:
            return await run_in_threadpool(orders.place, store, market, w, body.intent, body.size, body.price,
                                           body.side, body.position_id, body.post_only, body.ttl_minutes,
                                           body.strategy_version)
        except orders.OrderRefused as e:
            raise HTTPException(409, str(e))

    @app.post("/orders/{order_id}/cancel")
    def cancel_order(order_id: int, w: dict = Depends(who)):
        try:
            return orders.cancel(store, w, order_id)
        except orders.OrderRefused as e:
            raise HTTPException(409, str(e))

    @app.get("/orders")
    def list_orders(employee: str | None = None, open: bool = False):
        return orders.listing(store, employee, open)

    @app.post("/positions/open")
    async def open_(body: Open, w: dict = Depends(who)):
        try:
            return await run_in_threadpool(positions.open_position, store, market, w["id"], body.pair,
                                           body.side, body.size, body.strategy_version, body.max_hold_s)
        except positions.Refused as e:
            raise refused(e)

    @app.post("/positions/{position_id}/close")
    async def close(position_id: int, w: dict = Depends(who)):
        try:
            return await run_in_threadpool(positions.close_position, store, market, position_id, w["id"], "self")
        except positions.Refused as e:
            raise refused(e)

    @app.get("/positions")
    def listing(employee: str | None = None, open: bool = False):
        return positions.listing(store, employee, open)

    @app.get("/leaderboard")
    def board():
        return leaderboard.standings(store)

    @app.get("/objective")
    def get_objective():
        """The manager's objective ladder: from minus to plus, computed from the record."""
        return objective.compute(store)

    @app.get("/golive/{employee_id}")
    def golive(employee_id: str):
        """Read-only: has this trader earned a real Kraken account? The switch itself is the user's."""
        return broker.checklist(store, employee_id)

    @app.get("/season")
    def season():
        """This week's standings, when it ends, and every trophy handed out so far."""
        return seasons.summary(store)

    @app.get("/progress")
    def progress_all():
        """XP, level, title, perks, probation and badges per trader -- earned by validated improvement."""
        return progress.all_progress(store)

    @app.get("/iterations")
    def iteration_timeline():
        """Each trader's strategy versions with their held-out evaluations: did the change help?"""
        return iterations.timeline(store)

    @app.get("/bars")
    async def bars(minutes: int = 60, pair: str = PRODUCT):
        try:
            return await run_in_threadpool(market.bars, pair, minutes)
        except (Stale, ValueError) as e:
            raise HTTPException(503, str(e))

    @app.post("/report")
    def report(body: Report, w: dict = Depends(who)):
        """An agent reporting on itself (woke, new strategy version, what it is doing). Never about others."""
        if body.kind not in REPORTABLE:
            raise HTTPException(422, f"kind must be one of {sorted(REPORTABLE)}")
        if len(json.dumps(body.payload)) > 4000:
            raise HTTPException(413, "payload too large")
        ev = store.emit(w["id"], body.kind, body.payload)
        if body.kind == "version":
            progress.announce(store, w["id"])
        return ev

    @app.post("/me/name")
    def name_me(body: Name, w: dict = Depends(who)):
        try:
            return names.set_name(store, w, body.name)
        except names.NameRefused as e:
            raise HTTPException(409, str(e))

    @app.get("/employees")
    def employees():
        rows = store.q("SELECT * FROM employees ORDER BY hired_ts")
        for r in rows:
            r["params"] = json.loads(r["params"])
        return rows

    @app.post("/employees/{employee_id}/params")
    def params(employee_id: str, body: Params, w: dict = Depends(who)):
        try:
            return staff.set_params(store, w, employee_id, body.model_dump(exclude={"reason"}), body.reason)
        except staff.StaffRefused as e:
            raise HTTPException(409, str(e))

    @app.post("/employees/{employee_id}/fire")
    async def fire(employee_id: str, body: Fire, w: dict = Depends(who)):
        try:
            return await run_in_threadpool(staff.fire, store, market, w, employee_id, body.reason, tokens, tokens_path,
                                           body.replace)
        except staff.StaffRefused as e:
            raise HTTPException(409, str(e))

    @app.post("/evaluate")
    async def evaluate(body: Evaluate, w: dict = Depends(who)):
        """Score a strategy (code defining decide(bars)) on the held-out window. Aggregates only."""
        try:
            return await run_in_threadpool(evaluation.evaluate, store, market, w, body.code, eval_runner, body.version)
        except evaluation.EvalRefused as e:
            raise HTTPException(409, str(e))

    @app.post("/tasks")
    def give_task(body: Task, w: dict = Depends(who)):
        """The manager (or boss) hands a trader a task. The trader's runner runs ONE RLM turn on it in
        the trader's own REPL and reports a `task_result` naming this task's event id."""
        if w["role"] not in ("manager", "boss"):
            raise HTTPException(403, "only the manager or the boss gives tasks")
        emp = store.employee(body.to)
        if not emp or emp["role"] != "trader" or emp["fired_ts"]:
            raise HTTPException(409, f"no working trader {body.to!r}")
        return store.emit(w["id"], "task", {"to": body.to, "text": body.text})

    @app.post("/repl")
    def run_in_shared_repl(body: Repl, w: dict = Depends(who)):
        """Run code in the office's ONE shared REPL (user, 2026-10-10: everyone works in the same REPL).
        It lives in the trader's process; the runner executes it between turns and reports `repl_result`."""
        if w["role"] not in ("manager", "boss"):
            raise HTTPException(403, "the trader already works in the shared REPL; this route is for the manager and boss")
        if not store.q("SELECT id FROM employees WHERE role = 'trader' AND fired_ts IS NULL"):
            raise HTTPException(409, "no working trader hosts the shared REPL")
        return store.emit(w["id"], "repl", {"code": body.code, "lines": body.code.count("\n") + 1})

    @app.get("/repl/{req_id}")
    def repl_status(req_id: int):
        rows = store.q("SELECT ts, payload FROM events WHERE kind = 'repl_result' "
                       "AND json_extract(payload, '$.req') = ? ORDER BY id DESC LIMIT 1", (req_id,))
        if not rows:
            return {"req": req_id, "status": "pending"}
        return {"req": req_id, "status": "done", "ts": rows[0]["ts"], **json.loads(rows[0]["payload"])}

    @app.get("/tasks/{task_id}")
    def task_status(task_id: int):
        rows = store.q("SELECT id, ts, actor, payload FROM events WHERE kind = 'task_result' "
                       "AND json_extract(payload, '$.task') = ? ORDER BY id DESC LIMIT 1", (task_id,))
        if not rows:
            return {"task": task_id, "status": "pending"}
        r = rows[0]
        return {"task": task_id, "status": "done", "ts": r["ts"], "by": r["actor"], **json.loads(r["payload"])}

    @app.post("/backtest")
    async def backtest(body: Backtest, w: dict = Depends(who)):
        """Same simulator as /evaluate, on data the caller may see, with every trade. The research tool."""
        try:
            return await run_in_threadpool(evaluation.backtest, store, market, w, body.code, body.data, body.days,
                                           eval_runner)
        except evaluation.EvalRefused as e:
            raise HTTPException(409, str(e))

    @app.get("/budget")
    def budgets():
        rows = store.q("SELECT id, role FROM employees WHERE role != 'boss' AND fired_ts IS NULL ORDER BY id")
        return [budget(store, r["id"], r["role"]) for r in rows]

    @app.get("/budget/me")
    def my_budget(w: dict = Depends(who)):
        return budget(store, w["id"], w["role"])

    async def _llm(route: str, request: Request, w: dict):
        try:
            return await run_in_threadpool(gateway.forward, w, route, await request.json())
        except GatewayRefused as e:
            raise HTTPException(e.status, str(e))

    @app.post("/llm/v1/chat/completions")
    async def llm_chat(request: Request, w: dict = Depends(who)):
        return await _llm("chat", request, w)

    @app.post("/llm/api/alpha/decisions")
    async def llm_decisions(request: Request, w: dict = Depends(who)):
        return await _llm("decisions", request, w)

    return app


def _from_env() -> FastAPI:
    db = os.path.expanduser(os.environ.get("OFFICE_DB", "~/pixel-office/office.db"))
    os.makedirs(os.path.dirname(db), exist_ok=True)
    tokens_path = Path(os.path.expanduser(os.environ.get("OFFICE_TOKENS", "~/pixel-office/tokens.json")))
    return create_app(Store(db), FuturesMarket(), json.loads(tokens_path.read_text()), tokens_path=tokens_path)


app = _from_env() if os.environ.get("OFFICE_DB") or os.environ.get("OFFICE_TOKENS") else None

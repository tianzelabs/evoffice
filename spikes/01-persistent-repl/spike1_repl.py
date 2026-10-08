"""Spike 1: can a persistent DockerREPL run code with NO model call, how fast,
what survives between cells, and can state survive a process restart?

No LLM is involved anywhere in this script.
"""
import os
import shutil
import statistics
import time

from rlm.environments.docker_repl import DockerREPL

WS = os.path.expanduser("~/pixel-office-home/spike/ws")
os.environ["RLM_DOCKER_WORKSPACE_DIR"] = WS
os.makedirs(WS, exist_ok=True)
IMAGE = os.environ.get("SPIKE_IMAGE", "python:3.11-slim")


def run(env, code):
    r = env.execute_code(code)
    return r.stdout.strip(), r.stderr.strip(), r.execution_time


t0 = time.perf_counter()
env = DockerREPL(image=IMAGE, persistent=True)
print(f"[setup] container up + deps installed in {time.perf_counter() - t0:.1f}s")

# 1. the trader defines a strategy function, a trigger, a closure, a class, and state
out = run(env, '''
import math
prices = [100.0, 100.5, 101.2, 100.9]
def fee_hurdle(px, bps=8):
    return px * bps / 10_000
def trigger(px_now, px_then):
    return abs(px_now - px_then) > 2 * fee_hurdle(px_now)
def make_counter():
    n = [0]
    def inc():
        n[0] += 1
        return n[0]
    return inc
counter = make_counter()
class Book:
    def __init__(self): self.rows = []
    def add(self, x): self.rows.append(x); return len(self.rows)
book = Book()
gen = (i for i in range(3))
import threading
lock = threading.Lock()
print("defined")
''')
print("[define]", out)

# 2. the next cell: does each survive?
out = run(env, '''
checks = {}
for name in ["prices", "fee_hurdle", "trigger", "counter", "Book", "book", "gen", "lock", "math"]:
    checks[name] = name in dir()
print(checks)
print("trigger:", trigger(101.0, 100.0), "counter:", counter(), counter(), "book:", book.add(1), book.add(2))
''')
print("[survive]", out)

# 3. does mutation persist across cells (counter / book state)?
print("[mutate]", run(env, 'print("counter:", counter(), "book rows:", book.rows)'))

# 4. the watcher's call: a trigger check with no model, timed
times = []
for i in range(20):
    _, err, t = run(env, f'print(trigger({100 + i * 0.3}, 100.0))')
    times.append(t)
print(f"[watcher] 20 trigger checks: median {statistics.median(times)*1000:.0f}ms, "
      f"max {max(times)*1000:.0f}ms")

# 5. state growth: a trader keeping a long price history in the REPL
run(env, 'hist = [100.0 + (i % 50) * 0.01 for i in range(200_000)]')
_, _, t = run(env, 'print(len(hist))')
size = os.path.getsize(os.path.join(env.temp_dir, "state.dill"))
print(f"[growth] 200k-float history: state.dill {size/1e6:.1f}MB, cell {t*1000:.0f}ms")

# 6. restart: copy state.dill into a brand new env, as a runner restart would
saved = os.path.join(WS, "state.dill.bak")
shutil.copy(os.path.join(env.temp_dir, "state.dill"), saved)
env.cleanup()
env2 = DockerREPL(image=IMAGE, persistent=True)
shutil.copy(saved, os.path.join(env2.temp_dir, "state.dill"))
print("[restart]", run(env2, 'print("trigger" in dir(), "counter" in dir(), len(hist), book.rows)'))

# 7. can the container reach the host proxy? (llm_query depends on it; spike 2 needs it)
print("[proxy]", run(env2, f'''
import requests
try:
    r = requests.post("http://host.docker.internal:{env2.proxy_port}/llm_query", json={{}}, timeout=5)
    print("reached host proxy, status", r.status_code)
except Exception as e:
    print("UNREACHABLE:", type(e).__name__, str(e)[:120])
'''))
env2.cleanup()
os.remove(saved)

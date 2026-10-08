"""Spike 1b: WHY do functions vanish in DockerREPL, and does LocalREPL keep them?"""
import os
import statistics

from rlm.environments.docker_repl import DockerREPL
from rlm.environments.local_repl import LocalREPL

os.environ["RLM_DOCKER_WORKSPACE_DIR"] = os.path.expanduser("~/pixel-office-home/spike/ws")

env = DockerREPL(persistent=True)
r = env.execute_code('''
import dill
print("dill", dill.__version__)
def trigger(a, b): return a > b
try:
    dill.dumps(trigger); print("dumps(trigger) OK")
except Exception as e:
    print("dumps(trigger) FAILED:", type(e).__name__, str(e)[:200])
''')
print("[docker why]", r.stdout.strip(), r.stderr.strip()[-300:])
env.cleanup()

loc = LocalREPL(persistent=True)
loc.execute_code('''
def trigger(px_now, px_then): return abs(px_now - px_then) > 0.016 * px_now / 100
def make_counter():
    n = [0]
    def inc():
        n[0] += 1; return n[0]
    return inc
counter = make_counter()
class Book:
    def __init__(self): self.rows = []
    def add(self, x): self.rows.append(x); return len(self.rows)
book = Book()
''')
r = loc.execute_code('print(trigger(101, 100), counter(), counter(), book.add(1), book.add(2))')
print("[local survive]", r.stdout.strip(), r.stderr.strip()[-200:])
r = loc.execute_code('print(counter(), book.rows)')
print("[local mutate]", r.stdout.strip(), r.stderr.strip()[-200:])
ts = [loc.execute_code(f'print(trigger({100 + i * 0.3}, 100))').execution_time for i in range(20)]
print(f"[local watcher] median {statistics.median(ts)*1000:.2f}ms max {max(ts)*1000:.2f}ms")
r = loc.execute_code('import os; print(os.getuid(), os.path.exists(os.path.expanduser("~/.village.env")))')
print("[local reach] uid, can see ~/.village.env:", r.stdout.strip())
loc.cleanup()
